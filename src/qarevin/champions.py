"""Frozen research baseline and owner-reviewed challenger decisions; no deployment effects."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from qarevin.domain import Contract, digest, utc_now
from qarevin.evidence import EvidenceStore


class EvidenceRef(Contract):
    kind: Literal['job_result','walk_forward_result']
    identifier: str = Field(min_length=1,max_length=128)
    candidate_id: str = Field(pattern=r'^[a-f0-9]{64}$')


class ChampionBook:
    def __init__(self,store: EvidenceStore):
        self.store=store
        with store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS research_champion(id INTEGER PRIMARY KEY CHECK(id=1),candidate_id TEXT NOT NULL,version INTEGER NOT NULL)')

    def current(self):
        with self.store.read() as db:
            row=db.execute('SELECT * FROM research_champion WHERE id=1').fetchone()
        return dict(row) if row else None

    def freeze_baseline(self,candidate_id: str):
        self.store.get('candidate',candidate_id)
        with self.store.transaction() as db:
            existing=db.execute('SELECT candidate_id FROM research_champion WHERE id=1').fetchone()
            if existing and existing[0]!=candidate_id:
                raise ValueError('baseline already frozen; nominate a challenger')
            db.execute('INSERT OR IGNORE INTO research_champion VALUES(1,?,1)',(candidate_id,))
            self.store.put('champion_decision',{'candidate_id':candidate_id,'version':1,'reason':'frozen baseline, not validated profitability'},identity='baseline',db=db)

    def evidence(self,reference: EvidenceRef):
        candidate=self.store.get('candidate',reference.candidate_id)
        body=self.store.get(reference.kind,reference.identifier)
        if reference.kind=='job_result':
            manifest=body['manifest']
            if manifest['source_hash']!=candidate['source_hash']:
                raise ValueError('candidate/source mismatch')
            if manifest['candidate_id']!=reference.candidate_id:
                raise ValueError('candidate/evidence mismatch')
            if 'walk_forward' in body:
                report=body['walk_forward']
                metrics=report['stitched_metrics']
                kind='walk_forward'
                split_hash=report['split_hash']
                dataset_key=report.get('bars_hash',manifest['dataset_id'])
            else:
                metrics=body['scorecard']['metrics']
                kind='backtest'
                split_hash=None
                dataset_key=manifest['dataset_id']
            return {'candidate_id':reference.candidate_id,'metrics':metrics,'kind':kind,'split_hash':split_hash,
                    'dataset_key':dataset_key,'config_hash':manifest['config_hash'],'source_hash':manifest['source_hash']}
        run=self.store.get('walk_forward_run',reference.identifier)
        protocol=self.store.get('walk_forward_protocol',run['protocol_id'])
        if protocol['source_hash']!=candidate['source_hash']:
            raise ValueError('candidate/source mismatch')
        if protocol['candidates']!=[candidate['strategy']] or any(fold['selected']!=candidate['strategy'] for fold in body['folds']):
            raise ValueError('champion evidence requires a fixed strategy artifact')
        return {'candidate_id':reference.candidate_id,'metrics':body['stitched_metrics'],'kind':'walk_forward',
                'split_hash':body['split_hash'],'dataset_key':protocol['bars_hash'],
                'config_hash':protocol['config_hash'],'source_hash':protocol['source_hash']}

    def nominate(self,baseline: EvidenceRef,challenger: EvidenceRef) -> str:
        current=self.current()
        if current is None or current['candidate_id']!=baseline.candidate_id or baseline.candidate_id==challenger.candidate_id:
            raise ValueError('nomination requires the current frozen baseline and a distinct challenger')
        left,right=self.evidence(baseline),self.evidence(challenger)
        for field in ('kind','dataset_key','config_hash','source_hash','split_hash'):
            if left[field]!=right[field]:
                raise ValueError('champion comparison requires matched data, costs, source and folds')
        body={'baseline':baseline.model_dump(),'challenger':challenger.model_dump(),
              'baseline_version':current['version'],'comparison':{'baseline':left,'challenger':right},
              'deployment_authorized':False}
        return self.store.put('champion_nomination',body)

    def accept(self,nomination_id: str,robustness_id: str,*,owner: str,note: str) -> dict:
        if not 1<=len(owner)<=128 or not 10<=len(note)<=2000:
            raise ValueError('authenticated owner and rationale required')
        nomination=self.store.get('champion_nomination',nomination_id)
        robust=self.store.get('robustness_result',robustness_id)
        challenger_id=nomination['challenger']['candidate_id']
        candidate=self.store.get('candidate',challenger_id)
        evidence=nomination['comparison']['challenger']
        if evidence['kind']!='walk_forward' or not robust.get('eligible_for_holdout_request') or robust['target']!=candidate['strategy']:
            raise ValueError('passing fixed-artifact OOS robustness evidence required')
        for field in ('config_hash','source_hash','split_hash','bars_hash'):
            expected=evidence['dataset_key'] if field=='bars_hash' else evidence[field]
            if robust.get(field)!=expected:
                raise ValueError('robustness scope mismatch')
        with self.store.transaction() as db:
            current=db.execute('SELECT * FROM research_champion WHERE id=1').fetchone()
            if current['candidate_id']!=nomination['baseline']['candidate_id'] or current['version']!=nomination['baseline_version']:
                raise ValueError('stale champion nomination')
            version=current['version']+1
            decision={'candidate_id':challenger_id,'version':version,'nomination_id':nomination_id,
                      'robustness_id':robustness_id,'owner':owner,'note':note,'at':utc_now(),
                      'deployment_authorized':False}
            self.store.put('champion_decision',decision,identity=digest(decision),db=db)
            db.execute('UPDATE research_champion SET candidate_id=?,version=? WHERE id=1',(challenger_id,version))
        return decision
