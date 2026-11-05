"""Causal, frozen seed rules. Signals indexed by their availability, not bar open."""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from qarevin.data import resample
from qarevin.domain import Contract


class StrategySpec(Contract):
    family: Literal["trend", "mean_reversion", "breakout", "no_trade", "random"]
    fast: int = Field(default=50, ge=2, le=200)
    slow: int = Field(default=200, ge=3, le=500)
    stop_atr: float = Field(default=2, ge=1, le=5)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def ordered(self):
        if self.fast >= self.slow:
            raise ValueError("fast must be less than slow")
        return self


def smooth(values: pd.Series, length: int, *, wilder: bool = False) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    # Each uninterrupted valid run is seeded with an SMA.
    alpha = 1 / length if wilder else 2 / (length + 1)
    buffer = []
    last = None
    for i, value in enumerate(values.to_numpy()):
        if not np.isfinite(value):
            buffer, last = [], None
            continue
        if last is None:
            buffer.append(float(value))
            if len(buffer) < length:
                continue
            last = float(np.mean(buffer))
        else:
            last = alpha * value + (1 - alpha) * last
        result.iloc[i] = last
    return result


def features(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    previous = bars.close.shift(1)
    tr = pd.concat([bars.high - bars.low, (bars.high - previous).abs(), (bars.low - previous).abs()], axis=1).max(axis=1)
    result["atr"] = smooth(tr, 14, wilder=True)
    delta = bars.close.diff()
    gain = smooth(delta.clip(lower=0), 14, wilder=True)
    loss = smooth(-delta.clip(upper=0), 14, wilder=True)
    result["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    result.loc[(loss == 0) & (gain > 0), "rsi"] = 100
    result.loc[(loss == 0) & (gain == 0), "rsi"] = 50
    up, down = bars.high.diff(), -bars.low.diff()
    plus = smooth(up.where((up > down) & (up > 0), 0), 14, wilder=True)
    minus = smooth(down.where((down > up) & (down > 0), 0), 14, wilder=True)
    denominator = plus + minus
    dx = 100 * (plus - minus).abs() / denominator.replace(0, np.nan)
    dx = dx.mask(denominator == 0, 0)
    result["adx"] = smooth(dx, 14, wilder=True)
    result["middle"] = bars.close.rolling(20).mean()
    std = bars.close.rolling(20).std(ddof=0)
    result["lower"], result["upper"] = result.middle - 2 * std, result.middle + 2 * std
    return result


def signals(m1: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    minutes = {"trend": 60, "mean_reversion": 15, "breakout": 30, "no_trade": 60, "random": 60}[spec.family]
    bars = features(resample(m1, minutes))
    side = pd.Series(np.nan, index=bars.index)
    if spec.family == "trend":
        fast, slow = smooth(bars.close, spec.fast), smooth(bars.close, spec.slow)
        side.loc[(fast > slow) & (fast.shift(1) <= slow.shift(1))] = 1
        side.loc[(fast < slow) & (fast.shift(1) >= slow.shift(1))] = -1
    elif spec.family == "mean_reversion":
        previous = bars.shift(1)
        side.loc[(previous.close < previous.lower) & (previous.rsi < 30) & (bars.close >= bars.lower) & (bars.adx <= 25)] = 1
        side.loc[(previous.close > previous.upper) & (previous.rsi > 70) & (bars.close <= bars.upper) & (bars.adx <= 25)] = -1
        # Exit is a closed-bar mean crossing, never a retrospective limit fill.
        side.loc[(bars.close >= bars.middle) & (previous.close < previous.middle)] = 0
        side.loc[(bars.close <= bars.middle) & (previous.close > previous.middle)] = 0
    elif spec.family == "breakout":
        top = bars.high.shift(1).rolling(20).max()
        bottom = bars.low.shift(1).rolling(20).min()
        eligible = bars.atr >= bars.atr.shift(1).rolling(100).median()
        side.loc[(bars.close > top) & eligible] = 1
        side.loc[(bars.close < bottom) & eligible] = -1
    elif spec.family == "random":
        rng = np.random.default_rng(spec.seed)
        side[:] = rng.choice([-1, 0, 1], size=len(bars), p=[0.1, 0.8, 0.1])
    result = pd.DataFrame({"side": side, "stop_distance": bars.atr * spec.stop_atr})
    return result.dropna()
