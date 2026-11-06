from datetime import datetime, timezone

import pytest

from qarevin.backtest import run_backtest
from qarevin.domain import digest
from qarevin.evaluation import evaluate, metrics
from qarevin.strategies import StrategySpec
from qarevin.walkforward import Fold, rolling_folds, walk_forward
from test_data import make_bars


def test_no_trade_metrics_null_and_all_gate_failures_explicit(config):
    result = run_backtest(make_bars(120), config, StrategySpec(family='no_trade'))
    report = evaluate(result, config)
    assert report['metrics']['profit_factor'] is None
    assert report['metrics']['calmar'] is None
    assert not report['eligible'] and 'verified_costs' in report['missing_evidence']
    result['final_equity'] += 100
    with pytest.raises(ValueError, match='hash'):
        metrics(result)


def test_metrics_equity_drawdown_and_trade_accounting():
    result = {'initial_equity':100., 'final_equity':80., 'trades':[{'net_pnl':-20.}],
              'equity':[{'time':'2020-01-01T12:00:00Z','equity':90.,'worst_equity':85.},
                        {'time':'2020-01-02T12:00:00Z','equity':80.,'worst_equity':80.}]}
    result['result_hash'] = digest(result)
    score = metrics(result)
    assert score['max_drawdown'] == pytest.approx(.2)
    assert score['net_pnl'] == -20
    assert score['profit_factor'] == 0
    result['trades'][0]['net_pnl'] = 1
    result['result_hash'] = digest({k:v for k,v in result.items() if k!='result_hash'})
    with pytest.raises(ValueError, match='reconciliation'):
        metrics(result)


def test_walkforward_selection_does_not_see_future(config):
    bars = make_bars(4 * 1440, '2020-01-06 00:00:00')
    fold = Fold(train_start='2020-01-06T00:00:00Z',validation_start='2020-01-07T00:00:00Z',
                test_start='2020-01-08T00:00:00Z',test_end='2020-01-09T00:00:00Z')
    candidates = [StrategySpec(family='no_trade'), StrategySpec(family='random', seed=5)]
    baseline = walk_forward(bars, config, candidates, [fold])
    changed = bars.copy()
    changed.loc[changed.index >= fold.test_start, ['open','high','low','close']] += 50
    shifted = walk_forward(changed, config, candidates, [fold])
    assert baseline['folds'][0]['selected'] == shifted['folds'][0]['selected']
    assert baseline['attempts'] == shifted['attempts']
    with pytest.raises(ValueError, match='overlap'):
        walk_forward(bars, config, candidates, [fold, fold])


def test_rolling_folds_nonoverlap():
    folds = rolling_folds(datetime(2016,1,1,tzinfo=timezone.utc), datetime(2023,1,1,tzinfo=timezone.utc))
    assert len(folds) == 9
    assert all(a.test_end == b.test_start for a,b in zip(folds,folds[1:]))


def test_robustness_cannot_accept_unconfigured_or_duplicate_neighborhood(config):
    from qarevin.robustness import campaign
    strategy = StrategySpec(family='trend')
    with pytest.raises(ValueError,match='distinct'):
        campaign(make_bars(120), config, strategy, [strategy,strategy], [])


def test_profitable_fold_then_drawdown_rebases_peak(monkeypatch, config):
    import qarevin.walkforward as wf
    def simulated(bars, config, strategy, start, end):
        test_first = start == '2020-01-08T00:00:00Z'
        test_second = start == '2020-01-09T00:00:00Z'
        final = 1200. if test_first else 1083. if test_second else 1000.
        values = [1200., final] if test_second else [1000., final]
        index = pd.date_range(start, periods=2, freq='h')
        result = {'initial_equity':1000., 'final_equity':final, 'config_hash':digest(config),
                  'trades':[{'net_pnl':final-1000.}],
                  'equity':[{'time':t.isoformat(),'equity':value,'worst_equity':value,'balance':value,
                             'peak_equity':1200. if test_second else max(1000.,value)} for t,value in zip(index,values)]}
        result['result_hash']=digest(result)
        return result
    import pandas as pd
    monkeypatch.setattr(wf,'run_window',simulated)
    folds=[Fold(train_start='2020-01-06T00:00:00Z',validation_start='2020-01-07T00:00:00Z',
                test_start='2020-01-08T00:00:00Z',test_end='2020-01-09T00:00:00Z'),
           Fold(train_start='2020-01-07T00:00:00Z',validation_start='2020-01-08T00:00:00Z',
                test_start='2020-01-09T00:00:00Z',test_end='2020-01-10T00:00:00Z')]
    report=wf.walk_forward(make_bars(5*1440,'2020-01-06'),config,[StrategySpec(family='no_trade')],folds)
    assert report['stitched_metrics']['max_drawdown']==pytest.approx(1-1083/1200)


def test_walkforward_registers_each_trial_before_result(tmp_path, config):
    from qarevin.evidence import EvidenceStore
    store=EvidenceStore(tmp_path/'registry.sqlite')
    bars=make_bars(4*1440,'2020-01-06')
    fold=Fold(train_start='2020-01-06T00:00:00Z',validation_start='2020-01-07T00:00:00Z',
              test_start='2020-01-08T00:00:00Z',test_end='2020-01-09T00:00:00Z')
    for _ in range(2):
        result=walk_forward(bars,config,[StrategySpec(family='no_trade')],[fold],store=store)
        assert result['ledger_registered']
    assert len(store.list('trial'))==2
    assert len(store.list('walk_forward_protocol'))==1
    assert len(store.list('walk_forward_run'))==2
    assert store.verify_audit()
