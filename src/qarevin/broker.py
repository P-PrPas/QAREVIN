"""Broker-neutral demo contract plus deterministic fault adapter. No live driver."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from qarevin.domain import Contract, InstrumentSpec


class Account(Contract):
    environment: Literal['demo','live']
    alias: str = Field(min_length=1)
    server: str = Field(min_length=1)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    equity: float
    balance: float
    margin: float = Field(ge=0)
    free_margin: float
    cumulative_cash_flow: float = 0
    cash_flow_verified: bool = False
    trade_allowed: bool = True


class Quote(Contract):
    symbol: str
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    timestamp: datetime

    @model_validator(mode='after')
    def valid(self):
        if self.ask < self.bid or self.timestamp.tzinfo is None:
            raise ValueError('quote requires ask>=bid and aware timestamp')
        return self


class Signal(Contract):
    signal_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    side: int = Field(ge=-1,le=1)
    stop_distance: float = Field(gt=0)

    @field_validator('side')
    @classmethod
    def direction(cls,value):
        if value not in (-1,1):
            raise ValueError('entry signal must be long or short')
        return value


class Order(Contract):
    client_order_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    symbol: str
    side: int
    lots: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    strategy_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    policy_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class OrderResult(Contract):
    client_order_id: str
    symbol: str | None = None
    state: Literal['accepted','partial','filled','rejected','cancelled','unknown']
    filled_lots: float = Field(default=0,ge=0)
    broker_order_id: str | None = None
    position_id: str | None = None


class Position(Contract):
    position_id: str
    client_order_id: str
    symbol: str
    side: int
    lots: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float | None = Field(default=None,gt=0)


class BrokerAdapter(Protocol):
    def get_account(self) -> Account: ...
    def get_instrument_spec(self, symbol: str) -> InstrumentSpec: ...
    def get_quote(self, symbol: str) -> Quote: ...
    def get_positions(self) -> list[Position]: ...
    def get_open_orders(self) -> list[OrderResult]: ...
    def find_order(self, client_order_id: str) -> OrderResult | None: ...
    def calculate_margin(self, order: Order) -> float: ...
    def place_order(self, order: Order) -> OrderResult: ...
    def cancel_order(self, client_order_id: str) -> OrderResult: ...
    def close_position(self, position_id: str) -> None: ...
    def health_check(self) -> bool: ...


class FakeBroker:
    """Faults are synthetic: never confuse this adapter with a validated MT5 broker."""
    def __init__(self, spec: InstrumentSpec, *, now: datetime | None = None):
        self.spec=spec
        self.account=Account(environment='demo',alias='synthetic-demo',server='fake',currency='USD',
                             equity=1000.,balance=1000.,margin=0.,free_margin=1000.,cash_flow_verified=True)
        self.quote=Quote(symbol=spec.symbol,bid=1500.,ask=1500.3,timestamp=now or datetime.now(timezone.utc))
        self.positions: dict[str,Position]={}
        self.orders: dict[str,OrderResult]={}
        self.fault=None
        self.connected=True
        self.submissions=0

    def health_check(self):
        return self.connected

    def get_account(self):
        if not self.connected:
            raise ConnectionError('fake disconnected')
        return self.account

    def get_instrument_spec(self,symbol):
        if symbol!=self.spec.symbol:
            raise ValueError('symbol mapping mismatch')
        return self.spec

    def get_quote(self,symbol):
        self.get_instrument_spec(symbol)
        return self.quote

    def get_positions(self):
        self.get_account()
        return list(self.positions.values())

    def get_open_orders(self):
        return [order for order in self.orders.values() if order.state in ('accepted','partial')]

    def find_order(self,identifier):
        self.get_account()
        return self.orders.get(identifier)

    def calculate_margin(self,order):
        return order.lots*self.spec.margin_per_lot

    def place_order(self,order):
        self.submissions+=1
        if self.fault=='reject':
            result=OrderResult(client_order_id=order.client_order_id,symbol=order.symbol,state='rejected')
        elif self.fault=='unknown_before':
            raise TimeoutError('fake transport timeout before acceptance')
        else:
            lots=order.lots / 2 if self.fault=='partial' else order.lots
            position_id='position-'+order.client_order_id
            position=Position(position_id=position_id,client_order_id=order.client_order_id,
                              symbol=order.symbol,side=order.side,lots=lots,entry_price=order.reference_price,
                              stop_loss=None if self.fault=='missing_stop' else order.stop_loss)
            self.positions[position_id]=position
            result=OrderResult(client_order_id=order.client_order_id,symbol=order.symbol,state='partial' if self.fault=='partial' else 'filled',
                               filled_lots=lots,broker_order_id='order-'+order.client_order_id,position_id=position_id)
        self.orders[order.client_order_id]=result
        if self.fault=='timeout_after_fill':
            raise TimeoutError('fake transport timeout after acceptance')
        return result

    def cancel_order(self,identifier):
        prior=self.orders[identifier]
        result=prior.model_copy(update={'state':'cancelled'})
        self.orders[identifier]=result
        return result

    def close_position(self,identifier):
        if self.fault=='close_timeout':
            raise TimeoutError('fake close uncertainty')
        self.positions.pop(identifier,None)
