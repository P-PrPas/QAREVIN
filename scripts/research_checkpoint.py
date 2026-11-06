#!/usr/bin/env python3
"""Research-only backup/restore. Live/demo risk and approval ledgers are rejected."""
import argparse
import json
from pathlib import Path

from qarevin.checkpoint import create_checkpoint, restore_checkpoint

parser=argparse.ArgumentParser(description=__doc__)
sub=parser.add_subparsers(dest='command',required=True)
create=sub.add_parser('create')
create.add_argument('--registry',type=Path,required=True)
create.add_argument('--artifacts',type=Path,required=True)
create.add_argument('--datasets',type=Path,required=True)
create.add_argument('--output',type=Path,required=True)
restore=sub.add_parser('restore')
restore.add_argument('source',type=Path)
restore.add_argument('destination',type=Path)
restore.add_argument('--expected-sha256',required=True)
args=parser.parse_args()
if args.command=='create':
    print(json.dumps(create_checkpoint(args.registry,args.artifacts,args.datasets,args.output)))
else:
    print(json.dumps(restore_checkpoint(args.source,args.destination,expected_sha256=args.expected_sha256)))
