from datetime import datetime, timedelta, timezone
from threading import Event
from concurrent.futures import ThreadPoolExecutor

from qarevin.evidence import EvidenceStore
from qarevin.operations import Alert, AlertOutbox, ForwardObserver
from test_execution import create

NOW=datetime(2026,11,5,12,tzinfo=timezone.utc)


def test_alert_retries_delivery_is_not_ack_and_condition_recurrence(tmp_path):
    store=EvidenceStore(tmp_path/'ops.sqlite')
    outbox=AlertOutbox(store)
    alert=Alert(kind='execution_halt',message='Execution halted; owner must inspect',critical=True)
    identifier=outbox.condition('risk',True,alert,NOW)
    assert outbox.condition('risk',True,alert,NOW)==identifier
    def failed(*args):
        raise TimeoutError('sensitive provider token must not be logged')
    assert outbox.dispatch_one(failed,NOW)['status']=='pending'
    assert outbox.dispatch_one(lambda *args:'sent',NOW+timedelta(seconds=59)) is None
    result=outbox.dispatch_one(lambda *args:'provider-id',NOW+timedelta(seconds=60))
    assert result['status']=='sent' and not result['acknowledged']
    assert len(outbox.pending())==1
    outbox.acknowledge(identifier,'owner')
    assert outbox.pending()==[]
    outbox.condition('risk',False,alert,NOW)
    assert outbox.condition('risk',True,alert,NOW)!=identifier
    with store.read() as db:
        assert not any('sensitive' in row[0] for row in db.execute('SELECT payload FROM audit_ledger'))
    assert store.verify_audit()


def test_delivered_normal_alerts_do_not_exhaust_critical_capacity(tmp_path):
    from qarevin.domain import canonical_json
    store=EvidenceStore(tmp_path/'ops.sqlite')
    outbox=AlertOutbox(store)
    normal=Alert(kind='spread_wide',message='Spread exceeds entry limit')
    first=outbox.condition('spread',True,normal,NOW)
    outbox.dispatch_one(lambda *args:'provider-id',NOW)
    outbox.condition('spread',False,normal,NOW)
    assert outbox.condition('spread',True,normal,NOW+timedelta(minutes=1))==first
    with store.transaction() as db:
        db.executemany('INSERT INTO alerts(id,body,state,next_attempt) VALUES(?,?,?,?)',
                       [(str(i),canonical_json(normal),'sent',1e30) for i in range(1000)])
    critical=outbox.enqueue('critical',Alert(kind='execution_halt',message='Execution halted; inspect',critical=True),NOW)
    assert [row['id'] for row in outbox.pending()]==[critical]
    assert outbox.dispatch_one(lambda *args:'critical-delivered',NOW)['id']==critical


def test_late_delivery_and_repeat_ack_preserve_audit_meaning(tmp_path):
    store=EvidenceStore(tmp_path/'ops.sqlite')
    outbox=AlertOutbox(store)
    identifier=outbox.enqueue('one',Alert(kind='owner_review',message='Owner review requested',critical=True),NOW)
    def sender(*args):
        outbox.acknowledge(identifier,'owner')
        return 'provider-id'
    assert outbox.dispatch_one(sender,NOW)['acknowledged']
    before=store.audit_anchor()
    outbox.acknowledge(identifier,'owner')
    assert store.audit_anchor()==before
    with store.read() as db:
        events=[row[0] for row in db.execute('SELECT event FROM audit_ledger')]
    assert 'alert_send_late' in events and 'alert_sent' not in events


def test_alert_failure_does_not_skip_forward_snapshot(tmp_path,config,monkeypatch):
    ready=config.model_copy(update={name:getattr(config,name).model_copy(update={'verified':True}) for name in ('instrument','costs','session')})
    runner,_=create(tmp_path,ready)
    with runner:
        runner.start_demo(NOW)
        outbox=AlertOutbox(runner.store)
        def fail(*args):
            raise RuntimeError('queue unavailable')
        monkeypatch.setattr(outbox,'condition',fail)
        result=ForwardObserver(runner,outbox).tick(NOW)
        assert result['snapshot'] and result['alert_errors']
        assert runner.store.get('forward_snapshot',result['snapshot'])
        assert any('integrity_failure' in item['body'] for item in outbox.pending())
        first=outbox.pending()[0]['id']
        outbox.acknowledge(first,'owner')
        observer=ForwardObserver(runner,outbox)
        assert observer.tick(NOW+timedelta(minutes=1))['alert_errors']
        assert any(row['id']!=first and 'integrity_failure' in row['body'] for row in outbox.pending())


def test_ack_during_delivery_is_not_overwritten(tmp_path):
    outbox=AlertOutbox(EvidenceStore(tmp_path/'ops.sqlite'))
    identifier=outbox.enqueue('one',Alert(kind='owner_review',message='Owner review requested',critical=True),NOW)
    entered,release=Event(),Event()
    def sender(*args):
        entered.set()
        assert release.wait(5)
        return 'provider-id'
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(outbox.dispatch_one,sender,NOW)
        assert entered.wait(5)
        assert outbox.dispatch_one(lambda *args:'duplicate',NOW) is None
        outbox.acknowledge(identifier,'owner')
        release.set()
        assert future.result()['acknowledged']
    assert outbox.pending()==[]


def test_forward_snapshots_are_sampled_diagnostics_not_trade_evidence(tmp_path,config):
    ready=config.model_copy(update={name:getattr(config,name).model_copy(update={'verified':True}) for name in ('instrument','costs','session')})
    runner,broker=create(tmp_path,ready)
    with runner:
        runner.start_demo(NOW)
        observer=ForwardObserver(runner,AlertOutbox(runner.store))
        first=observer.tick(NOW)
        assert observer.tick(NOW+timedelta(seconds=1))['snapshot']==first['snapshot']
        broker.account=broker.account.model_copy(update={'equity':1100.,'balance':1100.,'cumulative_cash_flow':100.})
        broker.quote=broker.quote.model_copy(update={'timestamp':NOW+timedelta(minutes=1)})
        observer.tick(NOW+timedelta(minutes=1))
        report=observer.report()
        assert report['snapshots']==2 and report['equity_change_after_cash_flows']==0
        assert report['synthetic'] and not report['eligible_for_live']
        assert report['closed_trade_count'] is None
