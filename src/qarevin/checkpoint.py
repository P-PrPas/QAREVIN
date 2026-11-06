"""Portable research-only checkpoint. Never clones execution risk or approval replay state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from qarevin.domain import canonical_json, file_digest
from qarevin.evidence import EvidenceStore


def _research_only(store: EvidenceStore):
    with store.read() as db:
        forbidden=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('execution_state','intents')").fetchone()
        approvals=db.execute("SELECT 1 FROM objects WHERE kind LIKE 'approval_%' OR kind IN ('deployment_identity','risk_basis_initialized')").fetchone()
    if forbidden or approvals:
        raise ValueError('research checkpoint cannot clone execution/approval state')


def create_checkpoint(registry: Path,artifacts: Path,datasets: Path,destination: Path) -> dict:
    if not registry.is_file() or registry.is_symlink():
        raise ValueError('existing regular research registry required')
    store=EvidenceStore(registry)
    _research_only(store)
    if not store.verify_audit():
        raise ValueError('audit chain invalid')
    for root in (registry.parent,artifacts,datasets):
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError('checkpoint destination must be outside source roots')
    if destination.exists() or destination.is_symlink():
        raise ValueError('checkpoint destination must be new')
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='.checkpoint-',dir=destination.parent)
    os.close(descriptor)
    temp=Path(name)
    try:
        with tempfile.TemporaryDirectory(prefix='qarevin-db-snapshot-') as snapshot:
            backup=Path(snapshot)/'registry.sqlite'
            store.backup(backup)
            paths={'registry.sqlite':backup,'registry.sqlite.anchor.json':backup.with_suffix('.sqlite.anchor.json')}
            for prefix,root in (('artifacts',artifacts),('datasets',datasets)):
                if root.is_symlink():
                    raise ValueError('checkpoint source root must not be a symlink')
                if not root.exists():
                    continue
                for path in sorted(root.rglob('*')):
                    if path.is_symlink():
                        raise ValueError('checkpoint source contains a symlink')
                    if path.is_file():
                        if any(part in ('.env','secrets','hermes-profile') for part in path.relative_to(root).parts):
                            raise ValueError('unexpected private material in research source')
                        paths[prefix+'/'+path.relative_to(root).as_posix()]=path
            manifest={}
            with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
                for relative,path in paths.items():
                    sha,size=hashlib.sha256(),0
                    with path.open('rb') as source,archive.open(relative,'w',force_zip64=True) as target:
                        for chunk in iter(lambda:source.read(1024*1024),b''):
                            sha.update(chunk)
                            size+=len(chunk)
                            target.write(chunk)
                    if file_digest(path)!=sha.hexdigest():
                        raise ValueError('source changed during checkpoint')
                    manifest[relative]={'sha256':sha.hexdigest(),'bytes':size}
                archive.writestr('checkpoint.json',canonical_json({'schema':1,'files':manifest,
                                  'audit_anchor':EvidenceStore(backup).audit_anchor(),'scope':'research_only'}))
        with temp.open('rb') as stream:
            os.fsync(stream.fileno())
        os.link(temp,destination)
        return {'checkpoint':str(destination),'sha256':file_digest(destination),'scope':'research_only','files':len(manifest)}
    finally:
        temp.unlink(missing_ok=True)


def restore_checkpoint(source: Path,destination: Path,*,expected_sha256: str,max_bytes: int = 10*1024**3) -> dict:
    if not re.fullmatch(r'[a-f0-9]{64}',expected_sha256) or file_digest(source)!=expected_sha256:
        raise ValueError('checkpoint external digest mismatch')
    if destination.exists() or destination.is_symlink() or max_bytes<=0:
        raise ValueError('restore destination must be new and size bound positive')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.restore-',dir=destination.parent))
    try:
        with zipfile.ZipFile(source) as archive:
            infos=archive.infolist()
            if len({info.filename for info in infos})!=len(infos) or sum(info.file_size for info in infos)>max_bytes:
                raise ValueError('duplicate members or restore size limit exceeded')
            for info in infos:
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):
                    raise ValueError('unsafe checkpoint path')
                if info.filename not in ('checkpoint.json','registry.sqlite','registry.sqlite.anchor.json') and (not path.parts or path.parts[0] not in ('artifacts','datasets')):
                    raise ValueError('unexpected checkpoint member')
            if archive.getinfo('checkpoint.json').file_size>4*1024*1024:
                raise ValueError('checkpoint manifest too large')
            manifest=json.loads(archive.read('checkpoint.json'))
            if not {'registry.sqlite','registry.sqlite.anchor.json'}<=set(manifest.get('files',{})):
                raise ValueError('checkpoint missing required registry or anchor')
            if manifest.get('scope')!='research_only' or manifest.get('schema')!=1:
                raise ValueError('unsupported checkpoint scope/schema')
            if set(manifest['files'])!={info.filename for info in infos if info.filename!='checkpoint.json'}:
                raise ValueError('checkpoint member manifest mismatch')
            for relative,expected in manifest['files'].items():
                path=temp/relative
                path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                sha,size=hashlib.sha256(),0
                with archive.open(relative) as origin,path.open('xb') as target:
                    path.chmod(0o600)
                    for chunk in iter(lambda:origin.read(1024*1024),b''):
                        size+=len(chunk)
                        if size>expected['bytes']:
                            raise ValueError('checkpoint member size mismatch')
                        sha.update(chunk)
                        target.write(chunk)
                if size!=expected['bytes'] or sha.hexdigest()!=expected['sha256']:
                    raise ValueError('checkpoint member digest mismatch')
        restored=EvidenceStore(temp/'registry.sqlite')
        _research_only(restored)
        if not restored.verify_audit() or restored.audit_anchor()!=manifest['audit_anchor']:
            raise ValueError('checkpoint audit anchor mismatch')
        temp.rename(destination)
        return {'restored':str(destination),'scope':'research_only','audit_anchor':manifest['audit_anchor']}
    finally:
        if temp.exists():
            shutil.rmtree(temp)
