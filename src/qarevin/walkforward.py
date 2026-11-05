"""Preregistered non-overlapping outer tests; parameter selection uses validation only."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from pydantic import model_validator

from qarevin.backtest import run_backtest
from qarevin.domain import Contract, ResearchConfig, digest
from qarevin.evaluation import evaluate, metrics
from qarevin.strategies import StrategySpec, signals


class Fold(Contract):
    train_start: str
    validation_start: str
    test_start: str
    test_end: str

    @model_validator(mode='after')
    def ordered(self):
        values = [pd.Timestamp(v) for v in (self.train_start, self.validation_start, self.test_start, self.test_end)]
        if any(v.tz is None for v in values) or not all(a < b for a, b in zip(values, values[1:])):
            raise ValueError('fold requires ordered timezone-aware boundaries')
        return self


def rolling_folds(start: datetime, end: datetime, train_months=24, validation_months=6, test_months=6) -> list[Fold]:
    if min(train_months, validation_months, test_months) < 1:
        raise ValueError('window sizes must be positive')
    cursor, end = pd.Timestamp(start), pd.Timestamp(end)
    if cursor.tz is None or end.tz is None:
        raise ValueError('timezone-aware boundaries required')
    folds = []
    while True:
        validation = cursor + pd.DateOffset(months=train_months)
        test = validation + pd.DateOffset(months=validation_months)
        stop = test + pd.DateOffset(months=test_months)
        if stop > end:
            break
        folds.append(Fold(train_start=cursor.isoformat(), validation_start=validation.isoformat(),
                          test_start=test.isoformat(), test_end=stop.isoformat()))
        cursor += pd.DateOffset(months=test_months)
    return folds


def run_window(bars: pd.DataFrame, config: ResearchConfig, strategy: StrategySpec, start: str, end: str) -> dict:
    start_time, end_time = pd.Timestamp(start), pd.Timestamp(end)
    # Indicators warm up from pre-window history; orders and PnL only exist in the declared window.
    history = bars[bars.index < end_time]
    decision = signals(history, strategy)
    decision = decision[(decision.index >= start_time) & (decision.index < end_time)]
    return run_backtest(bars[(bars.index >= start_time) & (bars.index < end_time)], config, strategy,
                        signal_frame=decision)


def walk_forward(bars: pd.DataFrame, config: ResearchConfig, candidates: list[StrategySpec], folds: list[Fold]) -> dict:
    if not candidates or len(candidates) > 12 or not folds:
        raise ValueError('require 1..12 candidates and at least one fold')
    prior_end = None
    outputs, attempts = [], []
    for fold in folds:
        if prior_end is not None and pd.Timestamp(fold.test_start) < prior_end:
            raise ValueError('outer test windows overlap or are unordered')
        prior_end = pd.Timestamp(fold.test_end)
        choices = []
        for candidate in candidates:
            training = run_window(bars, config, candidate, fold.train_start, fold.validation_start)
            validation = run_window(bars, config, candidate, fold.validation_start, fold.test_start)
            score = metrics(validation)
            attempts.append({'fold': fold.model_dump(), 'strategy': candidate.model_dump(),
                             'train_hash': training['result_hash'], 'validation_hash': validation['result_hash'],
                             'validation_metrics': score})
            choices.append((score['net_pnl'], -score['max_drawdown'], digest(candidate), candidate))
        selected = max(choices, key=lambda row: row[:3])[3]
        result = run_window(bars, config, selected, fold.test_start, fold.test_end)
        outputs.append({'fold': fold.model_dump(), 'selected': selected.model_dump(), 'result': result,
                        'scorecard': evaluate(result, config, evidence_kind='walk_forward')})
    # Independent fold accounts are rebased only for diagnostic stitched equity, not a deployable portfolio.
    scale = 1.0
    stitched, trades = [], []
    for output in outputs:
        result = output['result']
        for sample in result['equity']:
            stitched.append(sample | {key: sample[key] * scale for key in ('equity', 'worst_equity', 'balance')})
        trades.extend(trade | {'net_pnl': trade['net_pnl'] * scale} for trade in result['trades'])
        scale *= result['final_equity'] / result['initial_equity']
    aggregate = {'initial_equity': config.initial_equity, 'final_equity': config.initial_equity * scale,
                 'equity': stitched, 'trades': trades}
    aggregate['result_hash'] = digest(aggregate)
    report = {'folds': outputs, 'attempts': attempts, 'split_hash': digest([f.model_dump() for f in folds]),
              'stitched_metrics': metrics(aggregate),
              'limitations': ['stitched rebased independent accounts; not a continuous-risk deployment replay'],
              'promotion_ready': False}
    return report | {'report_hash': digest(report)}
