"""Owner-only Ed25519 authorization; no live broker connector is shipped or enabled."""
from __future__ import annotations

import base64
import calendar
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, model_validator

from qarevin.domain import Contract, canonical_json, digest, unique_json
from qarevin.evidence import EvidenceStore

HASH=r'^[a-f0-9]{64}$'


def three_months_after(value: datetime) -> datetime:
    month=value.month+3
    year=value.year+(month-1)//12
    month=(month-1)%12+1
    return value.replace(year=year,month=month,day=min(value.day,calendar.monthrange(year,month)[1]))


class DeploymentScope(Contract):
    environment: Literal['live'] = 'live'
    strategy_hash: str = Field(pattern=HASH)
    risk_policy_hash: str = Field(pattern=HASH)
    evidence_hash: str = Field(pattern=HASH)
    broker: str = Field(min_length=1,max_length=128)
    account_alias: str = Field(min_length=1,max_length=128)
    account_server: str = Field(min_length=1,max_length=128)
    capital: float = Field(gt=0)
    notional_cap: float = Field(gt=0)
    currency: str = Field(pattern=r'^[A-Z]{3}$')


class ResearchMetrics(Contract):
    net_pnl: float
    net_return: float
    max_drawdown: float = Field(ge=0)
    profit_factor: float | None
    calmar: float | None
    sharpe: float | None
    trade_count: int = Field(ge=0)
    calendar_days: float = Field(ge=0)


class CostScenario(Contract):
    spread_multiplier: float = Field(ge=1)
    slippage_multiplier: float = Field(ge=1)
    net_return: float
    max_drawdown: float = Field(ge=0)
    trade_count: int = Field(ge=0)


class CandidateReport(Contract):
    strategy_hash: str = Field(pattern=HASH)
    risk_policy_hash: str = Field(pattern=HASH)
    broker: str = Field(min_length=1,max_length=128)
    account_alias: str = Field(min_length=1,max_length=128)
    account_server: str = Field(min_length=1,max_length=128)
    capital: float = Field(gt=0)
    notional_cap: float = Field(gt=0)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    human_readable_logic: str = Field(min_length=20,max_length=8000)
    differences_from_parent: str = Field(min_length=5,max_length=4000)
    data_coverage: str = Field(min_length=10,max_length=1000)
    data_qa_hash: str = Field(pattern=HASH)
    split_manifest_hash: str = Field(pattern=HASH)
    walk_forward_report_hash: str = Field(pattern=HASH)
    holdout_report_hash: str = Field(pattern=HASH)
    demo_report_hash: str = Field(pattern=HASH)
    broker_contract_report_hash: str = Field(pattern=HASH)
    rollback_runbook_hash: str = Field(pattern=HASH)
    research_metrics: ResearchMetrics
    stressed_costs: tuple[CostScenario, ...] = Field(min_length=2,max_length=5)
    trial_count: int = Field(ge=1)
    holdout_open_count: int = Field(ge=1)
    demo_started_at: datetime
    demo_observed_through: datetime
    demo_trade_count: int = Field(ge=0)
    demo_max_drawdown: float = Field(ge=0)
    demo_risk_violations: int = Field(ge=0)
    correlated_exposure: str = Field(min_length=5,max_length=2000)
    uncertainty_and_alternatives: str = Field(min_length=20,max_length=8000)
    synthetic: bool = True
    verified_data: bool = False
    verified_broker: bool = False
    passed_walk_forward: bool = False
    passed_holdout: bool = False
    verified_forward_evidence: bool = False

    @model_validator(mode='after')
    def chronology(self):
        if any(value.tzinfo is None for value in (self.demo_started_at,self.demo_observed_through)):
            raise ValueError('forward evidence requires aware timestamps')
        if self.demo_observed_through<self.demo_started_at:
            raise ValueError('invalid forward chronology')
        return self

    def missing(self,now: datetime) -> list[str]:
        if now.tzinfo is None:
            raise ValueError('aware owner clock required')
        metrics=self.research_metrics
        conditions={'research_net':metrics.net_pnl>0 and metrics.net_return>0,
                    'research_drawdown':metrics.max_drawdown<=.15,
                    'research_profit_factor':metrics.profit_factor is not None and metrics.profit_factor>1.2,
                    'research_calmar':metrics.calmar is not None and metrics.calmar>.5 and metrics.calendar_days>=365,
                    'research_trade_count':metrics.trade_count>=100,
                    'cost_stress':all(item.net_return>0 and item.max_drawdown<=.15 and item.trade_count>=100 for item in self.stressed_costs),
                    'real_data':not self.synthetic,'verified_data':self.verified_data,
                    'verified_broker':self.verified_broker,'walk_forward':self.passed_walk_forward,
                    'holdout':self.passed_holdout,'verified_forward':self.verified_forward_evidence,
                    'three_calendar_months':self.demo_observed_through>=three_months_after(self.demo_started_at),
                    'enough_trades':self.demo_trade_count>=100,'demo_drawdown':self.demo_max_drawdown<=.05,
                    'no_risk_violations':self.demo_risk_violations==0,
                    'not_future':self.demo_observed_through<=now,
                    'recent_evidence':0<=(now-self.demo_observed_through).total_seconds()<=7*86400}
        return [name for name,passed in conditions.items() if not passed]

    def scope(self) -> DeploymentScope:
        return DeploymentScope(strategy_hash=self.strategy_hash,risk_policy_hash=self.risk_policy_hash,
                 evidence_hash=digest(self),broker=self.broker,account_alias=self.account_alias,
                 account_server=self.account_server,capital=self.capital,notional_cap=self.notional_cap,currency=self.currency)


class Claims(DeploymentScope):
    authorization_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=0)

    @model_validator(mode='after')
    def bounded(self):
        if not 0<self.expires_at-self.issued_at<=3600:
            raise ValueError('authorization lifetime must be 1..3600 seconds')
        return self


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def _decode(value: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise ValueError('invalid authorization encoding')
    return base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)


def issue(report: CandidateReport,key: Ed25519PrivateKey,now: datetime,*,ttl_seconds: int = 600) -> str:
    """Called only by an authenticated owner process with private signing-key access."""
    if report.missing(now):
        raise PermissionError('candidate evidence is not live-ready')
    claims=Claims(**report.scope().model_dump(),authorization_id=uuid.uuid4().hex,
                  issued_at=int(now.timestamp()),expires_at=int(now.timestamp())+ttl_seconds)
    payload=canonical_json(claims).encode()
    return _encode(payload)+'.'+_encode(key.sign(payload))


class ApprovalVerifier:
    def __init__(self,public_key: Ed25519PublicKey,owner_state: EvidenceStore,*,clock=None):
        self.key,self.store=public_key,owner_state
        self.clock=clock or (lambda: datetime.now(timezone.utc))
        with owner_state.read() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('jobs','execution_state')").fetchone():
                raise ValueError('approval ledger must be isolated from research/demo state')

    def verify(self,token: str,expected: DeploymentScope,now: datetime) -> Claims:
        if now.tzinfo is None or len(token)>16384 or token.count('.')!=1:
            raise PermissionError('invalid authorization envelope')
        encoded,signature=token.split('.')
        try:
            payload=_decode(encoded)
            self.key.verify(_decode(signature),payload)
            claims=Claims.model_validate(unique_json(payload.decode()))
        except (ValueError,InvalidSignature,UnicodeError,RecursionError) as exc:
            raise PermissionError('invalid signed authorization') from exc
        current=int(now.timestamp())
        if not claims.issued_at<=current<claims.expires_at:
            raise PermissionError('authorization expired or issued in the future')
        scope={key:value for key,value in claims.model_dump().items() if key not in ('authorization_id','issued_at','expires_at')}
        if scope!=expected.model_dump():
            raise PermissionError('authorization scope mismatch')
        with self.store.read() as db:
            if db.execute("SELECT 1 FROM objects WHERE kind IN ('approval_revoked','approval_consumed') AND id=?",(claims.authorization_id,)).fetchone():
                raise PermissionError('authorization revoked or already consumed')
        return claims

    def consume(self,token: str,expected: DeploymentScope,now: datetime) -> Claims:
        claims=self.verify(token,expected,now)
        with self.store.transaction() as db:
            current=max(int(now.timestamp()),int(self.clock().timestamp()))
            if not claims.issued_at<=current<claims.expires_at:
                raise PermissionError('authorization expired while acquiring deployment lock')
            if db.execute("SELECT 1 FROM objects WHERE kind IN ('approval_revoked','approval_consumed') AND id=?",(claims.authorization_id,)).fetchone():
                raise PermissionError('authorization revoked or already consumed')
            self.store.put('approval_consumed',{'scope_hash':digest(expected),'consumed_at':now.isoformat()},
                           identity=claims.authorization_id,db=db)
        return claims

    def revoke(self,authorization_id: str):
        if not re.fullmatch(r'[a-f0-9]{32}',authorization_id):
            raise ValueError('invalid authorization ID')
        self.store.put('approval_revoked',{'status':'revoked'},identity=authorization_id)


class DisabledLiveController:
    """Reviewable authorization workflow with no order/deployment actuator."""
    def __init__(self,verifier: ApprovalVerifier):
        self.verifier=verifier

    def prepare(self,report: CandidateReport,token: str,now: datetime) -> dict:
        if report.missing(now):
            raise PermissionError('live evidence gates incomplete')
        claims=self.verifier.verify(token,report.scope(),now)
        return {'status':'authorization_valid_live_disabled','authorization_id':claims.authorization_id,
                'evidence_hash':digest(report),'activation_performed':False,'authorization_consumed':False}

    def activate(self,*args,**kwargs):
        raise PermissionError('live connector is not implemented or enabled')
