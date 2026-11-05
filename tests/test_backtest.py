import pandas as pd
import pytest

from qarevin.backtest import run_backtest, size_lots
from qarevin.domain import digest
from qarevin.strategies import StrategySpec, signals, smooth
from test_data import make_bars


def test_wilder_hand_computed():
    values = pd.Series([1., 2., 3., 6.])
    assert smooth(values, 3, wilder=True).iloc[2] == 2
    assert smooth(values, 3, wilder=True).iloc[3] == pytest.approx(10 / 3)


def test_no_trade_and_reproducibility(config):
    bars = make_bars(360)
    result = run_backtest(bars, config, StrategySpec(family='no_trade'))
    assert result['trades'] == [] and result['final_equity'] == 1000
    assert digest(result) == digest(run_backtest(bars, config, StrategySpec(family='no_trade')))


def test_closed_bar_causality_all_seeds():
    bars = make_bars(60 * 250)
    changed = bars.copy()
    changed.iloc[-600:, changed.columns.get_loc('close')] += 0.01
    for family in ('trend', 'mean_reversion', 'breakout', 'random'):
        a = signals(bars, StrategySpec(family=family))
        b = signals(changed, StrategySpec(family=family))
        cutoff = changed.index[-600]
        pd.testing.assert_frame_equal(a[a.index <= cutoff], b[b.index <= cutoff])


@pytest.mark.parametrize('direction', [1, -1])
def test_stop_fill_fees_and_next_available_quote(config, direction):
    bars = make_bars(3)
    bars[['open', 'close']] = 1500.
    bars['high'], bars['low'] = 1500.1, 1499.9
    bars.loc[bars.index[1], 'high'] = 1502.
    bars.loc[bars.index[1], 'low'] = 1498.
    decision = pd.DataFrame({'side': [direction], 'stop_distance': [1.]}, index=bars.index[1:2])
    result = run_backtest(bars, config, StrategySpec(family='no_trade'), signal_frame=decision)
    trade = result['trades'][0]
    assert trade['opened'] == bars.index[1].isoformat()
    assert trade['reason'] == 'stop'
    expected = (trade['exit'] - trade['entry']) * direction * trade['lots'] * 100 - trade['fees']
    assert trade['net_pnl'] == pytest.approx(expected)
    assert result['final_equity'] == pytest.approx(1000 + expected)
    assert trade['net_pnl'] < 0


def test_min_lot_skip_and_gap_stop(config):
    assert size_lots(1, 10, config) == 0
    bars = make_bars(3)
    bars[['open', 'close']] = 1500.
    bars['high'], bars['low'] = 1500.1, 1499.9
    bars.loc[bars.index[-1], ['open', 'close', 'high', 'low']] = [1490, 1490, 1490.1, 1489.9]
    decision = pd.DataFrame({'side': [1], 'stop_distance': [1.]}, index=bars.index[:1])
    result = run_backtest(bars, config, StrategySpec(family='no_trade'), signal_frame=decision)
    assert result['trades'][0]['reason'] == 'gap_stop'
    assert result['trades'][0]['exit'] < 1491
