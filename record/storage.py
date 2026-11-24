from os import PathLike
import sqlite3

from record.pulses import require_identifier
from record.revisions import RecordingRevision, dump_measurement_json, load_measurement_json


class UnknownRevision(KeyError):
    pass


class RevisionStore:
    def __init__(self, path: str | PathLike[str]) -> None:
        self._db = sqlite3.connect(path, isolation_level=None)
        try:
            self._db.execute('PRAGMA foreign_keys = ON')
            self.initialize()
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> 'RevisionStore':
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def initialize(self) -> None:
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS recording_revisions (
                revision TEXT PRIMARY KEY NOT NULL,
                station TEXT NOT NULL,
                recording TEXT NOT NULL,
                supersedes TEXT REFERENCES recording_revisions(revision),
                snapshot TEXT NOT NULL
            )
        ''')

    def append(self, revision: RecordingRevision) -> str:
        origin = revision.origin
        snapshot = dump_measurement_json(revision.to_payload())
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            if revision.supersedes is not None:
                previous = self._db.execute(
                    'SELECT station, recording FROM recording_revisions WHERE revision = ?',
                    (revision.supersedes,),
                ).fetchone()
                if previous is None:
                    raise UnknownRevision(revision.supersedes)
                if previous != (origin.station, origin.recording):
                    raise ValueError('correction must refer to a revision of the same recording')
            self._db.execute(
                'INSERT INTO recording_revisions VALUES (?, ?, ?, ?, ?)',
                (origin.revision, origin.station, origin.recording, revision.supersedes, snapshot),
            )
        return origin.revision

    def get(self, revision_id: str) -> RecordingRevision:
        revision_id = require_identifier(revision_id, 'revision')
        row = self._db.execute(
            'SELECT station, recording, supersedes, snapshot FROM recording_revisions WHERE revision = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise UnknownRevision(revision_id)
        station, recording, supersedes, snapshot = row
        revision = RecordingRevision.from_payload(load_measurement_json(snapshot), supersedes=supersedes)
        if (revision.origin.station, revision.origin.recording, revision.origin.revision) != (
            station, recording, revision_id
        ):
            raise ValueError('stored recording snapshot has inconsistent origin')
        return revision
