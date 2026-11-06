import zipfile
from pathlib import Path

import pytest

from qarevin.checkpoint import create_checkpoint,restore_checkpoint
from qarevin.data import import_csv
from qarevin.evidence import EvidenceStore
from qarevin.domain import file_digest
from qarevin.experiments import run_experiment,replay_experiment
from qarevin.strategies import StrategySpec


def test_research_checkpoint_restores_artifacts_data_and_replays(tmp_path,config):
    state=tmp_path/'research'
    manifest=import_csv(Path(__file__).parent/'fixtures/m1.csv',state/'datasets',source_timezone='UTC',provider='test',symbol='gold')
    store=EvidenceStore(state/'registry.sqlite')
    experiment=run_experiment(state/'datasets'/manifest['id'],config,StrategySpec(family='no_trade'),
                              'Checkpoint preserves reconstructable no-trade evidence',store,state/'artifacts')
    checkpoint=create_checkpoint(state/'registry.sqlite',state/'artifacts',state/'datasets',tmp_path/'backup.zip')
    restored=restore_checkpoint(tmp_path/'backup.zip',tmp_path/'restored',expected_sha256=checkpoint['sha256'],latest_anchor=checkpoint['audit_anchor'])
    artifact=tmp_path/'restored/artifacts/results'/Path(experiment['artifact']).name
    assert replay_experiment(artifact,tmp_path/'restored/datasets'/manifest['id'])['reproduced']
    assert checkpoint['scope']==restored['scope']=='research_only'
    restored_store=EvidenceStore(tmp_path/'restored/registry.sqlite')
    assert restored_store.verify_audit()
    repeated=run_experiment(tmp_path/'restored/datasets'/manifest['id'],config,StrategySpec(family='no_trade'),
                            'Checkpoint preserves reconstructable no-trade evidence',restored_store,tmp_path/'restored/artifacts')
    assert repeated['replay']['reproduced'] and Path(repeated['artifact']).is_relative_to(tmp_path/'restored')


def test_restore_rejects_traversal_duplicate_members_and_resource_bombs(tmp_path):
    for name,members in [('traversal',[('../outside',b'x')]),('duplicates',[('checkpoint.json',b'{}'),('checkpoint.json',b'{}')])]:
        path=tmp_path/(name+'.zip')
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(path,'w') as archive:
                for member,body in members:
                    archive.writestr(member,body)
        with pytest.raises(ValueError):
            restore_checkpoint(path,tmp_path/(name+'-output'),expected_sha256=file_digest(path),latest_anchor={'sequence':0,'head_hash':'0'*64})
    assert not (tmp_path/'outside').exists()


def test_checkpoint_refuses_approval_and_execution_ledgers(tmp_path):
    for kind in ('approval_trust_root','approval_consumed'):
        root=tmp_path/kind
        store=EvidenceStore(root/'registry.sqlite')
        store.put(kind,{'test':True})
        with pytest.raises(ValueError,match='cannot clone'):
            create_checkpoint(root/'registry.sqlite',root/'artifacts',root/'datasets',tmp_path/(kind+'.zip'))


def test_external_checkpoint_hash_cannot_be_replaced(tmp_path):
    path=tmp_path/'changed.zip'
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='external digest'):
        restore_checkpoint(path,tmp_path/'restored',expected_sha256='0'*64,latest_anchor={'sequence':0,'head_hash':'0'*64})


def test_restore_checks_uncompressed_size_before_extracting(tmp_path):
    path=tmp_path/'large.zip'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('datasets/data',b'x'*1000)
    with pytest.raises(ValueError,match='size limit'):
        restore_checkpoint(path,tmp_path/'restored',expected_sha256=file_digest(path),latest_anchor={'sequence':0,'head_hash':'0'*64},max_bytes=100)
    assert not (tmp_path/'restored').exists()


def test_checkpoint_rejects_rollback_against_latest_known_anchor(tmp_path):
    state=tmp_path/'research'
    store=EvidenceStore(state/'registry.sqlite')
    store.put('test',{'value':1})
    backup=create_checkpoint(state/'registry.sqlite',state/'artifacts',state/'datasets',tmp_path/'old.zip')
    store.put('trial',{'new_attempt':True})
    with pytest.raises(ValueError,match='older than last known'):
        restore_checkpoint(tmp_path/'old.zip',tmp_path/'restored',expected_sha256=backup['sha256'],latest_anchor=store.audit_anchor())
    assert not (tmp_path/'restored').exists()


def test_checkpoint_checks_known_prefix_and_does_not_migrate_source(tmp_path):
    state=tmp_path/'research'
    store=EvidenceStore(state/'registry.sqlite')
    store.put('trial',{'attempt':1})
    prefix=store.audit_anchor()
    store.put('trial',{'attempt':2})
    with store.read() as db:
        before=[tuple(row) for row in db.execute('SELECT * FROM schema_migrations')]
    backup=create_checkpoint(store.path,state/'artifacts',state/'datasets',tmp_path/'backup.zip')
    with store.read() as db:
        assert before==[tuple(row) for row in db.execute('SELECT * FROM schema_migrations')]
    assert store.audit_anchor()==backup['audit_anchor']
    readonly=EvidenceStore.open_readonly(store.path)
    with pytest.raises(PermissionError):
        readonly.put('trial',{'attempt':3})
    restore_checkpoint(tmp_path/'backup.zip',tmp_path/'good',expected_sha256=backup['sha256'],latest_anchor=prefix)
    with pytest.raises(ValueError,match='anchor mismatch'):
        restore_checkpoint(tmp_path/'backup.zip',tmp_path/'bad',expected_sha256=backup['sha256'],latest_anchor=prefix|{'head_hash':'f'*64})
    assert not (tmp_path/'bad').exists()


def test_checkpoint_never_clones_sealed_holdout_consumption_and_bounds_create(tmp_path):
    state=tmp_path/'research'
    store=EvidenceStore(state/'registry.sqlite')
    with pytest.raises(ValueError,match='size limit'):
        create_checkpoint(state/'registry.sqlite',state/'artifacts',state/'datasets',tmp_path/'small.zip',max_bytes=100)
    store.put('holdout_raw_access',{'consumed':True})
    with pytest.raises(ValueError,match='holdout'):
        create_checkpoint(state/'registry.sqlite',state/'artifacts',state/'datasets',tmp_path/'sealed.zip')
