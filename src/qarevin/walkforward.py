"""Preregistered non-overlapping outer tests; parameter selection uses validation only."""
from __future__ import annotations

from datetime import datetime
import uuid
import hashlib

import pandas as pd
from pydantic import model_validator

from qarevin.backtest import run_backtest
from qarevin.domain import Contract, ResearchConfig, digest, source_identity, utc_now
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


def walk_forward(bars: pd.DataFrame, config: ResearchConfig, candidates: list[StrategySpec], folds: list[Fold], *, store=None) -> dict:
    if not candidates or len(candidates) > 12 or not folds:
        raise ValueError('require 1..12 candidates and at least one fold')
    if bars.empty:
        return {'status': 'insufficient_evidence', 'reason': 'empty data', 'promotion_ready': False}
    if bars.index.max() >= pd.Timestamp(config.research_access_before):
        raise PermissionError('walk-forward cannot access sealed tail')
    for fold in folds:
        windows = ((fold.train_start, fold.validation_start), (fold.validation_start, fold.test_start), (fold.test_start, fold.test_end))
        if any(not ((bars.index >= pd.Timestamp(a)) & (bars.index < pd.Timestamp(b))).any() for a, b in windows):
            return {'status': 'insufficient_evidence', 'reason': 'empty fold segment', 'promotion_ready': False}
        if pd.Timestamp(fold.train_start) < bars.index.min() or pd.Timestamp(fold.test_end) > bars.index.max() + pd.Timedelta(minutes=1):
            return {'status': 'insufficient_evidence', 'reason': 'fold outside dataset coverage', 'promotion_ready': False}
    bars_hash = hashlib.sha256(pd.util.hash_pandas_object(bars, index=True).values.tobytes()).hexdigest()
    run_id = uuid.uuid4().hex
    if store:
        protocol_id = store.put('walk_forward_protocol', {'folds': [fold.model_dump() for fold in folds],
                                'candidates': [item.model_dump() for item in candidates],
                                'config_hash': digest(config), 'source_hash': source_identity(),
                                'bars_hash': bars_hash})
        store.put('walk_forward_run', {'protocol_id': protocol_id, 'started_at': utc_now()}, identity=run_id)
    prior_end = None
    outputs, attempts = [], []
    for fold in folds:
        if prior_end is not None and pd.Timestamp(fold.test_start) < prior_end:
            raise ValueError('outer test windows overlap or are unordered')
        prior_end = pd.Timestamp(fold.test_end)
        choices = []
        for candidate in candidates:
            trial_id = digest({'run_id': run_id, 'fold': fold.model_dump(), 'candidate': candidate.model_dump()})
            if store:
                store.put('trial', {'run_id': run_id, 'fold': fold.model_dump(), 'candidate': candidate.model_dump()}, identity=trial_id)
                store.audit('trial_started', {'trial_id': trial_id})
            try:
                training = run_window(bars, config, candidate, fold.train_start, fold.validation_start)
                validation = run_window(bars, config, candidate, fold.validation_start, fold.test_start)
                score = metrics(validation)
            except Exception as exc:
                if store:
                    store.audit('trial_failed', {'trial_id': trial_id, 'error_type': type(exc).__name__})
                    store.put('walk_forward_outcome', {'status': 'failed', 'error_type': type(exc).__name__}, identity=run_id)
                raise
            attempts.append({'fold': fold.model_dump(), 'strategy': candidate.model_dump(),
                             'train_hash': training['result_hash'], 'validation_hash': validation['result_hash'],
                             'validation_metrics': score, 'training_use': 'diagnostic_only'})
            if store:
                store.put('trial_result', attempts[-1], identity=trial_id)
                store.audit('trial_succeeded', {'trial_id': trial_id})
            choices.append((score['net_pnl'], -score['max_drawdown'], digest(candidate), candidate))
        selected = max(choices, key=lambda row: row[:3])[3]
        try:
            result = run_window(bars, config, selected, fold.test_start, fold.test_end)
            scorecard = evaluate(result, config, evidence_kind='walk_forward')
        except Exception as exc:
            if store:
                store.audit('outer_test_failed', {'run_id': run_id, 'error_type': type(exc).__name__})
                store.put('walk_forward_outcome', {'status': 'failed', 'error_type': type(exc).__name__}, identity=run_id)
            raise
        outputs.append({'fold': fold.model_dump(), 'selected': selected.model_dump(), 'result': result,
                        'scorecard': scorecard})
    # Independent fold accounts are rebased only for diagnostic stitched equity, not a deployable portfolio.
    scale = 1.0
    stitched, trades = [], []
    for output in outputs:
        result = output['result']
        for sample in result['equity']:
            stitched.append(sample | {key: sample[key] * scale for key in ('equity', 'worst_equity', 'balance', 'peak_equity')})
        trades.extend(trade | {'net_pnl': trade['net_pnl'] * scale} for trade in result['trades'])
        scale *= result['final_equity'] / result['initial_equity']
    aggregate = {'initial_equity': config.initial_equity, 'final_equity': config.initial_equity * scale,
                 'equity': stitched, 'trades': trades}
    aggregate['result_hash'] = digest(aggregate)
    report = {'bars_hash': bars_hash, 'folds': outputs, 'attempts': attempts, 'split_hash': digest([f.model_dump() for f in folds]),
              'stitched_metrics': metrics(aggregate),
              'limitations': ['stitched rebased independent accounts; not a continuous-risk deployment replay'],
              'promotion_ready': False, 'ledger_registered': store is not None}
    if store:
        store.put('walk_forward_result', report, identity=run_id)
        store.put('walk_forward_outcome', {'status': 'completed'}, identity=run_id)
    return report | {'report_hash': digest(report)}
