"""Bounded fixed-artifact OOS/cost/neighborhood campaign, never a user-supplied pass flag."""
from __future__ import annotations

import math

from pydantic import Field

from qarevin.domain import Contract, ResearchConfig, digest
from qarevin.evaluation import EvaluationProtocol
from qarevin.strategies import StrategySpec
from qarevin.walkforward import Fold, walk_forward


class RobustnessProtocol(Contract):
    minimum_folds: int = Field(default=3, ge=3)
    minimum_profitable_fraction: float = Field(default=0.6, ge=0.5, le=1)
    maximum_profit_concentration: float = Field(default=0.7, gt=0, le=0.8)
    maximum_drawdown: float = Field(default=0.15, gt=0, le=0.15)


def campaign(bars, config: ResearchConfig, target: StrategySpec, neighbors: list[StrategySpec],
             folds: list[Fold], protocol: RobustnessProtocol = RobustnessProtocol(), *, store=None) -> dict:
    identities = {digest(item) for item in neighbors}
    if len(neighbors) != 2 or len(identities | {digest(target)}) != 3:
        raise ValueError('exactly two distinct preregistered neighbors required')
    if any(item.family != target.family for item in neighbors):
        raise ValueError('parameter neighbors must belong to the same strategy family')
    if store:
        from qarevin.domain import source_identity
        store.put('robustness_preregistration', {'target': target.model_dump(), 'neighbors': [n.model_dump() for n in neighbors],
                  'folds': [f.model_dump() for f in folds], 'protocol': protocol.model_dump(),
                  'source_hash': source_identity(), 'config_hash': digest(config)})
    baseline = walk_forward(bars, config, [target], folds, store=store)
    if baseline.get('status') == 'insufficient_evidence':
        return baseline
    stresses = []
    for multiplier in (1.5, 2.0):
        costs = config.costs.model_copy(update={'spread_multiplier': config.costs.spread_multiplier * multiplier,
                                               'slippage_points': config.costs.slippage_points * multiplier})
        stresses.append(walk_forward(bars, config.model_copy(update={'costs': costs}), [target], folds, store=store))
    neighborhoods = [walk_forward(bars, config, [neighbor], folds, store=store) for neighbor in neighbors]
    fold_pnl = [item['scorecard']['metrics']['net_pnl'] for item in baseline['folds']]
    positive = sum(max(0, value) for value in fold_pnl)
    concentration = max([max(0, value) for value in fold_pnl], default=0) / positive if positive else 1
    score = baseline['stitched_metrics']
    gates = {
        'ledger_registered': store is not None,
        'stress_sample': all(item['stitched_metrics']['trade_count'] >= max(100, .8 * score['trade_count']) for item in stresses),
        'minimum_folds': len(folds) >= protocol.minimum_folds,
        'profitable_fraction': sum(value > 0 for value in fold_pnl) / len(fold_pnl) >= protocol.minimum_profitable_fraction,
        'profit_concentration': concentration <= protocol.maximum_profit_concentration,
        'stress_positive': all(item['stitched_metrics']['net_pnl'] > 0 for item in stresses),
        'stress_drawdown': all(item['stitched_metrics']['max_drawdown'] <= protocol.maximum_drawdown for item in stresses),
        'neighbors_positive': all(item['stitched_metrics']['net_pnl'] > 0 for item in neighborhoods),
        'neighbors_drawdown': all(item['stitched_metrics']['max_drawdown'] <= protocol.maximum_drawdown for item in neighborhoods),
        'verified_metadata': all((config.instrument.verified, config.costs.verified, config.session.verified)),
        'net_positive': score['net_pnl'] > 0,
        'trade_count': score['trade_count'] >= 100,
        'drawdown': score['max_drawdown'] <= min(.15, config.risk.max_drawdown),
        'profit_factor': score['profit_factor'] is not None and score['profit_factor'] > 1.2,
        'calmar': score['calmar'] is not None and math.isfinite(score['calmar']) and score['calmar'] > .5,
    }
    report = {'target': target.model_dump(), 'config_hash': digest(config), 'split_hash': baseline['split_hash'],
              'evaluation_protocol_hash': digest(EvaluationProtocol()), 'robustness_protocol_hash': digest(protocol),
              'walk_forward': baseline, 'stresses': stresses, 'neighbors': neighborhoods,
              'gates': gates, 'eligible_for_holdout_request': all(gates.values()),
              'promotion_ready': False, 'reason': 'holdout and future demo evidence remain separate',
              'trial_count': sum(len(item['attempts']) for item in [baseline, *stresses, *neighborhoods])}
    if store:
        store.put('robustness_result', report)
    return report | {'campaign_hash': digest(report)}
