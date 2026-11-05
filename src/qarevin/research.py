"""Scoped preregistration and durable, bounded parameter-only research jobs."""
from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import Field

from qarevin.catalog import ResearchCatalog
from qarevin.domain import Contract, ResearchConfig, canonical_json, digest, source_identity, utc_now
from qarevin.evidence import EvidenceStore
from qarevin.strategies import StrategySpec
from qarevin.walkforward import Fold


class Hypothesis(Contract):
    statement: str = Field(min_length=10, max_length=2000)
    expected_effect: str = Field(min_length=5, max_length=1000)
    stopping_criterion: str = Field(min_length=5, max_length=1000)
    max_trials: int = Field(default=5, ge=1, le=20)


class Candidate(Contract):
    hypothesis_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    strategy: StrategySpec
    parent_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    change_summary: str = Field(min_length=5, max_length=1000)


class JobRequest(Contract):
    candidate_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    dataset_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    kind: Literal['backtest', 'walk_forward'] = 'backtest'
    folds: list[Fold] = Field(default_factory=list)


class Observation(Contract):
    experiment_id: str
    observation: str = Field(min_length=5, max_length=2000)
    alternative_explanations: list[str] = Field(min_length=1, max_length=5)
    next_test: str = Field(min_length=5, max_length=1000)
    confidence: Literal['low', 'medium', 'high'] = 'low'


class BudgetExceeded(ValueError):
    pass


class DuplicateExperiment(ValueError):
    pass


class ResearchService:
    def __init__(self, store: EvidenceStore, catalog: ResearchCatalog, config: ResearchConfig):
        self.store, self.catalog, self.config = store, catalog, config
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    fingerprint TEXT UNIQUE NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, lease_until REAL, worker_id TEXT,
                    result_id TEXT, error_type TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO schema_migrations VALUES(3);
            ''')

    def propose(self, hypothesis: Hypothesis) -> str:
        return self.store.put('hypothesis', hypothesis.model_dump(mode='json'))

    def submit(self, candidate: Candidate) -> str:
        self.store.get('hypothesis', candidate.hypothesis_id)
        if candidate.parent_id:
            self.store.get('candidate', candidate.parent_id)
        return self.store.put('candidate', candidate.model_dump(mode='json') | {'source_hash': source_identity()})

    def enqueue(self, request: JobRequest, request_key: str) -> dict:
        if not 8 <= len(request_key) <= 128:
            raise ValueError('idempotency key length must be 8..128')
        candidate = self.store.get('candidate', request.candidate_id)
        hypothesis = self.store.get('hypothesis', candidate['hypothesis_id'])
        if candidate['source_hash'] != source_identity():
            raise ValueError('candidate code changed; register a new version')
        directory = self.catalog.directory(request.dataset_id)
        from qarevin.data import read_manifest
        dataset_manifest = read_manifest(directory)
        self.store.put('dataset', dataset_manifest, identity=request.dataset_id)
        if dataset_manifest['rows'] > 250_000:
            raise ValueError('initial worker dataset cap is 250000 M1 rows; owner must partition input')
        if request.kind == 'walk_forward' and (not request.folds or len(request.folds) > 12):
            raise ValueError('walk-forward requires 1..12 preregistered folds')
        if request.kind == 'backtest' and request.folds:
            raise ValueError('backtest has no fold parameter')
        body = request.model_dump(mode='json') | {'config_hash': digest(self.config), 'source_hash': source_identity()}
        spec = StrategySpec.model_validate(candidate['strategy'])
        semantic = {'family': spec.family}
        if spec.family != 'no_trade':
            semantic['stop_atr'] = spec.stop_atr
        if spec.family == 'trend':
            semantic.update(fast=spec.fast, slow=spec.slow)
        if spec.family == 'random':
            semantic['seed'] = spec.seed
        fingerprint = digest({key: value for key, value in body.items() if key != 'candidate_id'} | {'strategy': semantic})
        now = utc_now()
        with self.store.transaction() as db:
            prior = db.execute('SELECT * FROM jobs WHERE request_key=?', (request_key,)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise ValueError('idempotency key reused with different inputs')
                return dict(prior)
            duplicate = db.execute('SELECT id FROM jobs WHERE fingerprint=?', (fingerprint,)).fetchone()
            if duplicate:
                raise DuplicateExperiment('identical experiment already registered')
            daily = db.execute('SELECT COUNT(*) FROM jobs WHERE substr(created_at,1,10)=?', (now[:10],)).fetchone()[0]
            count = db.execute('SELECT COUNT(*) FROM jobs WHERE json_extract(body,\'$.candidate_id\') IN (SELECT id FROM objects WHERE kind=\'candidate\' AND json_extract(body,\'$.hypothesis_id\')=?)', (candidate['hypothesis_id'],)).fetchone()[0]
            if daily >= self.config.daily_experiments or count >= hypothesis['max_trials']:
                raise BudgetExceeded('research experiment budget exhausted')
            identifier = uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,request_key,fingerprint,body,state,created_at) VALUES(?,?,?,?,?,?)',
                       (identifier, request_key, fingerprint, canonical_json(body), 'queued', now))
            self.store.audit('job_queued', {'job_id': identifier, 'candidate_id': request.candidate_id,
                                           'dataset_id': request.dataset_id, 'fingerprint': fingerprint}, db=db)
        return self.job(identifier)

    def job(self, identifier: str) -> dict:
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError('job not found')
        return dict(row)

    def cancel(self, identifier: str) -> dict:
        with self.store.transaction() as db:
            row = db.execute('SELECT state FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise KeyError('job not found')
            if row[0] == 'queued':
                db.execute("UPDATE jobs SET state='cancelled',cancel_requested=1 WHERE id=?", (identifier,))
            elif row[0] == 'running':
                db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?', (identifier,))
            self.store.audit('job_cancel_requested', {'job_id': identifier}, db=db)
        return self.job(identifier)

    def lease(self, worker_id: str) -> dict | None:
        now = time.time()
        with self.store.transaction() as db:
            expired = db.execute("SELECT id FROM jobs WHERE state='running' AND lease_until<?", (now,)).fetchall()
            for row in expired:
                db.execute("UPDATE jobs SET state='failed',error_type='LeaseExpired' WHERE id=?", (row[0],))
                self.store.audit('job_failed', {'job_id': row[0], 'error_type': 'LeaseExpired'}, db=db)
            if db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                return None
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running',worker_id=?,lease_until=? WHERE id=? AND state='queued'",
                       (worker_id, now + self.config.job_timeout_seconds + 30, row['id']))
            self.store.audit('job_started', {'job_id': row['id'], 'worker_id': worker_id}, db=db)
            identifier = row['id']
        return self.job(identifier)

    def finish(self, identifier: str, worker_id: str, *, result: dict | None = None, error_type: str | None = None) -> None:
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None or row['state'] != 'running' or row['worker_id'] != worker_id:
                raise ValueError('job lease no longer owned')
            if row['cancel_requested']:
                state, result_id = 'cancelled', None
            elif result is not None:
                state = 'succeeded'
                result_id = self.store.put('job_result', result, identity=identifier, db=db)
            else:
                state, result_id = ('timed_out' if error_type == 'TimeoutExpired' else 'failed'), None
            db.execute('UPDATE jobs SET state=?,result_id=?,error_type=?,lease_until=NULL WHERE id=?',
                       (state, result_id, error_type, identifier))
            self.store.audit('job_' + state, {'job_id': identifier, 'result_id': result_id, 'error_type': error_type}, db=db)

    def remember(self, memory: Observation) -> str:
        job = self.job(memory.experiment_id)
        if job['state'] != 'succeeded':
            raise ValueError('memory requires a completed experiment')
        return self.store.put('memory', memory.model_dump(mode='json'))

    def lineage(self, identifier: str) -> list[dict]:
        result, visited = [], set()
        while identifier:
            if identifier in visited or len(result) >= 100:
                raise ValueError('invalid lineage')
            visited.add(identifier)
            candidate = self.store.get('candidate', identifier)
            result.append({'id': identifier, **candidate})
            identifier = candidate.get('parent_id')
        return result
