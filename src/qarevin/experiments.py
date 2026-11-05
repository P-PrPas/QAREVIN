"""Owner research execution with archived source/config and independently sealed evidence."""
from __future__ import annotations

import importlib.metadata
import subprocess
import zipfile
from pathlib import Path

from qarevin.artifacts import read_artifact, write_artifact
from qarevin.backtest import run_backtest
from qarevin.data import load_dataset, read_manifest
from qarevin.domain import ResearchConfig, canonical_json, digest, file_digest, source_identity
from qarevin.evaluation import evaluate
from qarevin.evidence import EvidenceStore
from qarevin.strategies import StrategySpec


def snapshot_sources(store: Path) -> dict:
    package = Path(__file__).parent
    files = {'src/' + str(path.relative_to(package.parent)): path.read_bytes() for path in sorted(package.rglob('*.py'))}
    project = package.parents[1]
    for name in ('requirements.lock', 'pyproject.toml'):
        if (project / name).is_file():
            files[name] = (project / name).read_bytes()
    identity = digest({name: __import__('hashlib').sha256(body).hexdigest() for name, body in files.items()})
    store.mkdir(parents=True, exist_ok=True)
    target = store / (identity + '.zip')
    if not target.exists():
        with target.open('xb') as stream:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, body)
    return {'source_hash': source_identity(), 'archive': target.name, 'archive_sha256': file_digest(target)}


def run_experiment(dataset: Path, config: ResearchConfig, strategy: StrategySpec,
                   hypothesis: str, store: EvidenceStore, artifacts: Path, parent_id: str | None = None) -> dict:
    if not 10 <= len(hypothesis) <= 4000:
        raise ValueError('hypothesis length must be 10..4000')
    if parent_id:
        store.get('strategy', parent_id)
    source = snapshot_sources(artifacts / 'source')
    strategy_id = store.put('strategy', {'spec': strategy.model_dump(mode='json'), 'parent_id': parent_id,
                                         'source_hash': source['source_hash']})
    dataset_manifest = read_manifest(dataset)
    store.put('dataset', dataset_manifest, identity=dataset_manifest['id'])
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent,
                                text=True, capture_output=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    environment = {item.metadata['Name']: item.version for item in importlib.metadata.distributions()}
    manifest = {'strategy_id': strategy_id, 'dataset_id': dataset_manifest['id'],
                'config': config.model_dump(mode='json'), 'hypothesis': hypothesis, 'source': source,
                'git_commit': commit, 'environment': environment, 'seed': strategy.seed}
    experiment_id = store.put('experiment', manifest)
    store.audit('experiment_started', {'experiment_id': experiment_id})
    try:
        result = run_backtest(load_dataset(dataset), config, strategy)
        scorecard = evaluate(result, config)
        payload = {'manifest': manifest, 'result': result, 'scorecard': scorecard}
        path = write_artifact(artifacts / 'results', payload)
        store.put('experiment_result', {'artifact': str(path), 'artifact_sha256': path.stem,
                                        'scorecard': scorecard}, identity=experiment_id)
        store.audit('experiment_succeeded', {'experiment_id': experiment_id, 'artifact_sha256': path.stem})
        return {'experiment_id': experiment_id, 'artifact': str(path), 'scorecard': scorecard}
    except Exception as exc:
        store.audit('experiment_failed', {'experiment_id': experiment_id, 'error_type': type(exc).__name__})
        raise


def replay_experiment(artifact: Path, dataset: Path) -> dict:
    saved = read_artifact(artifact)
    manifest = saved['manifest']
    source = manifest['source']
    archive = artifact.parent.parent / 'source' / source['archive']
    if file_digest(archive) != source['archive_sha256'] or source_identity() != source['source_hash']:
        raise ValueError('source identity mismatch; restore archived source/environment first')
    if read_manifest(dataset)['id'] != manifest['dataset_id']:
        raise ValueError('dataset identity mismatch')
    config = ResearchConfig.model_validate(manifest['config'])
    # The strategy is recorded in the deterministic result as well as the registry.
    strategy = StrategySpec.model_validate(saved['result']['strategy'])
    result = run_backtest(load_dataset(dataset), config, strategy)
    if canonical_json(result) != canonical_json(saved['result']):
        raise ValueError('reproduction mismatch')
    return {'reproduced': True, 'result_hash': result['result_hash']}
