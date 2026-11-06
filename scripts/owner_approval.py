#!/usr/bin/env python3
"""Owner-only offline key/sign/preview/revoke workflow. Live activation is always disabled."""
import argparse
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from qarevin.approval import ApprovalVerifier, CandidateReport, DisabledLiveController, issue, public_key_id
from qarevin.artifacts import read_artifact
from qarevin.domain import canonical_json
from qarevin.evidence import EvidenceStore

ROOT=Path(__file__).resolve().parents[1]


def owner_path(path: Path):
    if path.resolve().is_relative_to(ROOT):
        raise ValueError('owner keys/approval state/tokens must be outside the repository and research mounts')
    if path.resolve()!=path.absolute():
        raise ValueError('owner paths must not traverse symlinks')
    directory=path if path.is_dir() else path.parent
    for parent in (directory,*directory.parents):
        if parent.exists():
            mode=parent.stat().st_mode
            if mode & 0o022 and not mode & stat.S_ISVTX:
                raise ValueError('owner material has an untrusted writable parent directory')
    for name in ('QAREVIN_STATE_DIR','QAREVIN_STATE','QAREVIN_DATA_DIR','QAREVIN_DATASETS','QAREVIN_HERMES_HOME'):
        root=os.environ.get(name)
        if root and path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError('owner material must be outside configured research/data/Hermes mounts')
    return path


def public_read(path: Path):
    owner_path(path)
    if path.is_symlink() or path.stat().st_mode & 0o022 or path.stat().st_size>16384:
        raise ValueError('public-key file must be bounded, non-symlink and not group/other writable')
    return path.read_bytes()


def owner_state(path: Path):
    owner_path(path)
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.stat().st_mode & 0o077:
        raise ValueError('approval state directory must be owner-only')
    return EvidenceStore(path/'approvals.sqlite')


def private_read(path: Path,limit=16384):
    owner_path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size>limit:
        raise ValueError('private file must be owner-only, bounded and non-symlink')
    return path.read_bytes()


def exclusive_write(path: Path,body: bytes,mode=0o600):
    owner_path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    generate=sub.add_parser('keygen')
    generate.add_argument('--directory',type=Path,required=True)
    generate.add_argument('--state',type=Path,required=True)
    for command in ('sign','preview'):
        action=sub.add_parser(command)
        action.add_argument('--packet',type=Path,required=True)
        action.add_argument('--state',type=Path,required=True)
        action.add_argument('--key',type=Path,required=True)
        action.add_argument('--token',type=Path,required=True,help='sign output or preview input (never printed)')
        if command=='sign':
            action.add_argument('--ttl-seconds',type=int,default=600)
    revoke=sub.add_parser('revoke')
    revoke.add_argument('--state',type=Path,required=True)
    revoke.add_argument('--public-key',type=Path,required=True)
    revoke.add_argument('--authorization-id',required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    if args.command=='keygen':
        directory=owner_path(args.directory)
        if (directory/'owner.private.pem').exists() or (directory/'owner.public.pem').exists():
            raise ValueError('refusing existing approval key paths')
        key=Ed25519PrivateKey.generate()
        state=owner_state(args.state)
        state.put('approval_trust_root',{'key_id':public_key_id(key.public_key())},identity='owner')
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        exclusive_write(directory/'owner.private.pem',private)
        exclusive_write(directory/'owner.public.pem',public,0o644)
        print(canonical_json({'public_key_fingerprint':public_key_id(key.public_key()),'private_key_printed':False}))
        return
    state=owner_state(args.state)
    if args.command=='revoke':
        public=serialization.load_pem_public_key(public_read(args.public_key))
        if not isinstance(public,Ed25519PublicKey):
            raise ValueError('Ed25519 public key required')
        ApprovalVerifier(public,state,expected_fingerprint=state.get('approval_trust_root','owner')['key_id']).revoke(args.authorization_id)
        print(canonical_json({'status':'revoked','authorization_id':args.authorization_id,'activation_performed':False}))
        return
    packet=CandidateReport.model_validate_json(canonical_json(read_artifact(args.packet)['candidate_report']))
    if packet.missing(now):
        print(canonical_json({'status':'blocked','missing':packet.missing(now),'activation_performed':False}))
        raise SystemExit(2)
    if args.command=='sign':
        key=serialization.load_pem_private_key(private_read(args.key),password=None)
        if not isinstance(key,Ed25519PrivateKey):
            raise ValueError('Ed25519 owner key required')
        token=issue(packet,key,now,ttl_seconds=args.ttl_seconds)
        verifier=ApprovalVerifier(key.public_key(),state,expected_fingerprint=state.get('approval_trust_root','owner')['key_id'])
        claims=verifier.verify(token,packet.scope(),now)
        state.put('approval_issued',claims.model_dump())
        exclusive_write(args.token,token.encode())
        print(canonical_json({'authorization_id':claims.authorization_id,'expires_at':claims.expires_at,
                              'token_printed':False,'activation_performed':False}))
    else:
        public=serialization.load_pem_public_key(public_read(args.key))
        if not isinstance(public,Ed25519PublicKey):
            raise ValueError('Ed25519 public key required')
        result=DisabledLiveController(ApprovalVerifier(public,state,expected_fingerprint=state.get('approval_trust_root','owner')['key_id'])).prepare(packet,private_read(args.token).decode(),now)
        print(json.dumps(result))


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,KeyError,PermissionError) as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}))
        raise SystemExit(2) from None
