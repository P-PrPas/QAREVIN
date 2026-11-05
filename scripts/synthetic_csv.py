"""Create deterministic bid-price M1 synthetic input; not market performance evidence."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--days', type=int, default=30)
args = parser.parse_args()
if not 1 <= args.days <= 365:
    parser.error('days must be 1..365')
index = pd.date_range('2020-01-01', periods=args.days * 1440, freq='min', tz='UTC')
index = index[index.day_of_week < 5]
rng = np.random.default_rng(42)
close = 1500 + np.cumsum(rng.normal(0, .15, len(index)))
frame = pd.DataFrame({'timestamp': index, 'open': close, 'high': close + .3, 'low': close - .3,
                      'close': close, 'tick_volume': 10, 'real_volume': 0})
frame.to_csv(args.output, index=False)
