"""Bounded subprocess entry. Input contains parameters, never executable source/import paths."""
import json
import resource
import sys
from pathlib import Path


def main():
    scratch = Path(sys.argv[1])
    memory, timeout = int(sys.argv[2]), int(sys.argv[3])
    resource.setrlimit(resource.RLIMIT_AS, (memory * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from qarevin.backtest import run_backtest
    from qarevin.data import load_dataset
    from qarevin.domain import ResearchConfig, canonical_json
    from qarevin.strategies import StrategySpec
    from qarevin.walkforward import Fold, walk_forward
    body = json.loads((scratch / 'request.json').read_text())
    config, strategy = ResearchConfig.model_validate(body['config']), StrategySpec.model_validate(body['strategy'])
    bars = load_dataset(Path(body['dataset']))
    if len(bars) > 250_000:
        raise ValueError('dataset exceeds bounded-worker row cap')
    if body['kind'] == 'backtest':
        result = {'result': run_backtest(bars, config, strategy)}
    elif body['kind'] == 'walk_forward':
        result = {'walk_forward': walk_forward(bars, config, [strategy], [Fold.model_validate(f) for f in body['folds']])}
    else:
        raise ValueError('unsupported job kind')
    (scratch / 'result.json').write_text(canonical_json(result))


if __name__ == '__main__':
    main()
