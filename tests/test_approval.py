from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qarevin.approval import ApprovalVerifier, CandidateReport, CostScenario, ResearchMetrics, DisabledLiveController, issue, public_key_id
from qarevin.evidence import EvidenceStore

NOW=datetime(2026,11,5,12,tzinfo=timezone.utc)


@pytest.fixture
def report():
    # Trusted evidence fixture only: no real forward trading was performed.
    return CandidateReport(strategy_hash='a'*64,risk_policy_hash='b'*64,broker='fixture-broker',
        account_alias='fixture-live',account_server='fixture-server',capital=1000.,notional_cap=2000.,currency='USD',
        human_readable_logic='Deterministic fixture strategy for authorization tests',differences_from_parent='Fixture only',
        data_coverage='Fixture history 2016 through 2026',data_qa_hash='c'*64,split_manifest_hash='d'*64,
        walk_forward_report_hash='e'*64,holdout_report_hash='f'*64,demo_report_hash='1'*64,
        broker_contract_report_hash='2'*64,rollback_runbook_hash='3'*64,search_protocol_hash='4'*64,preregistered_trial_budget=20,
        research_metrics=ResearchMetrics(net_pnl=100.,net_return=.1,max_drawdown=.05,profit_factor=1.4,calmar=1.,sharpe=.8,trade_count=150,calendar_days=730.),
        stressed_costs=tuple(CostScenario(spread_multiplier=value,slippage_multiplier=value,net_return=.05,max_drawdown=.08,trade_count=120) for value in (1.5,2.)),trial_count=20,holdout_open_count=1,
        demo_started_at=NOW-timedelta(days=100),demo_observed_through=NOW,demo_trade_count=100,
        demo_max_drawdown=.02,demo_risk_violations=0,correlated_exposure='Single fixture exposure',
        uncertainty_and_alternatives='Fixture evidence is synthetic and proves authorization code only',
        synthetic=False,verified_data=True,verified_broker=True,passed_walk_forward=True,
        passed_holdout=True,verified_forward_evidence=True)


def test_default_synthetic_and_short_evidence_cannot_issue(report):
    key=Ed25519PrivateKey.generate()
    for patch in ({'synthetic':True},{'verified_broker':False},{'demo_started_at':NOW-timedelta(days=89)},
                  {'demo_risk_violations':1},{'demo_trade_count':99}):
        with pytest.raises(PermissionError):
            issue(report.model_copy(update=patch),key,NOW)


def test_scope_tamper_expiry_wrong_key_and_revoke(tmp_path,report):
    key=Ed25519PrivateKey.generate()
    verifier=fixture_verifier(key,tmp_path/'owner.sqlite')
    token=issue(report,key,NOW)
    claims=verifier.verify(token,report.scope(),NOW)
    for patch in ({'strategy_hash':'0'*64},{'risk_policy_hash':'0'*64},{'capital':2000.},
                  {'account_alias':'another'},{'evidence_hash':'0'*64},{'notional_cap':4000.}):
        with pytest.raises(PermissionError):
            verifier.verify(token,report.scope().model_copy(update=patch),NOW)
    for bad in ('',token[:-1]+'!',token.replace('.', '..')):
        with pytest.raises(PermissionError):
            verifier.verify(bad,report.scope(),NOW)
    with pytest.raises(PermissionError):
        verifier.verify(token,report.scope(),NOW+timedelta(seconds=600))
    with pytest.raises(PermissionError):
        ApprovalVerifier(Ed25519PrivateKey.generate().public_key(),verifier.store,expected_fingerprint=public_key_id(key.public_key())).verify(token,report.scope(),NOW)
    verifier.revoke(claims.authorization_id)
    with pytest.raises(PermissionError):
        verifier.verify(token,report.scope(),NOW)


def test_consume_once_atomic_and_prepare_never_activates(tmp_path,report):
    key=Ed25519PrivateKey.generate()
    verifier=fixture_verifier(key,tmp_path/'owner.sqlite')
    token=issue(report,key,NOW)
    controller=DisabledLiveController(verifier)
    assert not controller.prepare(report,token,NOW)['activation_performed']
    def consume(_):
        try:
            verifier.consume(token,report.scope(),NOW)
            return True
        except PermissionError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(consume,range(2)))==1
    with pytest.raises(PermissionError,match='not implemented'):
        controller.activate(report,token,NOW)
    assert verifier.store.verify_audit()


def test_expiry_rechecked_after_acquiring_consumption_lock(tmp_path,report):
    key=Ed25519PrivateKey.generate()
    verifier=fixture_verifier(key,tmp_path/'owner.sqlite',clock=lambda:NOW+timedelta(seconds=601))
    token=issue(report,key,NOW)
    with pytest.raises(PermissionError,match='acquiring deployment lock'):
        verifier.consume(token,report.scope(),NOW)
    assert verifier.store.list('approval_consumed')==[]


def test_claim_lifetime_and_future_timestamps_are_bounded(tmp_path,report):
    key=Ed25519PrivateKey.generate()
    for lifetime in (0,-1,3601):
        with pytest.raises(ValueError):
            issue(report,key,NOW,ttl_seconds=lifetime)
    verifier=fixture_verifier(key,tmp_path/'owner.sqlite')
    token=issue(report,key,NOW+timedelta(seconds=1))
    with pytest.raises(PermissionError,match='future'):
        verifier.verify(token,report.scope(),NOW)


def test_owner_cli_keygen_and_blocked_packet_never_print_secrets(tmp_path,report):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from qarevin.artifacts import write_artifact
    script=Path(__file__).parents[1]/'scripts/owner_approval.py'
    generated=subprocess.run([sys.executable,str(script),'keygen','--directory',str(tmp_path/'keys'),'--state',str(tmp_path/'owner')],text=True,capture_output=True,check=True)
    assert json.loads(generated.stdout)['private_key_printed'] is False
    private=tmp_path/'keys/owner.private.pem'
    assert private.stat().st_mode & 0o077 == 0
    assert 'PRIVATE KEY' not in generated.stdout
    payload={'candidate_report':report.model_copy(update={'synthetic':True}).model_dump(mode='json')}
    path=write_artifact(tmp_path/'packets',payload)
    blocked=subprocess.run([sys.executable,str(script),'sign','--packet',str(path),'--state',str(tmp_path/'owner'),
                            '--key',str(private),'--token',str(tmp_path/'authorization.token')],text=True,capture_output=True)
    assert blocked.returncode==2
    assert json.loads(blocked.stdout)['activation_performed'] is False
    assert not (tmp_path/'authorization.token').exists()


def fixture_verifier(key,path,clock=lambda:NOW):
    store=EvidenceStore(path)
    fingerprint=public_key_id(key.public_key())
    store.put('approval_trust_root',{'key_id':fingerprint},identity='owner')
    return ApprovalVerifier(key.public_key(),store,expected_fingerprint=fingerprint,clock=clock)


def test_stress_holdout_and_search_budget_gates_cannot_weaken(report):
    key=Ed25519PrivateKey.generate()
    weak=tuple(CostScenario(spread_multiplier=1.,slippage_multiplier=1.,net_return=.1,max_drawdown=.02,trade_count=120) for _ in range(2))
    for patch in ({'stressed_costs':weak},{'holdout_open_count':2},{'trial_count':21}):
        with pytest.raises(PermissionError):
            issue(report.model_copy(update=patch),key,NOW)


def test_public_key_replacement_and_other_signing_domain_rejected(tmp_path,report):
    from qarevin.approval import _encode
    from qarevin.domain import canonical_json
    key=Ed25519PrivateKey.generate()
    verifier=fixture_verifier(key,tmp_path/'owner.sqlite')
    with pytest.raises(PermissionError,match='fingerprint'):
        ApprovalVerifier(Ed25519PrivateKey.generate().public_key(),verifier.store,expected_fingerprint=public_key_id(key.public_key()))
    token=issue(report,key,NOW)
    claims=verifier.verify(token,report.scope(),NOW)
    payload=canonical_json(claims).encode()
    other_domain_token=_encode(payload)+'.'+_encode(key.sign(payload))
    with pytest.raises(PermissionError):
        verifier.verify(other_domain_token,report.scope(),NOW)


def test_owner_cli_sign_preview_uses_pinned_root_and_private_output(tmp_path,report):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from qarevin.artifacts import write_artifact
    script=Path(__file__).parents[1]/'scripts/owner_approval.py'
    current=datetime.now(timezone.utc)
    packet=write_artifact(tmp_path/'packets',{'candidate_report':report.model_copy(update={
        'demo_started_at':current-timedelta(days=100),'demo_observed_through':current}).model_dump(mode='json')})
    base=[sys.executable,str(script)]
    subprocess.run(base+['keygen','--directory',str(tmp_path/'keys'),'--state',str(tmp_path/'owner')],capture_output=True,check=True)
    signed=subprocess.run(base+['sign','--packet',str(packet),'--state',str(tmp_path/'owner'),'--key',str(tmp_path/'keys/owner.private.pem'),
                                '--token',str(tmp_path/'authorization.token')],capture_output=True,text=True,check=True)
    token=(tmp_path/'authorization.token').read_text()
    assert token not in signed.stdout and (tmp_path/'authorization.token').stat().st_mode & 0o077==0
    preview=subprocess.run(base+['preview','--packet',str(packet),'--state',str(tmp_path/'owner'),'--key',str(tmp_path/'keys/owner.public.pem'),
                                 '--token',str(tmp_path/'authorization.token')],capture_output=True,text=True,check=True)
    result=json.loads(preview.stdout)
    assert result['trial_count']==20 and not result['activation_performed']
    assert not result['authorization_consumed']


def test_failed_keygen_leaves_state_recoverable(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script=Path(__file__).parents[1]/'scripts/owner_approval.py'
    readonly=tmp_path/'readonly'
    readonly.mkdir()
    readonly.chmod(0o500)
    state=tmp_path/'owner'
    try:
        failed=subprocess.run([sys.executable,str(script),'keygen','--directory',str(readonly/'keys'),'--state',str(state)],capture_output=True)
        assert failed.returncode==2
    finally:
        readonly.chmod(0o700)
    store=EvidenceStore(state/'approvals.sqlite')
    assert store.list('approval_trust_root')==[]
    retry=subprocess.run([sys.executable,str(script),'keygen','--directory',str(tmp_path/'keys'),'--state',str(state)],capture_output=True)
    assert retry.returncode==0


def test_owner_path_rejects_another_local_directory_owner(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    script=Path(__file__).parents[1]/'scripts/owner_approval.py'
    spec=importlib.util.spec_from_file_location('owner_cli',script)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with monkeypatch.context() as patch:
        patch.setattr(module.os,'geteuid',lambda:999999)
        with pytest.raises(ValueError,match='directory owner'):
            module.owner_path(tmp_path/'keys')
