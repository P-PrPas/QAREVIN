"""Deterministic M1 event simulation, conservative OHLC fills and equity accounting."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

import numpy as np
import pandas as pd

from qarevin.data import validate_bars
from qarevin.domain import ResearchConfig, canonical_json, digest
from qarevin.strategies import StrategySpec, signals


@dataclass
class Position:
    side: int
    lots: float
    entry: float
    stop: float
    opened: str
    entry_fee: float


def size_lots(equity: float, stop_distance: float, config: ResearchConfig) -> float:
    spec, costs = config.instrument, config.costs
    if equity <= 0 or not np.isfinite(stop_distance) or stop_distance <= 0:
        return 0
    risk_per_lot = (stop_distance + 2 * costs.slippage_points * spec.point) / spec.tick_size * spec.tick_value
    risk_per_lot += 2 * costs.commission_per_lot_side
    raw = min(equity * config.risk.per_trade / risk_per_lot, spec.volume_max,
              equity / spec.margin_per_lot)
    step = Decimal(str(spec.volume_step))
    lots = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    return lots if lots >= spec.volume_min else 0


def run_backtest(bars: pd.DataFrame, config: ResearchConfig, strategy: StrategySpec,
                 *, signal_frame: pd.DataFrame | None = None) -> dict:
    validate_bars(bars)
    decisions = signals(bars, strategy) if signal_frame is None else signal_frame.copy()
    if not isinstance(decisions.index, pd.DatetimeIndex) or decisions.index.tz is None:
        raise ValueError("signals require availability timestamps")
    if not decisions.index.is_monotonic_increasing or decisions.index.has_duplicates:
        raise ValueError("signals unordered or duplicated")
    if not decisions.empty and (not np.isfinite(decisions[["side", "stop_distance"]].to_numpy()).all()
                               or not decisions.side.isin([-1, 0, 1]).all()
                               or (decisions.stop_distance <= 0).any()):
        raise ValueError("invalid signal")
    spec, cost, policy = config.instrument, config.costs, config.risk
    slip = cost.slippage_points * spec.point
    unit = spec.tick_value / spec.tick_size
    balance = config.initial_equity
    high_water = balance
    day_start = balance
    day = None
    halted_day = False
    halted_drawdown = False
    position = None
    trades, equity, events = [], [], []
    cursor = 0
    times = decisions.index

    def mark(bid: float, spread: float) -> float:
        if position is None:
            return balance
        liquidation = bid if position.side == 1 else bid + spread
        return balance + position.side * (liquidation - position.entry) * position.lots * unit

    def close(bid: float, spread: float, timestamp, reason: str):
        nonlocal position, balance
        price = (bid if position.side == 1 else bid + spread) - position.side * slip
        gross = position.side * (price - position.entry) * position.lots * unit
        fee = position.lots * cost.commission_per_lot_side
        balance += gross - fee
        trades.append({"opened": position.opened, "closed": timestamp.isoformat(),
                       "side": position.side, "lots": position.lots, "entry": position.entry,
                       "exit": price, "gross_pnl": gross, "fees": fee + position.entry_fee,
                       "net_pnl": gross - fee - position.entry_fee, "reason": reason})
        position = None

    for timestamp, row in bars.iterrows():
        spread = (float(row.get("spread_points", cost.spread_points))) * spec.point
        if not np.isfinite(spread) or spread < 0:
            raise ValueError("invalid spread")
        local = timestamp.tz_convert(config.session.timezone)
        risk_day = timestamp.tz_convert(policy.risk_day_timezone).date()
        if day != risk_day:
            if position is not None:
                close(float(row.open), spread, timestamp, "missed_cutoff_gap")
            day, day_start, halted_day = risk_day, balance, False
        if position:
            # Gap stops precede new decisions. Short stops trigger on ask.
            open_exit = float(row.open) + (spread if position.side == -1 else 0)
            if (position.side == 1 and open_exit <= position.stop) or (position.side == -1 and open_exit >= position.stop):
                close(float(row.open), spread, timestamp, "gap_stop")
        current = mark(float(row.open), spread)
        high_water = max(high_water, current)
        halted_day |= current <= day_start * (1 - policy.daily_loss)
        halted_drawdown |= current <= high_water * (1 - policy.max_drawdown)
        cutoff = local.weekday() >= 5 or local.hour >= config.session.flatten_hour
        if position and (cutoff or halted_day or halted_drawdown):
            close(float(row.open), spread, timestamp, "cutoff" if cutoff else "risk_halt")
        latest = None
        while cursor < len(times) and times[cursor] <= timestamp:
            latest = decisions.iloc[cursor]
            cursor += 1
        # Signals expire if their immediate M1 execution event was missing (e.g. a weekend gap).
        if latest is not None and times[cursor - 1] != timestamp:
            latest = None
        if latest is not None:
            direction = int(latest.side)
            if position and direction != position.side:
                close(float(row.open), spread, timestamp, "signal")
            current = mark(float(row.open), spread)
            halted_day |= current <= day_start * (1 - policy.daily_loss)
            halted_drawdown |= current <= high_water * (1 - policy.max_drawdown)
            eligible = (config.session.entry_start_hour <= local.hour < config.session.entry_end_hour
                        and local.weekday() < 5 and not halted_day and not halted_drawdown
                        and spread / spec.point <= policy.max_spread_points)
            if direction and position is None and eligible:
                distance = float(latest.stop_distance)
                # Stop distance is measured from fill; cover spread so broker-side stop is valid.
                if distance >= spec.stop_distance_min + spread + slip + spec.tick_size:
                    lots = size_lots(balance, distance, config)
                    if lots:
                        price = float(row.open) + (spread if direction == 1 else 0) + direction * slip
                        raw_stop = price - direction * distance
                        tick = Decimal(str(spec.tick_size))
                        # Round toward entry, so rounding cannot silently increase planned loss.
                        mode = ROUND_FLOOR if direction == -1 else 'ROUND_CEILING'
                        stop = float((Decimal(str(raw_stop)) / tick).to_integral_value(rounding=mode) * tick)
                        fee = lots * cost.commission_per_lot_side
                        balance -= fee
                        position = Position(direction, lots, price, stop, timestamp.isoformat(), fee)
                        events.append({"time": timestamp.isoformat(), "event": "entry", "lots": lots})
                    else:
                        events.append({"time": timestamp.isoformat(), "event": "skip_min_lot_or_margin"})
        worst_equity = mark(float(row.open), spread)
        if position:
            adverse_bid = float(row.low if position.side == 1 else row.high)
            adverse_exit = adverse_bid + (spread if position.side == -1 else 0)
            stop_hit = (position.side == 1 and adverse_exit <= position.stop) or (position.side == -1 and adverse_exit >= position.stop)
            if stop_hit:
                stop_bid = position.stop if position.side == 1 else position.stop - spread
                close(stop_bid, spread, timestamp, "stop")
                worst_equity = min(worst_equity, balance)
            else:
                worst = mark(adverse_bid, spread)
                worst_equity = min(worst_equity, worst)
                if worst <= day_start * (1 - policy.daily_loss) or worst <= high_water * (1 - policy.max_drawdown):
                    halted_day |= worst <= day_start * (1 - policy.daily_loss)
                    halted_drawdown |= worst <= high_water * (1 - policy.max_drawdown)
                    # OHLC cannot sequence threshold crossing: adverse extreme is conservative.
                    close(adverse_bid, spread, timestamp, "risk_halt_adverse")
        current = mark(float(row.close), spread)
        high_water = max(high_water, current)
        halted_day |= current <= day_start * (1 - policy.daily_loss)
        halted_drawdown |= current <= high_water * (1 - policy.max_drawdown)
        equity.append({"time": (timestamp + pd.Timedelta(minutes=1)).isoformat(),
                       "equity": current, "worst_equity": min(current, worst_equity), "balance": balance, "drawdown": max(0, 1 - min(current, worst_equity) / high_water)})
    if position:
        close(float(bars.iloc[-1].close), spread, bars.index[-1] + pd.Timedelta(minutes=1), "end_of_data")
        equity[-1].update(equity=balance, balance=balance, drawdown=max(0, 1 - balance / high_water))
    result = {"schema": 1, "strategy": strategy.model_dump(mode="json"), "config_hash": digest(config),
              "initial_equity": config.initial_equity, "final_equity": balance,
              "trades": trades, "equity": equity, "events": events,
              "limitations": ["M1 bid OHLC with spread proxy; no intrabar tick path", "static contract/margin; no swap because overnight positions prohibited"],
              "promotion_ready": False}
    # Ensure no NaN/Infinity can become a score or artifact.
    canonical_json(result)
    return result | {"result_hash": digest(result)}
