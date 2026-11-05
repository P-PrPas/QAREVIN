"""Owner-controlled SQLite registry. Candidate processes never receive this handle."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class Registry:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO schema_migrations VALUES(1);
            CREATE TABLE IF NOT EXISTS audit(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL
            );
        ''')
        self.db.commit()

    def backup(self, destination: Path) -> None:
        with sqlite3.connect(destination) as target:
            self.db.backup(target)

    def close(self) -> None:
        self.db.close()
