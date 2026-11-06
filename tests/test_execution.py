from datetime import datetime, timedelta, timezone

import pytest

from qarevin.broker import FakeBroker, Position, Signal
from qarevin.domain import digest
from qarevin.execution import DemoRunner, SafetyStop

NOW=datetime(2026,11,5,12,tzinfo=timezone.utc)


@pytest.fixture
def ready_config(config):
    return config.model_copy(update={name:getattr(config,name).model_copy(update={'verified':True}) for name in ('instrument','costs','session')})


def create(tmp_path,config,broker=None):
    broker=broker or FakeBroker(config.instrument,now=NOW)
    runner=DemoRunner(tmp_path/'demo.sqlite',broker,config,strategy_hash='a'*64,account_alias='synthetic-demo',server='fake')
    return runner,broker


def signal(number=1):
    return Signal(signal_id=digest({'signal':number}),side=1,stop_distance=1.)


def test_activation_demo_only_and_no_unverified_config(tmp_path,config,ready_config):
    with pytest.raises(ValueError,match='unverified'):
        create(tmp_path,config)
    runner,broker=create(tmp_path,ready_config)
    with runner:
        with pytest.raises(SafetyStop,match='not active'):
            runner.submit(signal(),NOW)
        broker.account=broker.account.model_copy(update={'environment':'live'})
        with pytest.raises(SafetyStop):
            runner.start_demo(NOW)
        assert broker.submissions==0


def test_order_once_restart_reconcile_and_single_writer(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    runner.start_demo(NOW)
    first=runner.submit(signal(),NOW)
    assert first['state']=='filled'
    with pytest.raises(SafetyStop,match='single execution writer'):
        create(tmp_path,ready_config,broker)
    runner.close()
    restarted,_=create(tmp_path,ready_config,broker)
    with restarted:
        repeated=restarted.submit(signal(),NOW)
        assert repeated['duplicate'] and broker.submissions==1
        assert restarted.reconcile(NOW)['mode']=='active'
        with pytest.raises(SafetyStop,match='exposure already'):
            restarted.submit(signal(2),NOW)


@pytest.mark.parametrize('fault',['timeout_after_fill','unknown_before'])
def test_timeout_never_resends_intent(tmp_path,ready_config,fault):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.fault=fault
        with pytest.raises(SafetyStop,match='uncertain'):
            runner.submit(signal(),NOW)
        assert runner.submit(signal(),NOW)['duplicate']
        assert broker.submissions==1
        if fault=='timeout_after_fill':
            assert runner.reconcile(NOW)['mode']=='active'
        else:
            with pytest.raises(SafetyStop):
                runner.reconcile(NOW)


def test_partial_fill_cancels_remainder_and_missing_stop_flattens(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.fault='partial'
        runner.submit(signal(),NOW)
        assert broker.get_open_orders()==[]
        assert len(broker.get_positions())==1
        runner.pause(flatten=True)
        assert broker.get_positions()==[]
        broker.fault='missing_stop'
        runner.start_demo(NOW)
        with pytest.raises(SafetyStop):
            runner.submit(signal(2),NOW)
        assert broker.get_positions()==[] and runner.state()['paused']


def test_daily_drawdown_persistent_cash_flow_adjusted(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    runner.start_demo(NOW)
    broker.account=broker.account.model_copy(update={'equity':980.,'balance':980.})
    assert runner.reconcile(NOW)['daily_halted']
    runner.close()
    restarted,_=create(tmp_path,ready_config,broker)
    with restarted:
        assert restarted.reconcile(NOW)['daily_halted']
        broker.account=broker.account.model_copy(update={'equity':1980.,'balance':1980.,'cumulative_cash_flow':1000.})
        assert restarted.reconcile(NOW)['high_water']==2000.
        assert restarted.state()['daily_halted']
        broker.account=broker.account.model_copy(update={'equity':1800.,'balance':1800.})
        assert restarted.reconcile(NOW)['permanent_halted']
        assert restarted.reconcile(NOW+timedelta(days=1))['permanent_halted']


def test_stale_quote_manual_position_and_cutoff(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.quote=broker.quote.model_copy(update={'timestamp':NOW-timedelta(seconds=20)})
        with pytest.raises(SafetyStop,match='stale'):
            runner.submit(signal(),NOW)
        broker.quote=broker.quote.model_copy(update={'timestamp':NOW})
        runner.submit(signal(),NOW)
        assert broker.get_positions()
        runner.watchdog(NOW.replace(hour=21))
        assert broker.get_positions()==[]
        broker.positions['manual']=Position(position_id='manual',client_order_id='unowned',symbol=ready_config.instrument.symbol,
                                           side=1,lots=.01,entry_price=1500.,stop_loss=1499.)
        with pytest.raises(SafetyStop):
            runner.reconcile(NOW.replace(hour=22))
        assert 'manual' in broker.positions


def test_bridge_https_mapping_and_no_transport_retries(ready_config):
    import httpx
    from qarevin.bridge_adapter import HTTPDemoAdapter
    calls=[]
    def transport(request):
        calls.append(request)
        assert request.headers['X-Qarevin-Environment']=='demo'
        if request.url.path=='/v1/quotes/XAUUSD.m':
            return httpx.Response(200,json={'symbol':'XAUUSD.m','bid':1500.,'ask':1500.3,'timestamp':NOW.isoformat()})
        if request.url.path=='/v1/instruments/XAUUSD.m':
            return httpx.Response(200,json=ready_config.instrument.model_copy(update={'symbol':'XAUUSD.m'}).model_dump())
        return httpx.Response(500,text='sensitive provider error')
    with pytest.raises(ValueError,match='HTTPS'):
        HTTPDemoAdapter('http://remote.example','a'*40,account_alias='a',server='s',symbol='XAUUSD')
    adapter=HTTPDemoAdapter('https://bridge.example','a'*40,account_alias='a',server='s',symbol='XAUUSD',
                            broker_symbol='XAUUSD.m',transport=httpx.MockTransport(transport))
    assert adapter.get_quote('XAUUSD').symbol=='XAUUSD'
    assert adapter.get_instrument_spec('XAUUSD').symbol=='XAUUSD'
    with pytest.raises(ConnectionError,match='bridge_status_500'):
        adapter.health_check()
    assert len(calls)==3
    adapter.close()


def test_concurrent_submissions_reserve_only_one_position(tmp_path,ready_config):
    from concurrent.futures import ThreadPoolExecutor
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        def submit(index):
            try:
                return runner.submit(signal(index),NOW)['state']
            except SafetyStop:
                return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,[1,2]))
        assert sorted(results)==['blocked','filled'] and broker.submissions==1


def test_causal_demo_runtime_rejects_unpinned_and_future_bars(tmp_path,ready_config):
    from qarevin.demo_strategy import DemoStrategy
    from qarevin.domain import source_identity
    from qarevin.strategies import StrategySpec
    from test_data import make_bars
    strategy=StrategySpec(family='no_trade')
    identity=digest({'strategy':strategy.model_dump(),'source_hash':source_identity(),'config_hash':digest(ready_config)})
    broker=FakeBroker(ready_config.instrument,now=NOW)
    with DemoRunner(tmp_path/'runtime.sqlite',broker,ready_config,strategy_hash=identity,
                    account_alias='synthetic-demo',server='fake') as runner:
        runtime=DemoStrategy(runner,strategy)
        runner.start_demo(NOW)
        assert runtime.tick(make_bars(60,'2026-11-05 10:00:00'),NOW)['status']=='no_signal'
        with pytest.raises(SafetyStop,match='future'):
            runtime.tick(make_bars(60,'2026-11-05 12:00:00'),NOW)


def test_reject_disconnect_and_widened_stop_fail_closed(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.fault='reject'
        assert runner.submit(signal(),NOW)['state']=='rejected'
        broker.connected=False
        with pytest.raises(SafetyStop):
            runner.submit(signal(2),NOW)
        assert broker.submissions==1
        broker.connected=True
        broker.fault=None
        runner.submit(signal(2),NOW)
        position=next(iter(broker.positions.values()))
        broker.positions[position.position_id]=position.model_copy(update={'stop_loss':position.stop_loss-10})
        with pytest.raises(SafetyStop):
            runner.reconcile(NOW)
        assert broker.get_positions()==[] and runner.state()['paused']


def test_uncertain_flatten_stays_paused_and_clock_cannot_reset_loss_day(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        runner.submit(signal(),NOW)
        broker.fault='close_timeout'
        with pytest.raises(SafetyStop,match='flatten not confirmed'):
            runner.pause(flatten=True)
        assert runner.state()['paused'] and broker.get_positions()
        with pytest.raises(SafetyStop):
            runner.reconcile(NOW-timedelta(days=1))


def test_cutoff_closes_known_positions_even_when_static_contract_check_fails(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        runner.submit(signal(),NOW)
        broker.spec=broker.spec.model_copy(update={'tick_size':.02})
        with pytest.raises(SafetyStop):
            runner.watchdog(NOW.replace(hour=21))
        assert broker.get_positions()==[]
        assert runner.state()['mode']=='reconciling'


def test_dynamic_margin_does_not_change_contract_identity_but_caps_new_orders(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.spec=broker.spec.model_copy(update={'margin_per_lot':40000.,'verified':False})
        assert runner.reconcile(NOW)['mode']=='active'
        with pytest.raises(SafetyStop,match='actual broker margin'):
            runner.submit(signal(),NOW)
        assert broker.submissions==0


def test_owner_resolution_and_critical_ack_are_explicit(tmp_path,ready_config):
    runner,broker=create(tmp_path,ready_config)
    with runner:
        runner.start_demo(NOW)
        broker.fault='unknown_before'
        with pytest.raises(SafetyStop):
            runner.submit(signal(),NOW)
        runner.resolve_intent(signal().signal_id,'f'*64,'Owner checked complete broker order and deal history',NOW)
        broker.fault='missing_stop'
        runner.start_demo(NOW)
        with pytest.raises(SafetyStop):
            runner.submit(signal(2),NOW)
        with pytest.raises(SafetyStop,match='acknowledgement'):
            runner.start_demo(NOW)
        runner.acknowledge_halt('protection_failure','e'*64,'Owner verified native stop support and fixed bridge behavior',NOW)
        broker.fault=None
        assert runner.start_demo(NOW)['mode']=='active'


def test_paused_strategy_can_still_exit_known_position(tmp_path,ready_config,monkeypatch):
    import pandas as pd
    import qarevin.demo_strategy as module
    from qarevin.domain import source_identity
    from qarevin.strategies import StrategySpec
    from test_data import make_bars
    spec=StrategySpec(family='no_trade')
    identity=digest({'strategy':spec.model_dump(),'source_hash':source_identity(),'config_hash':digest(ready_config)})
    broker=FakeBroker(ready_config.instrument,now=NOW)
    with DemoRunner(tmp_path/'paused.sqlite',broker,ready_config,strategy_hash=identity,
                    account_alias='synthetic-demo',server='fake') as runner:
        runtime=module.DemoStrategy(runner,spec)
        runner.start_demo(NOW)
        runner.submit(signal(),NOW)
        runner.pause()
        monkeypatch.setattr(module,'signals',lambda bars,spec:pd.DataFrame({'side':[0],'stop_distance':[1.]},index=pd.DatetimeIndex([NOW])))
        assert runtime.tick(make_bars(60,'2026-11-05 11:00:00'),NOW)['status']=='paused'
        assert broker.get_positions()==[]
