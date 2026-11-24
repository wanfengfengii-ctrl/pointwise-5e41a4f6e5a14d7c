from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from archive import ArtifactCatalog, fetch
from exchange import issue
from record import RevisionStore, freeze


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.source_path = self.root / 'recordings.sqlite'
        self.station_path = self.root / 'stations.sqlite'
        self.review_path = self.root / 'night.sqlite'


def pulse(name, sync):
    return {'name': name, 'sync': sync}


def edge(evidence_id, start, end, upper_us):
    return {'id': evidence_id, 'start': start, 'end': end, 'upper_us': upper_us, 'unit': 'us'}


def alpha(upper=5):
    return (
        [pulse('s', 'S'), pulse('t-alpha', 'T'), pulse('h', None), pulse('quiet', 'X')],
        [edge('e1', 's', 'h', 0), edge('e2', 'h', 't-alpha', upper)],
    )


def beta():
    return (
        [pulse('t-beta', 'T'), pulse('u', 'U'), pulse('s-ref', 'S'), pulse('h', None)],
        [edge('e3', 't-beta', 'h', 1), edge('e4', 'h', 's-ref', -2), edge('e1', 't-beta', 'u', 2)],
    )


def gamma():
    return [pulse('u-ref', 'U'), pulse('s-ref', 'S')], [edge('e1', 'u-ref', 's-ref', -8)]


def external_package(package_id, station, recording, revision, pulses, comparisons):
    origin = {'station': station, 'recording': recording, 'revision': revision}
    return json.dumps({
        'version': 1,
        'package_id': package_id,
        'origin': origin,
        'evidence': {'origin': origin, 'pulses': pulses, 'comparisons': comparisons},
    })


def external_batch():
    return (
        external_package('outside-a', 'alpha', 'shift', 'external-1', *alpha()),
        external_package('outside-b', 'beta', 'shift', 'external-1', *beta()),
        external_package('outside-c', 'gamma', 'shift', 'external-1', *gamma()),
    )


def local_packages(source_path, station_path):
    with RevisionStore(source_path) as source, ArtifactCatalog(station_path) as outgoing:
        left = freeze(source, 'alpha', 'shift', *alpha())
        right = freeze(source, 'beta', 'shift', *beta())
        receipts = (issue(source, outgoing, left), issue(source, outgoing, right))
    with ArtifactCatalog(station_path) as outgoing:
        return tuple(fetch(outgoing, receipt.artifact_id) for receipt in receipts)


def stored_ids(path):
    with closing(sqlite3.connect(path)) as db:
        return (
            tuple(row[0] for row in db.execute('SELECT artifact_id FROM snapshots ORDER BY artifact_id')),
            tuple(row[0] for row in db.execute('SELECT artifact_id FROM receipts ORDER BY artifact_id')),
        )


def revision_ids(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(row[0] for row in db.execute('SELECT revision FROM recording_revisions ORDER BY revision'))


def reject_commit_for(path, kind):
    trigger_condition = {
        'station-package': "NEW.kind = 'station-package'",
        'report': "NEW.kind = 'report'",
    }[kind]
    with closing(sqlite3.connect(path)) as db:
        db.executescript(f'''
            CREATE TABLE allowed_commit (id INTEGER PRIMARY KEY);
            CREATE TABLE pending_commit (
                artifact_id TEXT PRIMARY KEY,
                allowed_id INTEGER REFERENCES allowed_commit(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER check_commit AFTER INSERT ON receipts
            WHEN {trigger_condition}
            BEGIN
                INSERT INTO pending_commit VALUES (NEW.artifact_id, 1);
            END;
        ''')
