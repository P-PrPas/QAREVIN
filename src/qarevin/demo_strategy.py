"""Pinned causal signal-to-demo connection; owner supplies normalized closed broker bars."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from qarevin.broker import Signal
from qarevin.domain import digest, source_identity
from qarevin.execution import DemoRunner, SafetyStop
from qarevin.strategies import StrategySpec, signals


class DemoStrategy:
    def __init__(self,runner: DemoRunner,strategy: StrategySpec):
        self.runner,self.strategy=runner,strategy
        self.identity=digest({'strategy':strategy.model_dump(),'source_hash':source_identity(),
                              'config_hash':digest(runner.config)})
        if runner.strategy_hash!=self.identity:
            raise SafetyStop('strategy artifact/config/source identity mismatch')

    def tick(self,closed_m1: pd.DataFrame,now: datetime):
        if now.tzinfo is None:
            raise SafetyStop('aware current time required')
        if closed_m1.empty or closed_m1.index.max()+pd.Timedelta(minutes=1)>pd.Timestamp(now):
            raise SafetyStop('future or incomplete bars')
        if self.identity!=digest({'strategy':self.strategy.model_dump(),'source_hash':source_identity(),
                                  'config_hash':digest(self.runner.config)}):
            raise SafetyStop('pinned runtime changed')
        state=self.runner.watchdog(now)
        if state['mode']!='active':
            return {'status':state['mode']}
        decisions=signals(closed_m1,self.strategy)
        if decisions.empty:
            return {'status':'no_signal'}
        timestamp=decisions.index[-1]
        decision=decisions.iloc[-1]
        identifier=digest({'strategy_hash':self.identity,'signal_time':timestamp.isoformat()})
        try:
            self.runner.store.get('signal_seen',identifier)
            return {'status':'already_seen','signal_id':identifier}
        except KeyError:
            pass
        positions=self.runner.broker.get_positions()
        direction=int(decision.side)
        if positions and (direction==0 or direction!=positions[0].side):
            self.runner.flatten_known_positions()
        self.runner.store.put('signal_seen',{'available_at':timestamp.isoformat(),'side':direction},identity=identifier)
        age=(pd.Timestamp(now)-timestamp).total_seconds()
        if direction and 0<=age<60 and not self.runner.broker.get_positions():
            return self.runner.submit(Signal(signal_id=identifier,side=direction,stop_distance=float(decision.stop_distance)),now)
        return {'status':'exit_or_expired','signal_id':identifier}
