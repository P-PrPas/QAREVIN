"""Secured demo bridge client contract. Actual MT5 terminal server must be validated separately."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import httpx
from pydantic import Field, model_validator

from qarevin.broker import Account, Order, OrderResult, Position, Quote
from qarevin.domain import Contract, InstrumentSpec, canonical_json, unique_json


class Positions(Contract):
    positions: list[Position] = Field(max_length=100)


class Orders(Contract):
    orders: list[OrderResult] = Field(max_length=100)


class Find(Contract):
    found: bool
    order: OrderResult | None = None

    @model_validator(mode='after')
    def consistent(self):
        if self.found != (self.order is not None):
            raise ValueError('inconsistent order lookup')
        return self


class Health(Contract):
    connected: bool


class CloseResult(Contract):
    closed: bool


class HTTPDemoAdapter:
    def __init__(self,url: str,token: str,*,account_alias: str,server: str,symbol: str,
                 broker_symbol: str | None = None,transport=None):
        parsed=urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or len(token)<32:
            raise ValueError('dedicated bridge URL and token required')
        if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):
            raise ValueError('bridge requires HTTPS except loopback tests')
        for name in (symbol,broker_symbol or symbol):
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name):
                raise ValueError('invalid symbol mapping')
        self.symbol,self.broker_symbol=symbol,broker_symbol or symbol
        self.http=httpx.Client(base_url=url.rstrip('/'),headers={'Authorization':'Bearer '+token,
              'X-Qarevin-Environment':'demo','X-Qarevin-Account':account_alias,'X-Qarevin-Server':server},
              timeout=10,transport=transport,follow_redirects=False,trust_env=False)

    def _request(self,method,path,body=None):
        with self.http.stream(method,'/v1/'+path,json=body) as response:
            if not response.is_success:
                raise ConnectionError(f'bridge_status_{response.status_code}')
            chunks,size=[],0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>1024*1024:
                    raise ValueError('bridge response exceeds limit')
                chunks.append(chunk)
        return unique_json(b''.join(chunks).decode())

    def _symbol(self,symbol):
        if symbol!=self.symbol:
            raise ValueError('unexpected normalized symbol')
        return quote(self.broker_symbol,safe='')

    def get_account(self):
        return Account.model_validate_json(canonical_json(self._request('GET','account')))

    def get_instrument_spec(self,symbol):
        spec=InstrumentSpec.model_validate_json(canonical_json(self._request('GET','instruments/'+self._symbol(symbol))))
        if spec.symbol!=self.broker_symbol:
            raise ValueError('bridge symbol spec mismatch')
        return spec.model_copy(update={'symbol':self.symbol})

    def get_quote(self,symbol):
        result=Quote.model_validate_json(canonical_json(self._request('GET','quotes/'+self._symbol(symbol))))
        if result.symbol!=self.broker_symbol:
            raise ValueError('bridge quote symbol mismatch')
        return result.model_copy(update={'symbol':self.symbol})

    def get_positions(self):
        rows=Positions.model_validate_json(canonical_json(self._request('GET','positions'))).positions
        return [position.model_copy(update={'symbol':self.symbol}) if position.symbol==self.broker_symbol else position.model_copy(update={'symbol':'UNMAPPED:'+position.symbol}) for position in rows]

    def get_open_orders(self):
        return Orders.model_validate_json(canonical_json(self._request('GET','orders'))).orders

    def find_order(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{64}',identifier):
            raise ValueError('invalid client order ID')
        return Find.model_validate_json(canonical_json(self._request('GET','orders/'+identifier))).order

    def place_order(self,order: Order):
        self._symbol(order.symbol)
        outgoing=order.model_copy(update={'symbol':self.broker_symbol})
        return OrderResult.model_validate_json(canonical_json(self._request('POST','orders',outgoing.model_dump(mode='json'))))

    def cancel_order(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{64}',identifier):
            raise ValueError('invalid client order ID')
        return OrderResult.model_validate_json(canonical_json(self._request('POST','orders/'+identifier+'/cancel')))

    def close_position(self,identifier):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identifier):
            raise ValueError('invalid position ID')
        if not CloseResult.model_validate_json(canonical_json(self._request('POST','positions/'+identifier+'/close'))).closed:
            raise ConnectionError('close not confirmed')

    def health_check(self):
        return Health.model_validate_json(canonical_json(self._request('GET','health'))).connected

    def close(self):
        self.http.close()
