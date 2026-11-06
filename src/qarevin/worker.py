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
    job = None
    child_error = None
    try:
        job = service.lease(worker_id)
        if job is None:
            return None
        body = json.loads(job['body'])
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
                        service.renew(job['id'], worker_id)
                        time.sleep(1)
                    if process.returncode:
                        failure = scratch / 'failure.json'
                        if failure.exists() and failure.stat().st_size < 1024:
                            value = json.loads(failure.read_text()).get('error_type', '')
                            if value.isalnum() and len(value) < 100:
                                child_error = 'Child_' + value
                        service.store.audit('worker_process_failed', {'job_id': job['id'], 'returncode': process.returncode, 'child_error': child_error})
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
            if body['kind'] == 'walk_forward':
                report = result['walk_forward']
                report['execution_evidence'] = 'diagnostic child-computed; full-history and continuous-risk replay pending'
                for index, fold in enumerate(report.get('folds', [])):
                    fold['scorecard'] = evaluate(fold['result'], service.config, evidence_kind='walk_forward')
                    service.store.put('job_fold_result', {'job_id': job['id'], 'index': index, 'fold': fold['fold'],
                                      'scorecard': fold['scorecard']}, identity=job['id'] + ':' + str(index))
                report['promotion_ready'] = False
            result['manifest'] = body
            service.finish(job['id'], worker_id, result=result)
    except Exception as exc:
        if job is None:
            return {'status': 'retry_later', 'error_type': type(exc).__name__}
        try:
            current = service.job(job['id'])
            if current['state'] == 'running' and current['worker_id'] == worker_id:
                service.finish(job['id'], worker_id, error_type=child_error or type(exc).__name__)
        except Exception as recovery:
            return {'status': 'retry_later', 'job_id': job['id'], 'error_type': type(recovery).__name__}
    try:
        return service.job(job['id'])
    except Exception as exc:
        return {'status': 'retry_later', 'job_id': job['id'], 'error_type': type(exc).__name__}
