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
