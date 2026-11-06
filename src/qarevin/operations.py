"""Owner-side durable alerts and forward observations. No sender/cron is installed automatically."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from qarevin.domain import Contract, canonical_json, digest
from qarevin.evidence import EvidenceStore


class Alert(Contract):
    kind: Literal['execution_halt','broker_unavailable','quote_stale','spread_wide','backup_failed',
                  'resource_pressure','evidence_gap','integrity_failure','drift_warning','owner_review']
    message: str = Field(min_length=5,max_length=1000)
    critical: bool = False
    evidence_refs: tuple[str,...] = Field(default=(),max_length=10)


def epoch(now: datetime) -> float:
    if now.tzinfo is None:
        raise ValueError('aware operational clock required')
    return now.timestamp()


class AlertOutbox:
    def __init__(self,store: EvidenceStore):
        self.store=store
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS alerts(
                    id TEXT PRIMARY KEY,body TEXT NOT NULL,state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL,
                    lease_id TEXT,lease_until REAL,delivery_id TEXT,ack_actor TEXT
                );
                CREATE TABLE IF NOT EXISTS conditions(id TEXT PRIMARY KEY,active INTEGER NOT NULL,generation INTEGER NOT NULL,last_event REAL NOT NULL DEFAULT 0);
            ''')
            if 'last_event' not in {row[1] for row in db.execute('PRAGMA table_info(conditions)')}:
                db.execute('ALTER TABLE conditions ADD COLUMN last_event REAL NOT NULL DEFAULT 0')

    def enqueue(self,dedup_key: str,alert: Alert,now: datetime,*,db=None) -> str:
        if not 1<=len(dedup_key)<=256:
            raise ValueError('bounded dedup key required')
        identifier=digest({'kind':alert.kind,'dedup_key':dedup_key})
        if db is None:
            with self.store.transaction() as connection:
                return self.enqueue(dedup_key,alert,now,db=connection)
        if db.execute('SELECT 1 FROM alerts WHERE id=?',(identifier,)).fetchone():
            return identifier
        count=db.execute("SELECT COUNT(*) FROM alerts WHERE state IN ('pending','delivering') OR (state='sent' AND json_extract(body,'$.critical')=1)").fetchone()[0]
        if not alert.critical and count>=900:
            raise RuntimeError('alert queue full; owner intervention required')
        db.execute('INSERT INTO alerts(id,body,state,next_attempt) VALUES(?,?,?,?)',
                   (identifier,canonical_json(alert),'pending',epoch(now)))
        self.store.audit('alert_queued',{'alert_id':identifier,'kind':alert.kind,'critical':alert.critical},db=db)
        return identifier

    def condition(self,key: str,active: bool,alert: Alert,now: datetime) -> str | None:
        with self.store.transaction() as db:
            prior=db.execute('SELECT * FROM conditions WHERE id=?',(key,)).fetchone()
            generation=prior['generation'] if prior else 0
            last_event=prior['last_event'] if prior else 0
            if active and (prior is None or not prior['active']):
                identifier=digest({'kind':alert.kind,'dedup_key':key+':'+str(generation)})
                outstanding=db.execute("SELECT state FROM alerts WHERE id=? AND state!='acknowledged'",(identifier,)).fetchone()
                coalesce=outstanding is not None and (alert.critical or outstanding[0] in ('pending','delivering') or epoch(now)-last_event<3600)
                if not coalesce:
                    generation+=1
                    last_event=epoch(now)
            db.execute('INSERT INTO conditions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET active=excluded.active,generation=excluded.generation,last_event=excluded.last_event',
                       (key,int(active),generation,last_event))
            return self.enqueue(key+':'+str(generation),alert,now,db=db) if active else None

    def pending(self) -> list[dict]:
        with self.store.read() as db:
            return [dict(row) for row in db.execute("SELECT * FROM alerts WHERE state IN ('pending','delivering') OR (state='sent' AND json_extract(body,'$.critical')=1) ORDER BY next_attempt,id")]

    def dispatch_one(self,sender,now: datetime) -> dict | None:
        """sender(alert_id, body) must use a bounded timeout and stable provider idempotency if supported."""
        current=epoch(now)
        lease=uuid.uuid4().hex
        with self.store.transaction() as db:
            db.execute("UPDATE alerts SET state='pending',lease_id=NULL WHERE state='delivering' AND lease_until<?",(current,))
            row=db.execute("SELECT * FROM alerts WHERE state IN ('pending','sent') AND next_attempt<=? ORDER BY next_attempt,id LIMIT 1",(current,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE alerts SET state='delivering',lease_id=?,lease_until=?,attempts=attempts+1 WHERE id=?",(lease,current+120,row['id']))
        body=json.loads(row['body'])
        try:
            delivery_id=sender(row['id'],body)
            if not isinstance(delivery_id,str) or not 1<=len(delivery_id)<=128:
                raise ValueError('sender must return bounded delivery identifier')
            with self.store.transaction() as db:
                cursor=db.execute("UPDATE alerts SET state='sent',delivery_id=?,lease_id=NULL,next_attempt=? WHERE id=? AND state='delivering' AND lease_id=?",
                           (delivery_id,current+900 if body['critical'] else 1e30,row['id'],lease))
                self.store.audit('alert_sent' if cursor.rowcount else 'alert_send_late',{'alert_id':row['id'],'delivery_id':delivery_id},db=db)
            with self.store.read() as db:
                final=db.execute('SELECT state FROM alerts WHERE id=?',(row['id'],)).fetchone()[0]
            return {'id':row['id'],'status':final,'acknowledged':final=='acknowledged'}
        except Exception as exc:
            with self.store.transaction() as db:
                cursor=db.execute("UPDATE alerts SET state='pending',lease_id=NULL,next_attempt=? WHERE id=? AND state='delivering' AND lease_id=?",
                           (current+min(3600,60*2**min(row['attempts'],6)),row['id'],lease))
                self.store.audit('alert_delivery_failed' if cursor.rowcount else 'alert_send_late',{'alert_id':row['id'],'error_type':type(exc).__name__},db=db)
            with self.store.read() as db:
                final=db.execute('SELECT state FROM alerts WHERE id=?',(row['id'],)).fetchone()[0]
            return {'id':row['id'],'status':final,'acknowledged':final=='acknowledged','error_type':type(exc).__name__}

    def acknowledge(self,identifier: str,actor: str):
        if not 1<=len(actor)<=128:
            raise ValueError('authenticated owner actor required')
        with self.store.transaction() as db:
            existing=db.execute('SELECT state FROM alerts WHERE id=?',(identifier,)).fetchone()
            if existing is None:
                raise KeyError('alert not found')
            if existing[0]=='acknowledged':
                return
            db.execute("UPDATE alerts SET state='acknowledged',ack_actor=?,lease_id=NULL WHERE id=?",(actor,identifier))
            self.store.audit('alert_acknowledged',{'alert_id':identifier,'actor':actor},db=db)


class ForwardObserver:
    """Observations are diagnostics until actual broker/deal-history evidence is validated."""
    def __init__(self,runner,outbox: AlertOutbox,*,broker_validation_hash: str | None = None):
        self.runner,self.outbox=runner,outbox
        self.store=runner.store
        self.broker_validation_hash=broker_validation_hash

    def tick(self,now: datetime) -> dict:
        epoch(now)
        deployment=digest(self.store.get('deployment_identity','pinned'))
        error=None
        alert_errors=[]
        def condition(*args):
            try:
                return self.outbox.condition(*args)
            except Exception as exc:
                alert_errors.append(type(exc).__name__)
                try:
                    self.outbox.enqueue(deployment+':alert-persistence-failure',Alert(kind='integrity_failure',critical=True,
                        message='Operational alert persistence failed; owner must inspect storage and queue capacity'),now)
                except Exception as fallback:
                    alert_errors.append(type(fallback).__name__)
                return None
        try:
            state=self.runner.watchdog(now)
        except Exception as exc:
            state=self.runner.state() or {'mode':'reconciling'}
            error=type(exc).__name__
        bad=state['mode'] in ('halted','reconciling')
        condition(deployment+':execution',bad,Alert(kind='execution_halt',critical=True,
                              message='Execution halted or awaiting reconciliation; inspect owner runbook',evidence_refs=(deployment,)),now)
        try:
            account=self.runner._account_identity(for_exit=True)
            quote=self.runner.broker.get_quote(self.runner.config.instrument.symbol)
        except Exception as exc:
            condition(deployment+':broker',True,Alert(kind='broker_unavailable',critical=True,
                                  message='Confirmed demo account/quote unavailable; entries remain fail-closed',evidence_refs=(deployment,)),now)
            return {'state':state,'snapshot':None,'error_type':type(exc).__name__,'alert_errors':alert_errors}
        condition(deployment+':broker',False,Alert(kind='broker_unavailable',message='Broker recovered'),now)
        age=(now-quote.timestamp).total_seconds()
        condition(deployment+':quote',age>self.runner.config.risk.max_quote_age_seconds or age< -2,
                              Alert(kind='quote_stale',critical=True,message='Executable quote stale or in the future',evidence_refs=(deployment,)),now)
        spread=(quote.ask-quote.bid)/self.runner.config.instrument.point
        condition(deployment+':spread',spread>self.runner.config.risk.max_spread_points,
                              Alert(kind='spread_wide',message='Spread exceeds entry limit',evidence_refs=(deployment,)),now)
        minute=now.astimezone(timezone.utc).replace(second=0,microsecond=0).isoformat()
        identifier=digest({'deployment':deployment,'minute':minute})
        try:
            self.store.get('forward_snapshot',identifier)
        except KeyError:
            from qarevin.broker import FakeBroker
            body={'deployment':deployment,'observed_at':minute,'account_alias':account.alias,'server':account.server,
                  'equity':account.equity,'balance':account.balance,'margin':account.margin,
                  'cash_flow':account.cumulative_cash_flow,'cash_flow_verified':account.cash_flow_verified,
                  'quote_age_seconds':age,'spread_points':spread,'mode':state['mode'],
                  'synthetic':isinstance(self.runner.broker,FakeBroker),'broker_validation_hash':self.broker_validation_hash}
            self.store.put('forward_snapshot',body,identity=identifier)
        return {'state':state,'snapshot':identifier,'error_type':error,'alert_errors':alert_errors}

    def report(self) -> dict:
        deployment=digest(self.store.get('deployment_identity','pinned'))
        with self.store.read() as db:
            summary=db.execute("SELECT COUNT(*) AS count,MAX(json_extract(body,'$.synthetic')) AS synthetic FROM objects WHERE kind='forward_snapshot' AND json_extract(body,'$.deployment')=?",(deployment,)).fetchone()
            if not summary['count']:
                return {'status':'insufficient_evidence','eligible_for_live':False}
            first=json.loads(db.execute("SELECT body FROM objects WHERE kind='forward_snapshot' AND json_extract(body,'$.deployment')=? ORDER BY json_extract(body,'$.observed_at') LIMIT 1",(deployment,)).fetchone()[0])
            last=json.loads(db.execute("SELECT body FROM objects WHERE kind='forward_snapshot' AND json_extract(body,'$.deployment')=? ORDER BY json_extract(body,'$.observed_at') DESC LIMIT 1",(deployment,)).fetchone()[0])
        return {'deployment':deployment,'snapshots':summary['count'],'started_at':first['observed_at'],
                'observed_through':last['observed_at'],'equity_change_after_cash_flows':last['equity']-first['equity']-(last['cash_flow']-first['cash_flow']),
                'synthetic':bool(summary['synthetic']),'closed_trade_count':None,
                'eligible_for_live':False,
                'missing':['validated broker fill/deal history','continuous coverage review','independent forward scorecard'],
                'note':'Sampled account observations do not establish closed trades or three-month readiness'}
