"""Trusted job controller; child runs only installed parameterized strategies, never source text."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from qarevin.domain import canonical_json, digest, source_identity
from qarevin.evaluation import evaluate
from qarevin.research import ResearchService
from qarevin.resources import preflight


def run_one(service: ResearchService, *, worker_id: str = 'local-worker', memory_mib: int = 768,
            check_headroom: bool = True) -> dict | None:
    if check_headroom and not preflight(memory_mib, service.config.memory_reserve_mib)['ready']:
        return {'status': 'deferred', 'reason': 'insufficient_memory'}
    job = service.lease(worker_id)
    if job is None:
        return None
    body = json.loads(job['body'])
    try:
        if body['source_hash'] != source_identity() or body['config_hash'] != digest(service.config):
            raise ValueError('queued code/config no longer matches')
        candidate = service.store.get('candidate', body['candidate_id'])
        dataset = service.catalog.directory(body['dataset_id'])
        from qarevin.experiments import snapshot_sources
        source = snapshot_sources(service.store.path.parent / 'artifacts/source')
        service.store.put('job_inputs', {'request': body, 'source': source,
                          'config': service.config.model_dump(mode='json'), 'strategy': candidate['strategy']}, identity=job['id'])
        with tempfile.TemporaryDirectory(prefix='qarevin-job-') as directory:
            scratch = Path(directory)
            request = {'dataset': str(dataset), 'strategy': candidate['strategy'],
                       'config': service.config.model_dump(mode='json'), 'kind': body['kind'], 'folds': body['folds']}
            (scratch / 'request.json').write_text(canonical_json(request))
            environment = {'PATH': os.defpath, 'HOME': directory, 'OPENBLAS_NUM_THREADS': '1',
                           'OMP_NUM_THREADS': '1', 'PYTHONPATH': str(Path(__file__).parent.parent)}
            command = [sys.executable, '-m', 'qarevin.job_worker', str(scratch), str(memory_mib),
                       str(service.config.job_timeout_seconds)]
            with (scratch / 'stderr.log').open('w') as errors:
                process = subprocess.Popen(command, env=environment, cwd=scratch, stdout=subprocess.DEVNULL,
                                           stderr=errors, start_new_session=True)
                deadline = time.monotonic() + service.config.job_timeout_seconds
                try:
                    while process.poll() is None:
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(command, service.config.job_timeout_seconds)
                        if service.job(job['id'])['cancel_requested']:
                            process.kill()
                            process.wait()
                            service.finish(job['id'], worker_id, error_type='Cancelled')
                            return service.job(job['id'])
                        time.sleep(.1)
                    if process.returncode:
                        raise RuntimeError('bounded worker failed')
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
            result_path = scratch / 'result.json'
            if result_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('worker output too large')
            result = json.loads(result_path.read_text())
            if body['kind'] == 'backtest':
                # Recalculate the scorecard in this trusted parent; no candidate pass flags accepted.
                result['scorecard'] = evaluate(result['result'], service.config)
            result['manifest'] = body
            service.finish(job['id'], worker_id, result=result)
    except Exception as exc:
        service.finish(job['id'], worker_id, error_type=type(exc).__name__)
    return service.job(job['id'])
