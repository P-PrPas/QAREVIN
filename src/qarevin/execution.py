"""Demo-only durable order/risk controller. Owner process only; no agent HTTP route."""
from __future__ import annotations

import fcntl
import json
import math
import re
import threading
from functools import wraps
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

from qarevin.backtest import size_lots
from qarevin.broker import BrokerAdapter, Order, OrderResult, Signal
from qarevin.domain import ResearchConfig, canonical_json, digest, source_identity
from qarevin.evidence import EvidenceStore


def serialized(method):
    @wraps(method)
    def locked(self,*args,**kwargs):
        with self._mutex:
            return method(self,*args,**kwargs)
    return locked


class SafetyStop(ValueError):
    pass


class DemoRunner:
    def __init__(self,path: Path,broker: BrokerAdapter,config: ResearchConfig,*,
                 strategy_hash: str,account_alias: str,server: str):
        self._mutex=threading.RLock()
        config.require_demo_ready()
        self.store=EvidenceStore(path)
        self.broker,self.config=broker,config
        self.strategy_hash,self.account_alias,self.server=strategy_hash,account_alias,server
        self.policy_hash=digest(config.risk)
        self._lock=path.with_suffix(path.suffix+'.lock').open('a+')
        self._lock_path=path.with_suffix(path.suffix+'.lock')
        self._lock_path.chmod(0o600)
        try:
            fcntl.flock(self._lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise SafetyStop('single execution writer already running') from None
        try:
            with self.store.transaction() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                    raise SafetyStop('execution state must be separate from research')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS execution_state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,body TEXT NOT NULL,status TEXT NOT NULL,result TEXT);
                ''')
            self.store.put('deployment_identity',{'environment':'demo','account_alias':account_alias,'server':server,
                           'strategy_hash':strategy_hash,'policy_hash':self.policy_hash,'config_hash':digest(config),'engine_source_hash':source_identity()},identity='pinned')
        except BaseException:
            self.close()
            raise
        self.reconciled=False

    def close(self):
        if not self._lock.closed:
            fcntl.flock(self._lock,fcntl.LOCK_UN)
            self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    def state(self):
        with self.store.transaction() as db:
            row=db.execute('SELECT body FROM execution_state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def save_state(self,state,*,db=None):
        if db is None:
            with self.store.transaction() as connection:
                self.save_state(state,db=connection)
            return
        db.execute('INSERT INTO execution_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                   (canonical_json(state),))

    def _account_identity(self,*,for_exit=False):
        if not for_exit and self.store.get('deployment_identity','pinned')['engine_source_hash'] != source_identity():
            raise SafetyStop('pinned execution source changed')
        account=self.broker.get_account()
        if account.environment!='demo' or account.alias!=self.account_alias or account.server!=self.server:
            raise SafetyStop('wrong account identity or environment')
        if not for_exit and (account.currency!=self.config.instrument.account_currency or not account.cash_flow_verified or not account.trade_allowed):
            raise SafetyStop('account currency, cash flows or trade permission unverified')
        return account

    def _account(self):
        account=self._account_identity()
        actual=self.broker.get_instrument_spec(self.config.instrument.symbol)
        exclusions={'margin_per_lot','verified'}
        if {k:v for k,v in actual.model_dump().items() if k not in exclusions}!={k:v for k,v in self.config.instrument.model_dump().items() if k not in exclusions}:
            raise SafetyStop('static instrument contract changed')
        return account

    def _risk_state(self,now: datetime):
        if now.tzinfo is None:
            raise SafetyStop('aware clock required')
        account=self._account()
        day=now.astimezone(__import__('zoneinfo').ZoneInfo(self.config.risk.risk_day_timezone)).date().isoformat()
        state=self.state()
        if state is None:
            state={'day':day,'day_start':account.equity,'high_water':account.equity,
                   'cash_flow':account.cumulative_cash_flow,'daily_halted':False,'permanent_halted':False,
                   'requires_ack':False,'ack_reason':None,'paused':True,'mode':'reconciling','reason':'owner_activation_required','last_observed':now.isoformat()}
        if now < datetime.fromisoformat(state['last_observed']):
            raise SafetyStop('clock moved backwards')
        state['last_observed']=now.isoformat()
        flow=account.cumulative_cash_flow-state['cash_flow']
        state['high_water']+=flow
        state['day_start']+=flow
        state['cash_flow']=account.cumulative_cash_flow
        if min(state['day_start'],state['high_water'])<=0:
            raise SafetyStop('invalid cash-flow adjusted risk basis')
        if state['day']!=day:
            state.update(day=day,day_start=account.equity,daily_halted=False)
        state['high_water']=max(state['high_water'],account.equity)
        if account.equity<=state['day_start']*(1-self.config.risk.daily_loss):
            state['daily_halted']=True
            state['reason']='daily_loss'
        if account.equity<=state['high_water']*(1-self.config.risk.max_drawdown):
            state['permanent_halted']=True
            state['reason']='drawdown'
        self.save_state(state)
        return account,state

    def _persist_result(self,identifier: str,result: OrderResult):
        with self.store.read() as db:
            row=db.execute('SELECT body FROM intents WHERE id=?',(identifier,)).fetchone()
        if row is None:
            raise SafetyStop('broker result has no reserved intent')
        order=Order.model_validate_json(row[0])
        if result.filled_lots>order.lots+1e-9 or (result.state in ('filled','partial') and result.filled_lots<=0):
            raise SafetyStop('broker fill volume inconsistent with intent')
        if result.symbol is not None and result.symbol!=order.symbol:
            raise SafetyStop('broker result symbol mismatch')
        if result.client_order_id!=identifier:
            raise SafetyStop('broker correlation mismatch')
        with self.store.transaction() as db:
            db.execute('UPDATE intents SET status=?,result=? WHERE id=?',
                       (result.state,canonical_json(result),identifier))
            self.store.audit('order_'+result.state,{'client_order_id':identifier,'filled_lots':result.filled_lots},db=db)

    def _freeze(self,reason: str):
        state=self.state()
        if state:
            state.update(mode='reconciling',reason=reason)
            self.save_state(state)
        self.reconciled=False
        self.store.audit('execution_frozen',{'reason':reason})

    @serialized
    def reconcile(self,now: datetime):
        try:
            if not self.broker.health_check():
                raise SafetyStop('broker disconnected')
            account,state=self._risk_state(now)
            with self.store.transaction() as db:
                intents={row['id']:dict(row) for row in db.execute('SELECT * FROM intents').fetchall()}
            for identifier,row in intents.items():
                if row['status'] in ('prepared','unknown','accepted','partial'):
                    result=self.broker.find_order(identifier)
                    if result is None or result.state=='unknown':
                        raise SafetyStop('unresolved order intent')
                    self._persist_result(identifier,result)
            for pending in self.broker.get_open_orders():
                if pending.symbol!=self.config.instrument.symbol:
                    raise SafetyStop('unexpected pending order symbol')
                if pending.client_order_id not in intents:
                    raise SafetyStop('unexpected broker order')
                cancelled=self.broker.cancel_order(pending.client_order_id)
                if cancelled.state!='cancelled':
                    raise SafetyStop('pending order cancellation not confirmed')
                self._persist_result(pending.client_order_id,cancelled)
            positions=self.broker.get_positions()
            if len(positions)>self.config.risk.max_positions:
                raise SafetyStop('position limit exceeded')
            open_risk=0.
            for position in positions:
                if position.client_order_id not in intents or position.symbol!=self.config.instrument.symbol:
                    raise SafetyStop('unexpected broker position')
                intent=Order.model_validate_json(intents[position.client_order_id]['body'])
                if position.side!=intent.side or position.lots>intent.lots+1e-9:
                    raise SafetyStop('position side/volume mismatch')
                if position.stop_loss is None:
                    state.update(paused=True,reason='protection_failure',requires_ack=True,ack_reason='protection_failure')
                    self.save_state(state)
                    self.broker.close_position(position.position_id)
                    self.store.audit('protection_failure_flatten',{'position_id':position.position_id})
                    raise SafetyStop('missing broker protection; flatten requested')
                if (position.side==1 and position.stop_loss<intent.stop_loss-1e-9) or (position.side==-1 and position.stop_loss>intent.stop_loss+1e-9):
                    state.update(paused=True,reason='widened_stop',requires_ack=True,ack_reason='widened_stop')
                    self.save_state(state)
                    self.broker.close_position(position.position_id)
                    raise SafetyStop('broker stop wider than pinned intent; flatten requested')
                open_risk+=max(0,position.side*(position.entry_price-position.stop_loss))*position.lots*self.config.instrument.tick_value/self.config.instrument.tick_size
                open_risk+=2*position.lots*self.config.costs.commission_per_lot_side
            if open_risk>account.equity*self.config.risk.per_trade+1e-7:
                state.update(paused=True,reason='excess_open_risk',requires_ack=True,ack_reason='excess_open_risk')
                self.save_state(state)
                self.flatten_known_positions()
                raise SafetyStop('actual open risk exceeds policy')
            if state['daily_halted'] or state['permanent_halted']:
                state['mode']='halted'
            elif state['paused']:
                state['mode']='paused'
            else:
                state.update(mode='active',reason=None)
            self.save_state(state)
            self.reconciled=True
            return state
        except Exception as exc:
            self._freeze(type(exc).__name__)
            raise SafetyStop('reconciliation failed closed') from exc

    @serialized
    def start_demo(self,now: datetime):
        self._risk_state(now)
        state=self.state()
        if state.get('requires_ack'):
            raise SafetyStop('explicit owner acknowledgement required')
        state['paused']=False
        self.save_state(state)
        return self.reconcile(now)

    @serialized
    def submit(self,signal: Signal,now: datetime):
        with self.store.transaction() as db:
            prior=db.execute('SELECT * FROM intents WHERE id=?',(signal.signal_id,)).fetchone()
        if prior:
            # Durable idempotency: never send a previously prepared/unknown intent again.
            return {'client_order_id':signal.signal_id,'state':prior['status'],'duplicate':True}
        state=self.reconcile(now)
        if state['mode']!='active':
            raise SafetyStop('execution not active')
        account=self._account()
        quote=self.broker.get_quote(self.config.instrument.symbol)
        if quote.symbol!=self.config.instrument.symbol or not -2<=(now-quote.timestamp).total_seconds()<=self.config.risk.max_quote_age_seconds:
            raise SafetyStop('stale/future quote or symbol mismatch')
        local=now.astimezone(__import__('zoneinfo').ZoneInfo(self.config.session.timezone))
        if local.weekday()>=5 or not self.config.session.entry_start_hour<=local.hour<self.config.session.entry_end_hour:
            raise SafetyStop('entry session closed')
        spec=self.config.instrument
        spread=quote.ask-quote.bid
        if spread/spec.point>self.config.risk.max_spread_points:
            raise SafetyStop('spread limit')
        if self.broker.get_positions() or self.broker.get_open_orders():
            raise SafetyStop('exposure already exists')
        price=quote.ask if signal.side==1 else quote.bid
        if signal.stop_distance<spread+spec.stop_distance_min+spec.tick_size:
            raise SafetyStop('invalid stop distance')
        tick=Decimal(str(spec.tick_size))
        stop=float((Decimal(str(price-signal.side*signal.stop_distance))/tick).to_integral_value(
                    rounding=ROUND_CEILING if signal.side==1 else ROUND_FLOOR)*tick)
        lots=size_lots(account.equity,abs(price-stop),self.config)
        if lots==0 or lots*spec.margin_per_lot>account.free_margin or account.margin+lots*spec.margin_per_lot>account.equity*self.config.risk.max_margin_fraction:
            raise SafetyStop('minimum lot or free margin infeasible')
        order=Order(client_order_id=signal.signal_id,symbol=spec.symbol,side=signal.side,lots=lots,
                    reference_price=price,stop_loss=stop,strategy_hash=self.strategy_hash,policy_hash=self.policy_hash)
        margin=self.broker.calculate_margin(order)
        if not math.isfinite(margin) or margin<=0 or margin>account.free_margin or account.margin+margin>account.equity*self.config.risk.max_margin_fraction:
            raise SafetyStop('actual broker margin exceeds policy')
        with self.store.transaction() as db:
            db.execute('INSERT INTO intents VALUES(?,?,?,NULL)',(signal.signal_id,canonical_json(order),'prepared'))
            self.store.audit('order_prepared',{'client_order_id':signal.signal_id,'lots':lots,'policy_hash':self.policy_hash,'calculated_margin':margin},db=db)
        try:
            result=self.broker.place_order(order)
            self._persist_result(signal.signal_id,result)
            self.reconcile(now)
            return result.model_dump(mode='json')
        except Exception as exc:
            with self.store.transaction() as db:
                db.execute("UPDATE intents SET status='unknown' WHERE id=? AND status='prepared'",(signal.signal_id,))
                self.store.audit('order_uncertain',{'client_order_id':signal.signal_id,'error_type':type(exc).__name__},db=db)
            self._freeze('order_uncertainty')
            raise SafetyStop('order result uncertain; reconcile before any new entry') from exc

    @serialized
    def pause(self,*,flatten=False):
        state=self.state()
        if state is None:
            raise SafetyStop('deployment not activated')
        state.update(paused=True,mode='paused',reason='owner_pause')
        self.save_state(state)
        self.store.audit('owner_pause',{'flatten':flatten})
        if flatten:
            self.flatten_known_positions()

    @serialized
    def flatten_known_positions(self):
        try:
            self._flatten_known_positions()
        except Exception as exc:
            state=self.state()
            if state:
                state.update(paused=True,mode='reconciling',reason='flatten_uncertainty',requires_ack=True,ack_reason='flatten_uncertainty')
                self.save_state(state)
            self.store.audit('flatten_failed',{'error_type':type(exc).__name__})
            raise SafetyStop('flatten not confirmed; owner resolution required') from exc

    def _flatten_known_positions(self):
        self._account_identity(for_exit=True)  # Exit permission checks identity, not changing margin/contract assumptions.
        with self.store.read() as db:
            known={row[0] for row in db.execute('SELECT id FROM intents')}
        unknown=False
        for pending in self.broker.get_open_orders():
            if pending.client_order_id not in known:
                unknown=True
                continue
            result=self.broker.cancel_order(pending.client_order_id)
            if result.state!='cancelled':
                raise SafetyStop('cancel not confirmed')
            self._persist_result(pending.client_order_id,result)
        for position in self.broker.get_positions():
            if position.client_order_id not in known:
                unknown=True
                continue
            self.broker.close_position(position.position_id)
            self.store.audit('flatten_requested',{'position_id':position.position_id})
        remaining_positions=self.broker.get_positions()
        remaining_orders=self.broker.get_open_orders()
        if any(p.client_order_id in known for p in remaining_positions+remaining_orders):
            raise SafetyStop('owned flatten not confirmed')
        if unknown or remaining_positions or remaining_orders:
            raise SafetyStop('unowned exposure requires owner resolution')

    @serialized
    def acknowledge_halt(self,reason: str,evidence_hash: str,note: str,now: datetime):
        state=self.state()
        if not state or not state.get('requires_ack') or state.get('ack_reason')!=reason:
            raise SafetyStop('no matching halt to acknowledge')
        if not re.fullmatch(r'[a-f0-9]{64}',evidence_hash) or not 10<=len(note)<=1000 or now.tzinfo is None:
            raise ValueError('owner evidence hash, note and aware clock required')
        self._account_identity()
        self.store.put('owner_halt_acknowledgement',{'reason':reason,'evidence_hash':evidence_hash,'note':note,'at':now.isoformat()})
        state.update(requires_ack=False,ack_reason=None,paused=True,reason='owner_acknowledged')
        self.save_state(state)

    @serialized
    def resolve_intent(self,identifier: str,evidence_hash: str,note: str,now: datetime):
        if not re.fullmatch(r'[a-f0-9]{64}',evidence_hash) or not 10<=len(note)<=1000 or now.tzinfo is None:
            raise ValueError('owner broker-history evidence required')
        self._account_identity()
        with self.store.read() as db:
            row=db.execute('SELECT * FROM intents WHERE id=?',(identifier,)).fetchone()
        if row is None or row['status'] not in ('prepared','unknown'):
            raise SafetyStop('intent is not unresolved')
        if any(p.client_order_id==identifier for p in self.broker.get_positions()+self.broker.get_open_orders()):
            raise SafetyStop('broker still has matching exposure')
        actual=self.broker.find_order(identifier)
        if actual and (actual.filled_lots>0 or actual.state not in ('rejected','cancelled','unknown')):
            raise SafetyStop('broker evidence does not permit absent/rejected resolution')
        intent=Order.model_validate_json(row['body'])
        self.store.put('owner_intent_resolution',{'evidence_hash':evidence_hash,'note':note,'at':now.isoformat()},identity=identifier)
        self._persist_result(identifier,OrderResult(client_order_id=identifier,symbol=intent.symbol,state='rejected'))
        state=self.state()
        state.update(paused=True,mode='paused',reason='owner_resolved_intent')
        self.save_state(state)

    @serialized
    def watchdog(self,now: datetime):
        if now.tzinfo is None:
            raise SafetyStop('aware watchdog clock required')
        local=now.astimezone(__import__('zoneinfo').ZoneInfo(self.config.session.timezone))
        cutoff=local.weekday()>=5 or local.hour>=self.config.session.flatten_hour
        try:
            state=self.reconcile(now)
        except SafetyStop:
            prior=self.state() or {}
            if cutoff or prior.get('daily_halted') or prior.get('permanent_halted'):
                # Identity is rechecked inside flatten; a static contract failure must not bypass exits.
                self.store.audit('safety_exit_after_reconcile_failure',{'cutoff':cutoff})
                self.flatten_known_positions()
                self._freeze('reconcile_failed_safety_exit_attempted')
            raise
        if state['mode']=='halted' or cutoff:
            self.flatten_known_positions()
        return self.state()
