"""Atomic content-addressed output; no silent replacement of prior evidence."""
import json
import os
import tempfile
from pathlib import Path

from qarevin.domain import canonical_json, digest


def write_artifact(store: Path, payload: dict) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(payload)
    target = store / (digest(payload) + '.json')
    if target.exists():
        if target.read_text() != encoded:
            raise ValueError('artifact content mismatch')
        return target
    descriptor, name = tempfile.mkstemp(prefix='.artifact-', dir=store)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, target)
    except FileExistsError:
        if target.read_text() != encoded:
            raise ValueError('concurrent artifact mismatch') from None
    finally:
        os.unlink(name)
    return target


def read_artifact(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if path.stem != digest(payload):
        raise ValueError('artifact hash mismatch')
    return payload
