"""Agent-visible dataset catalog cannot resolve arbitrary paths or sealed-tail rows."""
from pathlib import Path

import pandas as pd

from qarevin.data import load_dataset, read_manifest


class ResearchCatalog:
    def __init__(self, root: Path, accessible_before: str = '2025-01-01T00:00:00Z'):
        self.root = root.resolve()
        self.boundary = pd.Timestamp(accessible_before)
        if self.boundary.tz is None:
            raise ValueError('catalog boundary requires explicit timezone')

    def directory(self, dataset_id: str) -> Path:
        if len(dataset_id) != 64 or any(c not in '0123456789abcdef' for c in dataset_id):
            raise ValueError('invalid dataset ID')
        path = self.root / dataset_id
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError('dataset path escape')
        manifest = read_manifest(path)
        if pd.Timestamp(manifest['end']) >= self.boundary:
            raise PermissionError('sealed tail is inaccessible')
        return path

    def list(self) -> list[dict]:
        result = []
        for path in sorted(self.root.glob('*/manifest.json')):
            try:
                directory = self.directory(path.parent.name)
            except (ValueError, PermissionError):
                continue
            manifest = read_manifest(directory)
            result.append({key: manifest[key] for key in ('id', 'provider', 'symbol', 'rows', 'start', 'end', 'qa')})
        return result

    def load(self, dataset_id: str):
        bars = load_dataset(self.directory(dataset_id))
        if bars.index.max() >= self.boundary:
            raise PermissionError('data exceeds declared research boundary')
        return bars
