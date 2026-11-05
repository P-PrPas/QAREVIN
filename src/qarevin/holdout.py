"""Owner-only sealed evaluation. This module has no agent tool or control API route."""
from pathlib import Path

from qarevin.backtest import run_backtest
from qarevin.data import load_dataset, read_manifest
import pandas as pd
from qarevin.domain import ResearchConfig, digest, source_identity
from qarevin.evaluation import evaluate, EvaluationProtocol
from qarevin.evidence import EvidenceStore
from qarevin.strategies import StrategySpec


class HoldoutService:
    def __init__(self, owner_store: EvidenceStore, holdout_root: Path, research_root: Path):
        self.store = owner_store
        self.root = holdout_root.resolve()
        research = research_root.resolve()
        if self.root == research or research in self.root.parents or self.root in research.parents:
            raise ValueError('holdout and research stores must be disjoint')

    def preregister(self, campaign: str, dataset_id: str, config: ResearchConfig, strategy: StrategySpec) -> str:
        if not campaign.strip():
            raise ValueError('campaign required')
        return self.store.put('holdout_campaign', {'campaign': campaign, 'config_hash': digest(config),
                              'strategy_hash': digest(strategy), 'source_hash': source_identity(), 'dataset_id': dataset_id,
                              'evaluation_protocol_hash': digest(EvaluationProtocol())}, identity=campaign)

    def evaluate_once(self, campaign: str, dataset_id: str, config: ResearchConfig, strategy: StrategySpec) -> dict:
        expected = self.store.get('holdout_campaign', campaign)
        if expected['dataset_id'] != dataset_id or expected['evaluation_protocol_hash'] != digest(EvaluationProtocol()) or expected['config_hash'] != digest(config) or expected['strategy_hash'] != digest(strategy) or expected['source_hash'] != source_identity():
            raise PermissionError('frozen campaign mismatch')
        if len(dataset_id) != 64 or any(c not in '0123456789abcdef' for c in dataset_id):
            raise ValueError('invalid dataset ID')
        # A durable opening consumes this campaign even if data is missing or the evaluator crashes.
        with self.store.transaction() as db:
            if db.execute('SELECT 1 FROM objects WHERE kind=? AND id=?', ('holdout_access', campaign)).fetchone():
                raise PermissionError('holdout campaign already consumed')
            if db.execute('SELECT 1 FROM objects WHERE kind=? AND id=?', ('holdout_dataset_access', dataset_id)).fetchone():
                raise PermissionError('holdout dataset already consumed')
            self.store.put('holdout_dataset_access', {'campaign': campaign, 'status': 'consumed'}, identity=dataset_id, db=db)
            self.store.put('holdout_access', {'campaign': campaign, 'dataset_id': dataset_id,
                                             'status': 'consumed'}, identity=campaign, db=db)
        directory = self.root / dataset_id
        try:
            if directory.is_symlink() or directory.resolve().parent != self.root:
                raise ValueError('holdout path escape')
            manifest = read_manifest(directory)
            if pd.Timestamp(manifest['start']) < pd.Timestamp('2025-01-01T00:00:00Z'):
                raise PermissionError('holdout overlaps development history')
            result = run_backtest(load_dataset(directory), config, strategy)
            report = evaluate(result, config, evidence_kind='holdout')
            self.store.put('holdout_result', report, identity=campaign)
            return report
        except Exception as exc:
            self.store.audit('holdout_failed', {'campaign': campaign, 'error_type': type(exc).__name__})
            raise
