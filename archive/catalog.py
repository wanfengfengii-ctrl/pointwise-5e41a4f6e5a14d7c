from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
import sqlite3


class ArtifactCatalog:
    def __init__(self, path: str | PathLike[str]) -> None:
        self._db = sqlite3.connect(path, isolation_level=None)
        try:
            self._db.execute('PRAGMA foreign_keys = ON')
            self.initialize()
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> 'ArtifactCatalog':
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._db.in_transaction:
            raise RuntimeError('an artifact transaction is already active')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            yield

    def initialize(self) -> None:
        with self.transaction():
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS snapshots (
                    artifact_id TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('station-package', 'report')),
                    payload TEXT NOT NULL,
                    UNIQUE (artifact_id, kind)
                )
            ''')
            self._db.execute('''
                CREATE TABLE IF NOT EXISTS receipts (
                    artifact_id TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (artifact_id, kind) REFERENCES snapshots(artifact_id, kind)
                )
            ''')

    def insert_snapshot(self, artifact_id: str, kind: str, payload: str) -> None:
        if not self._db.in_transaction:
            raise RuntimeError('inserting a snapshot requires an artifact transaction')
        self._db.execute('INSERT INTO snapshots VALUES (?, ?, ?)', (artifact_id, kind, payload))

    def insert_receipt(self, artifact_id: str, kind: str, payload: str) -> None:
        if not self._db.in_transaction:
            raise RuntimeError('inserting a receipt requires an artifact transaction')
        self._db.execute('INSERT INTO receipts VALUES (?, ?, ?)', (artifact_id, kind, payload))

    def read_pair(self, artifact_id: str) -> tuple[str, str, str | None, str | None] | None:
        return self._db.execute('''
            SELECT snapshots.kind, snapshots.payload, receipts.kind, receipts.payload
            FROM snapshots LEFT JOIN receipts USING (artifact_id)
            WHERE snapshots.artifact_id = ?
        ''', (artifact_id,)).fetchone()
