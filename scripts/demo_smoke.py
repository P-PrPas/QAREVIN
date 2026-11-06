#!/usr/bin/env python3
"""Synthetic execution fault smoke only; this script cannot choose a real broker adapter."""
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from qarevin.artifacts import write_artifact
from qarevin.broker import FakeBroker, Signal
from qarevin.domain import digest, load_config
from qarevin.execution import DemoRunner, SafetyStop

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
base=load_config(Path(__file__).parents[1]/'config/research.example.json')
config=base.model_copy(update={name:getattr(base,name).model_copy(update={'verified':True}) for name in ('instrument','costs','session')})
now=datetime(2026,11,5,12,tzinfo=timezone.utc)
broker=FakeBroker(config.instrument,now=now)
with tempfile.TemporaryDirectory(prefix='qarevin-fake-demo-') as temp:
    with DemoRunner(Path(temp)/'demo.sqlite',broker,config,strategy_hash='a'*64,
                    account_alias='synthetic-demo',server='fake') as runner:
        runner.start_demo(now)
        broker.fault='timeout_after_fill'
        signal=Signal(signal_id=digest({'smoke':1}),side=1,stop_distance=1.)
        try:
            runner.submit(signal,now)
        except SafetyStop:
            pass
        duplicate=runner.submit(signal,now)
        reconciled=runner.reconcile(now)
        runner.pause(flatten=True)
        report={'synthetic':True,'real_broker_validated':False,'forward_months':0,
                'timeout_duplicate_prevented':duplicate['duplicate'] and broker.submissions==1,
                'reconciled':reconciled['mode']=='active','flatten_confirmed':not broker.get_positions(),
                'audit_valid':runner.store.verify_audit(),'live_enabled':False}
        assert all(report[name] for name in ('timeout_duplicate_prevented','reconciled','flatten_confirmed','audit_valid'))
        print(write_artifact(args.output,report))
