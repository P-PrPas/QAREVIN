"""Independent accounting verification and explicit evidence gates."""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from qarevin.domain import Contract, ResearchConfig, digest


class EvaluationProtocol(Contract):
    schema_version: Literal[1] = 1
    minimum_trades: int = Field(default=100, ge=100)
    max_drawdown: float = Field(default=0.15, gt=0, le=0.15)
    minimum_profit_factor: float = Field(default=1.2, ge=1.2)
    minimum_calmar: float = Field(default=0.5, ge=0.5)
    minimum_annualization_days: int = Field(default=365, ge=365)
    # Promotion requires the separate robustness protocol/results, never a boolean supplied by an agent.
    robustness_protocol_hash: str | None = None


def metrics(result: dict, *, minimum_days: int = 365) -> dict:
    payload = {key: value for key, value in result.items() if key != 'result_hash'}
    if digest(payload) != result['result_hash']:
        raise ValueError('simulation result hash mismatch')
    initial, final = result['initial_equity'], result['final_equity']
    if initial <= 0 or not math.isfinite(initial) or not math.isfinite(final):
        raise ValueError('invalid equity')
    pnl = np.array([t['net_pnl'] for t in result['trades']], dtype=float)
    if not np.isfinite(pnl).all() or not math.isclose(initial + float(pnl.sum()), final, abs_tol=1e-7):
        raise ValueError('trade/equity reconciliation mismatch')
    curve = pd.DataFrame(result['equity'])
    if curve.empty:
        raise ValueError('missing equity')
    curve.index = pd.to_datetime(curve.pop('time'), utc=True)
    if not curve.index.is_monotonic_increasing or curve.index.has_duplicates:
        raise ValueError('invalid equity times')
    if not np.isfinite(curve[['equity', 'worst_equity']].to_numpy()).all():
        raise ValueError('nonfinite equity')
    if not math.isclose(float(curve.equity.iloc[-1]), final, abs_tol=1e-7):
        raise ValueError('final equity mismatch')
    peaks = np.maximum.accumulate(np.r_[initial, curve.get("peak_equity", curve.equity).to_numpy()])[1:]
    worst = np.minimum(curve.equity.to_numpy(), curve.worst_equity.to_numpy())
    dd = float(np.maximum(0, 1 - worst / peaks).max())
    daily = curve.equity.resample('1D').last().ffill()
    returns = np.diff(np.r_[initial, daily.to_numpy()]) / np.r_[initial, daily.to_numpy()[:-1]]
    days = (pd.Timestamp(result.get("end_time", curve.index[-1])) - pd.Timestamp(result.get("start_time", curve.index[0]))).total_seconds() / 86400 + 1 / 1440
    winners = float(pnl[pnl > 0].sum())
    losses = -float(pnl[pnl < 0].sum())
    pf = winners / losses if losses > 0 else None
    cagr = (final / initial) ** (365.25 / days) - 1 if days >= minimum_days and final > 0 else None
    calmar = cagr / dd if cagr is not None and dd > 0 else None
    sharpe = float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252)) if len(returns) >= 30 and np.std(returns, ddof=1) > 0 else None
    score = {'net_pnl': final - initial, 'net_return': final / initial - 1, 'max_drawdown': dd,
             'trade_count': len(pnl), 'profit_factor': pf, 'cagr': cagr, 'calmar': calmar,
             'sharpe': sharpe, 'calendar_days': days,
             'worst_day_return': float(min(returns)),
             'expected_shortfall_5pct': float(np.mean(np.sort(returns)[:max(1, math.ceil(.05 * len(returns)))])),
             'undefined_reasons': {'profit_factor': 'no losing trades' if pf is None else None,
                                   'cagr': 'insufficient horizon or nonpositive final equity' if cagr is None else None,
                                   'calmar': 'undefined CAGR or zero drawdown' if calmar is None else None,
                                   'sharpe': 'fewer than 30 days or zero volatility' if sharpe is None else None}}
    for key, value in list(score.items()):
        if isinstance(value, float) and not math.isfinite(value):
            score[key] = None
    return score


def evaluate(result: dict, config: ResearchConfig, protocol: EvaluationProtocol = EvaluationProtocol(),
             *, evidence_kind: Literal['backtest', 'walk_forward', 'holdout', 'demo', 'live'] = 'backtest') -> dict:
    if result.get("config_hash") != digest(config):
        raise ValueError("config/result identity mismatch")
    score = metrics(result, minimum_days=protocol.minimum_annualization_days)
    gates = {
        'safety_drawdown': score['max_drawdown'] <= config.risk.max_drawdown,
        'verified_contract': config.instrument.verified,
        'verified_costs': config.costs.verified,
        'verified_sessions': config.session.verified,
        'net_positive': score['net_pnl'] > 0,
        'drawdown': score['max_drawdown'] <= protocol.max_drawdown,
        'profit_factor': score['profit_factor'] is not None and score['profit_factor'] > protocol.minimum_profit_factor,
        'trade_count': score['trade_count'] >= protocol.minimum_trades,
        'calmar': score['calmar'] is not None and score['calmar'] > protocol.minimum_calmar,
        'walk_forward_evidence': evidence_kind == 'walk_forward',
        'robustness_evidence': False,
    }
    report = {'schema': 1, 'evidence_kind': evidence_kind, 'result_hash': result['result_hash'],
              'protocol_hash': digest(protocol), 'metrics': score, 'gates': gates,
              'eligible': all(gates.values()),
              'missing_evidence': [key for key, passed in gates.items() if not passed],
              'risk_note': 'planned risk limits cannot guarantee realized loss bounds during gaps'}
    return report | {'scorecard_hash': digest(report)}


def compare(left: dict, right: dict) -> dict:
    return {key: {'baseline': left['metrics'][key], 'challenger': right['metrics'][key]}
            for key in ('net_pnl', 'max_drawdown', 'trade_count', 'profit_factor', 'calmar')}
