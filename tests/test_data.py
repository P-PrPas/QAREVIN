from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qarevin.data import import_csv, load_dataset, resample, validate_bars


def make_bars(count=120, start='2020-01-02 07:00:00'):
    index = pd.date_range(start, periods=count, freq='min', tz='UTC')
    close = 1500 + np.sin(np.arange(count) / 15)
    return pd.DataFrame({'open': close, 'high': close + 0.1, 'low': close - 0.1, 'close': close,
                         'tick_volume': 10, 'real_volume': 0}, index=index)


def test_import_chunk_boundaries_immutable_and_tamper(tmp_path):
    source = Path(__file__).parent / 'fixtures/m1.csv'
    manifest = import_csv(source, tmp_path, source_timezone='UTC', provider='synthetic', symbol='XAUUSD', chunksize=1)
    directory = tmp_path / manifest['id']
    assert len(load_dataset(directory)) == 2
    assert import_csv(source, tmp_path, source_timezone='UTC', provider='synthetic', symbol='XAUUSD') == manifest
    (directory / manifest['partitions'][0]['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash'):
        load_dataset(directory)


def test_partial_bars_and_future_values_do_not_leak():
    bars = make_bars(120)
    baseline = resample(bars, 60)
    assert baseline.index[0] == bars.index[0] + pd.Timedelta(hours=1)
    changed = bars.copy()
    changed.iloc[60:, changed.columns.get_loc('high')] = 9000
    assert resample(changed, 60).iloc[0].equals(baseline.iloc[0])
    assert len(resample(bars.drop(bars.index[5]), 60)) == 1


@pytest.mark.parametrize('kind', ['duplicate', 'bad_ohlc', 'negative', 'nonfinite'])
def test_invalid_bars_rejected(kind):
    bars = make_bars(20)
    if kind == 'duplicate':
        bars = pd.concat([bars, bars.iloc[-1:]])
    elif kind == 'bad_ohlc':
        bars.iloc[0, bars.columns.get_loc('high')] = 1
    elif kind == 'negative':
        bars.iloc[0, bars.columns.get_loc('close')] = -1
    else:
        bars.iloc[0, bars.columns.get_loc('close')] = np.nan
    with pytest.raises(ValueError):
        validate_bars(bars)


def test_dst_ambiguity_and_sealed_boundary_rejected(tmp_path):
    source = tmp_path / 'ambiguous.csv'
    source.write_text('timestamp,open,high,low,close\n2020-11-01T01:30:00,1,2,1,2\n')
    with pytest.raises(Exception, match='(?i)ambiguous|infer dst'):
        import_csv(source, tmp_path / 'store', source_timezone='America/New_York', provider='test', symbol='gold')
    source = Path(__file__).parent / 'fixtures/m1.csv'
    with pytest.raises(ValueError, match='boundary'):
        import_csv(source, tmp_path / 'store', source_timezone='UTC', provider='test', symbol='gold', accessible_before='2020-01-01')
