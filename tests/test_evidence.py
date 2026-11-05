import sqlite3
from pathlib import Path

import pytest

from qarevin.catalog import ResearchCatalog
from qarevin.data import import_csv
from qarevin.evidence import EvidenceStore
from qarevin.experiments import replay_experiment, run_experiment
from qarevin.holdout import HoldoutService
from qarevin.strategies import StrategySpec


def test_append_only_evidence_backup_and_audit(tmp_path):
    store = EvidenceStore(tmp_path/'registry.sqlite')
    identity = store.put('test', {'value':1})
    assert store.get('test', identity) == {'value':1}
    assert store.put('test', {'value':1}) == identity
    with pytest.raises(ValueError, match='conflict'):
        store.put('test', {'value':2}, identity=identity)
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with store.transaction() as db:
            db.execute('DELETE FROM objects')
    store.backup(tmp_path/'backup.sqlite')
    restored = EvidenceStore(tmp_path/'backup.sqlite')
    assert restored.verify_audit() and restored.get('test', identity) == {'value':1}


def test_holdout_consumed_even_when_evaluation_crashes(tmp_path, config):
    store = EvidenceStore(tmp_path/'owner.sqlite')
    service = HoldoutService(store, tmp_path/'sealed', tmp_path/'research')
    strategy = StrategySpec(family='no_trade')
    service.preregister('campaign1', 'a'*64, config, strategy, robustness_stub(store,config,strategy))
    with pytest.raises(FileNotFoundError):
        service.evaluate_once('campaign1', 'a'*64, config, strategy)
    assert store.get('holdout_access', 'campaign1')['status'] == 'consumed'
    with pytest.raises(PermissionError, match='consumed'):
        service.evaluate_once('campaign1', 'a'*64, config, strategy)
    assert store.verify_audit()
    with pytest.raises(ValueError, match='disjoint'):
        HoldoutService(store, tmp_path/'research/sealed', tmp_path/'research')


def test_catalog_no_path_escape_or_boundary_override(tmp_path):
    catalog = ResearchCatalog(tmp_path)
    for name in ('../owner','/tmp/secret','a'*63):
        with pytest.raises(ValueError):
            catalog.directory(name)
    source = Path(__file__).parent/'fixtures/m1.csv'
    manifest = import_csv(source,tmp_path,source_timezone='UTC',provider='test',symbol='gold')
    assert len(catalog.load(manifest['id'])) == 2
    with pytest.raises(PermissionError):
        ResearchCatalog(tmp_path, '2019-01-01T00:00:00Z').load(manifest['id'])


def test_experiment_archives_exact_inputs_and_replays(tmp_path, config):
    source = Path(__file__).parent/'fixtures/m1.csv'
    manifest = import_csv(source,tmp_path/'datasets',source_timezone='UTC',provider='test',symbol='gold')
    dataset = tmp_path/'datasets'/manifest['id']
    store = EvidenceStore(tmp_path/'registry.sqlite')
    record = run_experiment(dataset,config,StrategySpec(family='no_trade'),'No trade conserves starting equity',store,tmp_path/'artifacts')
    assert replay_experiment(Path(record['artifact']),dataset)['reproduced']
    assert len(store.list('experiment')) == 1
    assert store.verify_audit()


def test_source_archive_replays_from_extracted_source(tmp_path, config):
    import json
    import os
    import subprocess
    import sys
    import zipfile
    source = Path(__file__).parent/'fixtures/m1.csv'
    manifest = import_csv(source,tmp_path/'datasets',source_timezone='UTC',provider='test',symbol='gold')
    dataset = tmp_path/'datasets'/manifest['id']
    store = EvidenceStore(tmp_path/'registry.sqlite')
    record = run_experiment(dataset,config,StrategySpec(family='no_trade'),'Replay exact archived source on isolated import path',store,tmp_path/'artifacts')
    saved = json.loads(Path(record['artifact']).read_text())
    archive = tmp_path/'artifacts/source'/saved['manifest']['source']['archive']
    with zipfile.ZipFile(archive) as bundle:
        assert 'requirements.lock' in bundle.namelist()
        bundle.extractall(tmp_path/'restore')
    result = subprocess.run([sys.executable, '-m', 'qarevin.cli',
                             'replay-experiment',record['artifact'],str(dataset)],
                            cwd=tmp_path/'restore', env=os.environ | {'PYTHONPATH':str(tmp_path/'restore/src')},
                            text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)['reproduced']


def test_holdout_renaming_campaign_does_not_reopen_dataset(tmp_path, config):
    store=EvidenceStore(tmp_path/'owner.sqlite')
    service=HoldoutService(store,tmp_path/'sealed',tmp_path/'research')
    strategy=StrategySpec(family='no_trade')
    for name in ('first','renamed'):
        service.preregister(name,'a'*64,config,strategy,robustness_stub(store,config,strategy))
    with pytest.raises(FileNotFoundError):
        service.evaluate_once('first','a'*64,config,strategy)
    with pytest.raises(PermissionError,match='dataset already consumed'):
        service.evaluate_once('renamed','a'*64,config,strategy)


def test_source_archive_corruption_not_reused(tmp_path):
    from qarevin.experiments import snapshot_sources
    import zipfile
    snapshot=snapshot_sources(tmp_path)
    (tmp_path/snapshot['archive']).write_bytes(b'partial zip')
    with pytest.raises((ValueError,zipfile.BadZipFile)):
        snapshot_sources(tmp_path)


def robustness_stub(store, config, strategy):
    # Owner-controlled evidence stub isolates holdout lifecycle fault tests.
    from qarevin.domain import digest, source_identity
    return store.put('robustness_result', {'eligible_for_holdout_request': True,
                     'config_hash': digest(config), 'target': strategy.model_dump(), 'source_hash': source_identity()})


def test_identical_experiment_is_recorded_as_replay(tmp_path, config):
    source=Path(__file__).parent/'fixtures/m1.csv'
    manifest=import_csv(source,tmp_path/'datasets',source_timezone='UTC',provider='test',symbol='gold')
    store=EvidenceStore(tmp_path/'registry.sqlite')
    args=(tmp_path/'datasets'/manifest['id'],config,StrategySpec(family='no_trade'),
          'Identical input replay keeps original result immutable',store,tmp_path/'artifacts')
    first=run_experiment(*args)
    repeated=run_experiment(*args)
    assert first['artifact']==repeated['artifact'] and repeated['replay']['reproduced']
    assert len(store.list('experiment_replay'))==1
    assert len(list((tmp_path/'artifacts/results').glob('*.json')))==1


def test_holdout_alias_raw_and_overlapping_range_are_consumed(tmp_path, config):
    store=EvidenceStore(tmp_path/'owner.sqlite')
    service=HoldoutService(store,tmp_path/'sealed',tmp_path/'research')
    strategy=StrategySpec(family='no_trade')
    source=tmp_path/'future.csv'
    source.write_text('timestamp,open,high,low,close\n2025-01-02T07:00:00,1500,1501,1499,1500\n')
    first=import_csv(source,tmp_path/'sealed',source_timezone='UTC',provider='a',symbol='gold',accessible_before='2100-01-01')
    second=import_csv(source,tmp_path/'sealed',source_timezone='UTC',provider='b',symbol='gold',accessible_before='2099-01-01')
    robust=robustness_stub(store,config,strategy)
    service.preregister('one',first['id'],config,strategy,robust)
    service.preregister('alias',second['id'],config,strategy,robust)
    service.evaluate_once('one',first['id'],config,strategy)
    with pytest.raises(PermissionError,match='raw data already consumed'):
        service.evaluate_once('alias',second['id'],config,strategy)
    source.write_text(source.read_text().replace('1501','1502'))
    overlap=import_csv(source,tmp_path/'sealed',source_timezone='UTC',provider='c',symbol='gold',accessible_before='2100-01-01')
    service.preregister('overlap',overlap['id'],config,strategy,robust)
    with pytest.raises(PermissionError,match='time range already consumed'):
        service.evaluate_once('overlap',overlap['id'],config,strategy)
