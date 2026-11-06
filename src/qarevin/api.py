"""Agent control API. No endpoint accepts source code, risk policy or broker orders."""
from __future__ import annotations

import asyncio
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from qarevin.catalog import ResearchCatalog
from qarevin.domain import Contract, load_config, unique_json
from qarevin.evidence import EvidenceStore
from qarevin.research import (BudgetExceeded, Candidate, DuplicateExperiment, Hypothesis,
                             JobRequest, Observation, ResearchService)


class QueueBody(Contract):
    request: JobRequest
    idempotency_key: str = Field(min_length=8, max_length=128)


class PromotionRequest(Contract):
    job_id: str = Field(min_length=1, max_length=128)


class CompareRequest(Contract):
    baseline_job_id: str
    challenger_job_id: str


def create_app(service: ResearchService, token: str) -> FastAPI:
    if len(token) < 32:
        raise ValueError('agent token must contain at least 32 characters')
    app = FastAPI(title='Qarevin Research Control', docs_url=None, redoc_url=None, openapi_url=None)
    slots = asyncio.Semaphore(2)
    denied_counts = {}

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + token).encode()):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        if slots.locked():
            return JSONResponse({'error': 'request_limit'}, status_code=429)
        async with slots:
            body, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({'error': 'body_too_large'}, status_code=413)
                body.append(chunk)
            request._body = b''.join(body)
            if request._body:
                try:
                    unique_json(request._body.decode())
                except (ValueError, UnicodeError, RecursionError):
                    return JSONResponse({'error': 'invalid_json'}, status_code=400)
            return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def bad_schema(request, exc):
        return JSONResponse({'error': 'invalid_arguments'}, status_code=422)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        status = 429 if isinstance(exc, BudgetExceeded) else 409 if isinstance(exc, DuplicateExperiment) else 400
        path = getattr(request.scope.get('route'), 'path', request.url.path)
        key = (path, type(exc).__name__)
        import time
        now = time.monotonic()
        if now - denied_counts.get(key, -60) >= 60:
            service.store.audit('request_denied', {'path': path, 'error_type': type(exc).__name__})
            if len(denied_counts) >= 128:
                denied_counts.clear()
            denied_counts[key] = now
        return JSONResponse({'error': type(exc).__name__}, status_code=status)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'error': 'not_found'}, status_code=404)

    @app.exception_handler(PermissionError)
    async def denied(request, exc):
        return JSONResponse({'error': 'forbidden'}, status_code=403)

    @app.get('/api/v1/datasets')
    def datasets():
        return {'datasets': service.catalog.list()}

    @app.post('/api/v1/hypotheses')
    def propose(body: Hypothesis):
        return {'hypothesis_id': service.propose(body)}

    @app.post('/api/v1/candidates')
    def submit(body: Candidate):
        return {'candidate_id': service.submit(body)}

    @app.get('/api/v1/candidates/{identifier}/lineage')
    def lineage(identifier: str):
        return {'lineage': service.lineage(identifier)}

    @app.post('/api/v1/jobs')
    def enqueue(body: QueueBody):
        return service.enqueue(body.request, body.idempotency_key)

    @app.get('/api/v1/jobs/{identifier}')
    def job(identifier: str):
        return service.job(identifier)

    @app.post('/api/v1/jobs/{identifier}/cancel')
    def cancel(identifier: str):
        return service.cancel(identifier)

    @app.get('/api/v1/jobs/{identifier}/result')
    def result(identifier: str):
        job = service.job(identifier)
        if job['state'] != 'succeeded':
            raise ValueError('job not succeeded')
        payload = service.store.get('job_result', identifier)
        answer = {'manifest': payload['manifest']}
        if 'scorecard' in payload:
            result = payload['result']
            answer.update(scorecard=payload['scorecard'], result_hash=result['result_hash'],
                          summary={'trade_count': len(result['trades']), 'final_equity': result['final_equity'],
                                   'lot_feasibility': result['lot_feasibility'], 'limitations': result['limitations']},
                          recent_trades=result['trades'][-20:], recent_equity=result['equity'][-24:])
        else:
            report = payload['walk_forward']
            answer['walk_forward'] = {key: report[key] for key in ('stitched_metrics','split_hash','limitations','promotion_ready') if key in report}
            answer['walk_forward']['folds'] = [{key: fold[key] for key in ('fold','selected','scorecard')} for fold in report.get('folds',[])]
            if report.get('status'):
                answer['walk_forward']['status'] = report['status']
        return answer

    @app.get('/api/v1/memory')
    def memories():
        return {'memories': service.store.list('memory', limit=20)}

    @app.post('/api/v1/memory')
    def remember(body: Observation):
        return {'memory_id': service.remember(body)}

    @app.post('/api/v1/promotions/demo')
    def request_demo(body: PromotionRequest):
        job = service.job(body.job_id)
        if job['state'] != 'succeeded':
            raise ValueError('job not succeeded')
        # Request-only: holdout, broker, risk and owner activation remain separate hard gates.
        identifier = service.bounded_put('promotion_request', {'job_id': body.job_id, 'target': 'demo',
                                      'status': 'blocked', 'missing': ['sealed_evidence', 'broker_validation', 'owner_activation']},10)
        return {'promotion_id': identifier, 'status': 'blocked', 'activated': False}

    @app.post('/api/v1/compare')
    def compare_jobs(body: CompareRequest):
        from qarevin.evaluation import compare
        baseline = result(body.baseline_job_id)
        challenger = result(body.challenger_job_id)
        for field in ('dataset_id', 'config_hash', 'kind', 'source_hash', 'folds'):
            if baseline['manifest'][field] != challenger['manifest'][field]:
                raise ValueError('comparison inputs must match')
        if 'scorecard' not in baseline or 'scorecard' not in challenger:
            raise ValueError('compare currently requires backtest scorecards')
        return compare(baseline['scorecard'], challenger['scorecard'])

    @app.post('/api/v1/registry/candidates')
    def register_evidence(body: PromotionRequest):
        evidence = result(body.job_id)
        identifier = service.bounded_put('candidate_evidence', {'job_id': body.job_id,
                       'scorecard': evidence.get('scorecard'), 'deployment_authorized': False},60)
        return {'evidence_id': identifier, 'deployment_authorized': False}

    @app.post('/api/v1/promotions/live')
    def request_live(body: PromotionRequest):
        result(body.job_id)
        identifier = service.bounded_put('promotion_request', {'job_id': body.job_id, 'target': 'live',
                       'status': 'blocked', 'missing': ['demo_forward', 'capital_policy', 'owner_authorization']},10)
        return {'promotion_id': identifier, 'status': 'blocked', 'activated': False}

    @app.get('/api/v1/status')
    def status():
        return {'environment': 'research', 'arbitrary_code_enabled': False, 'live_enabled': False,
                'walk_forward_mode': 'short-window diagnostic only under current row cap',
                'daily_budget': service.config.daily_experiments, 'job_row_cap': 250000}

    return app


def from_environment() -> FastAPI:
    state = Path(os.environ['QAREVIN_STATE'])
    token_path = Path(os.environ['QAREVIN_AGENT_TOKEN_FILE'])
    if token_path.stat().st_mode & 0o077:
        raise ValueError('token file must be owner-only')
    service = ResearchService(EvidenceStore(state / 'registry.sqlite'),
                              ResearchCatalog(Path(os.environ['QAREVIN_DATASETS'])),
                              load_config(Path(os.environ['QAREVIN_CONFIG'])))
    return create_app(service, token_path.read_text().strip())
