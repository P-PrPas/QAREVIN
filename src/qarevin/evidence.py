"""Append-only evidence, lineage and tamper-evident audit with serialized transactions."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from qarevin.domain import canonical_json, digest, utc_now
from qarevin.registry import Registry


class EvidenceStore:
    def __init__(self, path: Path):
        self.path = path
        Registry(path).close()
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS objects(
                    kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(kind,id)
                );
                CREATE TABLE IF NOT EXISTS audit_ledger(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS objects_no_update BEFORE UPDATE ON objects
                    BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
                CREATE TRIGGER IF NOT EXISTS objects_no_delete BEFORE DELETE ON objects
                    BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_ledger
                    BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_ledger
                    BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
                INSERT OR IGNORE INTO schema_migrations VALUES(2);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, event: str, payload: dict, *, db=None) -> None:
        if db is None:
            with self.transaction() as connection:
                self.audit(event, payload, db=connection)
            return
        last = db.execute('SELECT entry_hash FROM audit_ledger ORDER BY sequence DESC LIMIT 1').fetchone()
        previous = last[0] if last else '0' * 64
        timestamp, encoded = utc_now(), canonical_json(payload)
        current = digest({'timestamp': timestamp, 'event': event, 'payload': payload, 'previous_hash': previous})
        db.execute('INSERT INTO audit_ledger(timestamp,event,payload,previous_hash,entry_hash) VALUES(?,?,?,?,?)',
                   (timestamp, event, encoded, previous, current))

    def put(self, kind: str, body: dict, *, identity: str | None = None, db=None) -> str:
        identifier, encoded = identity or digest(body), canonical_json(body)
        if db is None:
            with self.transaction() as connection:
                return self.put(kind, body, identity=identifier, db=connection)
        prior = db.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if prior:
            if prior[0] != encoded:
                raise ValueError('immutable evidence identity conflict')
            return identifier
        db.execute('INSERT INTO objects VALUES(?,?,?,?)', (kind, identifier, encoded, utc_now()))
        self.audit('registered', {'kind': kind, 'id': identifier, 'body_hash': digest(body)}, db=db)
        return identifier

    def get(self, kind: str, identifier: str) -> dict:
        with self.transaction() as db:
            row = db.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if row is None:
            raise KeyError('evidence not found')
        return json.loads(row[0])

    def list(self, kind: str, *, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError('limit out of range')
        with self.transaction() as db:
            rows = db.execute('SELECT id,body,created_at FROM objects WHERE kind=? ORDER BY created_at DESC,id LIMIT ?', (kind, limit)).fetchall()
        return [{'id': row['id'], 'body': json.loads(row['body']), 'created_at': row['created_at']} for row in rows]

    def verify_audit(self) -> bool:
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM audit_ledger ORDER BY sequence').fetchall()
        previous = '0' * 64
        for row in rows:
            value = {'timestamp': row['timestamp'], 'event': row['event'], 'payload': json.loads(row['payload']), 'previous_hash': previous}
            if row['previous_hash'] != previous or row['entry_hash'] != digest(value):
                return False
            previous = row['entry_hash']
        return True

    def backup(self, destination: Path) -> None:
        registry = Registry(self.path)
        try:
            registry.backup(destination)
        finally:
            registry.close()
