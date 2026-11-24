from contextlib import closing
import json
import sqlite3

from archive import ArchiveIntegrityError, ArtifactCatalog, ArtifactNotFound, PublicationError, fetch
from exchange import issue
from record import RevisionStore, freeze
from review import audit
from station import account
from tests import WorkspaceTest, alpha, external_batch, reject_commit_for, stored_ids


class ArchiveTests(WorkspaceTest):
    def test_history(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as outgoing:
            old_revision = freeze(source, 'alpha', 'shift', *alpha())
            old_receipt = issue(source, outgoing, old_revision)
            old_package = fetch(outgoing, old_receipt.artifact_id)
        with ArtifactCatalog(self.review_path) as catalog:
            _, audit_receipt = audit(catalog, [old_package.payload], [('S', 'T')])
            old_report = fetch(catalog, audit_receipt.artifact_id)
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as outgoing:
            new_revision = freeze(source, 'alpha', 'shift', *alpha(6), supersedes=old_revision)
            new_receipt = issue(source, outgoing, new_revision)
        with ArtifactCatalog(self.station_path) as outgoing, ArtifactCatalog(self.review_path) as catalog:
            self.assertEqual(fetch(outgoing, old_receipt.artifact_id), old_package)
            self.assertEqual(fetch(catalog, audit_receipt.artifact_id), old_report)
            new_package = fetch(outgoing, new_receipt.artifact_id)
            new_report, _ = audit(catalog, [new_package.payload], [('S', 'T')])
        self.assertNotEqual(old_revision, new_revision)
        self.assertEqual(json.loads(old_report.payload)['results'][0]['upper_us'], 5)
        self.assertEqual(new_report.results[0].upper_us, 6)
        self.assertEqual(new_report.results[0].witness[-1].origin.revision, new_revision)
        self.assertEqual(old_report.receipt, audit_receipt)
        self.assertEqual(old_package.receipt, old_receipt)

    def test_pinned_revision(self):
        with RevisionStore(self.source_path) as source:
            original = freeze(source, 'alpha', 'shift', *alpha())
            corrected = freeze(source, 'alpha', 'shift', *alpha(6), supersedes=original)
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as outgoing:
            self.assertEqual(source.get(corrected).supersedes, original)
            old_receipt = issue(source, outgoing, original)
            new_receipt = issue(source, outgoing, corrected)
            snapshots = [fetch(outgoing, receipt.artifact_id) for receipt in (old_receipt, new_receipt)]
        with ArtifactCatalog(self.review_path) as catalog:
            for snapshot, revision, expected in zip(snapshots, (original, corrected), (5, 6), strict=True):
                report, _ = audit(catalog, [snapshot.payload], [('S', 'T')])
                result = report.results[0]
                self.assertEqual(result.upper_us, expected)
                self.assertEqual([(item.origin.revision, item.comparison.evidence_id) for item in result.witness],
                                 [(revision, 'e1'), (revision, 'e2')])

    def test_repeat_initialization(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            first = freeze(source, 'operator-station', 'operator-recording', *alpha())
            second = freeze(source, 'operator-station', 'operator-recording', *alpha(9), supersedes=first)
            receipt = issue(source, catalog, first)
            before = fetch(catalog, receipt.artifact_id)
            source.initialize()
            catalog.initialize()
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as catalog:
            source.initialize()
            catalog.initialize()
            self.assertEqual(account(source, first, 's', 't-alpha').upper_us, 5)
            self.assertEqual(account(source, second, 's', 't-alpha').upper_us, 9)
            self.assertEqual(source.get(second).supersedes, first)
            self.assertEqual(fetch(catalog, receipt.artifact_id), before)
            self.assertEqual(stored_ids(self.station_path), ((receipt.artifact_id,), (receipt.artifact_id,)))

    def test_failed_review_commit(self):
        packages = external_batch()[:2]
        with ArtifactCatalog(self.review_path) as catalog:
            _, old_receipt = audit(catalog, packages, [('S', 'U')])
            old = fetch(catalog, old_receipt.artifact_id)
        reject_commit_for(self.review_path, 'report')
        with ArtifactCatalog(self.review_path) as catalog:
            with self.assertRaises(PublicationError) as failure:
                audit(catalog, packages, [('T', 'S')])
        cause = failure.exception.__cause__
        self.assertIsInstance(cause, sqlite3.IntegrityError)
        self.assertEqual(cause.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY)
        with ArtifactCatalog(self.review_path) as reopened:
            self.assertEqual(fetch(reopened, old_receipt.artifact_id), old)
            self.assertEqual(stored_ids(self.review_path), ((old_receipt.artifact_id,), (old_receipt.artifact_id,)))
        with closing(sqlite3.connect(self.review_path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pending_commit').fetchone(), (0,))

    def test_fetch_distinguishes_unknown_id_from_incomplete_pair(self):
        with ArtifactCatalog(self.review_path) as catalog:
            with self.assertRaises(ArtifactNotFound):
                fetch(catalog, 'unknown')
            _, receipt = audit(catalog, external_batch()[:2], [('S', 'U')])
        with closing(sqlite3.connect(self.review_path)) as db, db:
            db.execute('DELETE FROM receipts WHERE artifact_id = ?', (receipt.artifact_id,))
        with ArtifactCatalog(self.review_path) as catalog:
            with self.assertRaises(ArchiveIntegrityError):
                fetch(catalog, receipt.artifact_id)
