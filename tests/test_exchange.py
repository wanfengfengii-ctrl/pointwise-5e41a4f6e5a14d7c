import json
import sqlite3

from archive import ArtifactCatalog, PublicationError, fetch
from exchange import issue, receive
from record import RevisionStore, UnknownRevision, freeze
from station import InconsistentConstraints
from tests import WorkspaceTest, alpha, edge, pulse, reject_commit_for, stored_ids


class ExchangeTests(WorkspaceTest):
    def test_fixed_issue(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            revision = freeze(source, 'alpha', 'shift', *alpha())
            receipt = issue(source, catalog, revision)
        with ArtifactCatalog(self.station_path) as catalog:
            station_file = fetch(catalog, receipt.artifact_id)
        self.assertEqual(station_file.receipt, receipt)
        self.assertEqual(station_file.kind, 'station-package')
        self.assertEqual(receive(station_file.payload).evidence.origin.revision, revision)
        self.assertEqual(stored_ids(self.station_path), ((receipt.artifact_id,), (receipt.artifact_id,)))

    def test_hidden_bridge(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            revision = freeze(source, 'alpha', 'shift', *alpha())
            receipt = issue(source, catalog, revision)
        with ArtifactCatalog(self.station_path) as catalog:
            payload = fetch(catalog, receipt.artifact_id).payload
        # Read the wire object directly and follow the two physical rows of this fixture.
        wire = json.loads(payload)
        self.assertEqual((wire['version'], wire['package_id']), (1, receipt.artifact_id))
        origin = {'station': 'alpha', 'recording': 'shift', 'revision': revision}
        self.assertEqual(wire['origin'], origin)
        evidence = wire['evidence']
        self.assertEqual(evidence['origin'], origin)
        self.assertEqual({p['name']: p['sync'] for p in evidence['pulses']}, {
            's': 'S', 't-alpha': 'T', 'h': None, 'quiet': 'X',
        })
        self.assertEqual({row['id'] for row in evidence['comparisons']}, {'e1', 'e2'}, 'PULSE_BOUND_HANDOFF')
        next_edge = {row['start']: row for row in evidence['comparisons']}
        first = next_edge['s']
        second = next_edge[first['end']]
        self.assertEqual((first['id'], first['end'], second['id'], second['end']), ('e1', 'h', 'e2', 't-alpha'))
        self.assertEqual(first['upper_us'] + second['upper_us'], 5)

    def test_local_conflict(self):
        pulses, comparisons = alpha()
        comparisons.append(edge('back', 't-alpha', 's', -6))
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            revision = freeze(source, 'alpha', 'shift', pulses, comparisons)
            with self.assertRaises(InconsistentConstraints):
                issue(source, catalog, revision)
            with self.assertRaises(UnknownRevision):
                issue(source, catalog, 'missing')
        self.assertEqual(stored_ids(self.station_path), ((), ()))

    def test_disconnected_cycle(self):
        pulses, comparisons = alpha()
        pulses.extend([pulse('x', None), pulse('y', None)])
        comparisons.extend([edge('xy', 'x', 'y', 0), edge('yx', 'y', 'x', -1)])
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            revision = freeze(source, 'alpha', 'shift', pulses, comparisons)
            with self.assertRaises(InconsistentConstraints):
                issue(source, catalog, revision)
        self.assertEqual(stored_ids(self.station_path), ((), ()))

    def test_issue_commit_rejected(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            revision = freeze(source, 'alpha', 'shift', *alpha())
            receipt = issue(source, catalog, revision)
            initial = fetch(catalog, receipt.artifact_id)
        reject_commit_for(self.station_path, 'station-package')
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            with self.assertRaises(PublicationError) as failure:
                issue(source, catalog, revision)
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(failure.exception.__cause__.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
        with ArtifactCatalog(self.station_path) as catalog:
            self.assertEqual(fetch(catalog, receipt.artifact_id), initial)
        self.assertEqual(stored_ids(self.station_path), ((receipt.artifact_id,), (receipt.artifact_id,)))
