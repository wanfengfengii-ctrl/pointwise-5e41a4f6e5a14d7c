import json

from archive import ArtifactCatalog, fetch
from exchange import InvalidPackage
from review import UnknownQueryEndpoint, audit
from station import InconsistentConstraints
from tests import WorkspaceTest, edge, external_batch, external_package, local_packages, pulse, stored_ids


class ReviewTests(WorkspaceTest):
    def test_cross_station_scope(self):
        left, right = local_packages(self.source_path, self.station_path)
        queries = [('S', 'U'), ('X', 'U'), ('S', 'U')]
        with ArtifactCatalog(self.review_path) as catalog:
            report, receipt = audit(catalog, [left.payload, right.payload], queries)
            swapped, _ = audit(catalog, [right.payload, left.payload], queries)
            artifact = fetch(catalog, receipt.artifact_id)
        self.assertEqual([item.upper_us for item in report.results], [7, None, 7], 'PULSE_BOUND_HANDOFF')
        self.assertEqual(report, swapped)
        self.assertEqual([item.origin.station for item in report.results[0].witness], ['alpha', 'alpha', 'beta'])
        self.assertEqual([item['upper_us'] for item in json.loads(artifact.payload)['results']], [7, None, 7])

    def test_external_packages(self):
        left, right, _ = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            report, receipt = audit(catalog, [left, right], [('S', 'U')])
            fixed = json.loads(fetch(catalog, receipt.artifact_id).payload)
        result = report.results[0]
        self.assertEqual(result.upper_us, 7, 'PULSE_BOUND_HANDOFF')
        self.assertEqual(report.package_ids, ('outside-a', 'outside-b'))
        self.assertEqual([item.origin.station for item in result.witness], ['alpha', 'alpha', 'beta'])
        self.assertEqual(fixed['report_id'], receipt.artifact_id)
        self.assertEqual(fixed['package_ids'], ['outside-a', 'outside-b'])
        self.assertFalse(self.source_path.exists())

    def test_invalid_package(self):
        left, right, _ = external_batch()
        inconsistent = json.loads(left)
        inconsistent['evidence']['origin']['revision'] = 'other'
        unregistered = json.loads(left)
        unregistered['evidence']['comparisons'][0]['end'] = 'absent'
        wrong_version = json.loads(left)
        wrong_version['version'] = True
        wrong_unit = json.loads(left)
        wrong_unit['evidence']['comparisons'][0]['unit'] = 'ms'
        with ArtifactCatalog(self.review_path) as catalog:
            for invalid in (inconsistent, unregistered, wrong_version, wrong_unit):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(InvalidPackage):
                        audit(catalog, [json.dumps(invalid), right], [('S', 'U')])
                    self.assertEqual(stored_ids(self.review_path), ((), ()))
            with self.assertRaises(InvalidPackage):
                audit(catalog, ['{"version": 1, "version": 1}'], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_scoped_identity(self):
        left, right, _ = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            report, _ = audit(catalog, [right, left], [('S', 'U'), ('T', 'S')])
        self.assertEqual([row.upper_us for row in report.results], [7, -1])
        self.assertEqual([edge.origin.station for edge in report.results[1].witness], ['beta', 'beta'])
        self.assertEqual([edge.comparison.evidence_id for edge in report.results[1].witness], ['e3', 'e4'])

    def test_scoped_witness(self):
        left, right, _ = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            _, receipt = audit(catalog, [right, left], [('S', 'U')])
            row = json.loads(fetch(catalog, receipt.artifact_id).payload)['results'][0]
        self.assertEqual(row['upper_us'], 7)
        self.assertEqual(
            [(item['origin'], item['id'], item['start'], item['end'], item['upper_us']) for item in row['witness']],
            [
                ({'station': 'alpha', 'recording': 'shift', 'revision': 'external-1'}, 'e1', 's', 'h', 0),
                ({'station': 'alpha', 'recording': 'shift', 'revision': 'external-1'}, 'e2', 'h', 't-alpha', 5),
                ({'station': 'beta', 'recording': 'shift', 'revision': 'external-1'}, 'e1', 't-beta', 'u', 2),
            ],
        )
        independent_originals = {}
        scoped_pulses = {}
        for wire in map(json.loads, (left, right)):
            origin = wire['origin']
            scope = (origin['station'], origin['recording'], origin['revision'])
            for declaration in wire['evidence']['pulses']:
                sync = declaration['sync']
                scoped_pulses[scope, declaration['name']] = ('public', sync) if sync else ('temporary', scope, declaration['name'])
            for comparison in wire['evidence']['comparisons']:
                independent_originals[scope, comparison['id']] = comparison
        at = ('public', 'S')
        total = 0
        for original in row['witness']:
            origin = original['origin']
            scope = (origin['station'], origin['recording'], origin['revision'])
            self.assertEqual({key: value for key, value in original.items() if key != 'origin'},
                             independent_originals[scope, original['id']])
            self.assertEqual(scoped_pulses[scope, original['start']], at)
            at = scoped_pulses[scope, original['end']]
            total += original['upper_us']
        self.assertEqual((at, total), (('public', 'U'), 7))

    def test_ordered_queries(self):
        left, right, _ = external_batch()
        queries = [('S', 'U'), ('X', 'S'), ('S', 'U')]
        with ArtifactCatalog(self.review_path) as catalog:
            for packages in ([left, right], [right, left]):
                _, receipt = audit(catalog, packages, queries)
                rows = json.loads(fetch(catalog, receipt.artifact_id).payload)['results']
                self.assertEqual([(r['position'], r['start'], r['end'], r['upper_us']) for r in rows],
                                 [(0, 'S', 'U', 7), (1, 'X', 'S', None), (2, 'S', 'U', 7)])
                self.assertEqual(rows[1]['witness'], [])
                self.assertEqual(rows[0]['witness'], rows[2]['witness'])

    def test_empty_queries(self):
        left, right, _ = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            report, receipt = audit(catalog, [left, right], [])
            self.assertEqual(report.results, ())
            self.assertEqual(json.loads(fetch(catalog, receipt.artifact_id).payload)['results'], [])

    def test_reopen_report(self):
        left, right, _ = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            _, receipt = audit(catalog, [left, right], [('S', 'U')])
            original = fetch(catalog, receipt.artifact_id)
        with ArtifactCatalog(self.review_path) as reopened:
            replay = fetch(reopened, receipt.artifact_id)
        self.assertEqual(replay, original)
        self.assertEqual(replay.receipt, receipt)
        self.assertEqual(json.loads(replay.payload)['results'][0]['upper_us'], 7)

    def test_joint_conflict(self):
        left, right = local_packages(self.source_path, self.station_path)
        third = external_batch()[2]
        with ArtifactCatalog(self.review_path) as catalog:
            with self.assertRaises(InconsistentConstraints, msg='PULSE_BOUND_HANDOFF'):
                audit(catalog, [left.payload, right.payload, third], [('S', 'U')])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_external_joint_conflict(self):
        packages = external_batch()
        with ArtifactCatalog(self.review_path) as catalog:
            for package in packages:
                audit(catalog, [package], [])
            before = stored_ids(self.review_path)
            with self.assertRaises(InconsistentConstraints):
                audit(catalog, packages, [('S', 'U')])
            self.assertEqual(stored_ids(self.review_path), before)

    def test_off_query_conflict(self):
        with ArtifactCatalog(self.review_path) as catalog:
            for queries in ([('X', 'X')], []):
                with self.subTest(queries=queries):
                    with self.assertRaises(InconsistentConstraints):
                        audit(catalog, external_batch(), queries)
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_unknown_query_endpoint_has_no_report(self):
        with ArtifactCatalog(self.review_path) as catalog:
            for query in (('S', 'missing'), ('S', 'h'), ('S', 't-alpha'), ('S',), ('S', [])):
                with self.subTest(query=query):
                    with self.assertRaises(UnknownQueryEndpoint):
                        audit(catalog, external_batch()[:2], [query])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_legacy_public_only_package(self):
        old = external_package('legacy', 'old-station', 'shift', 'old-revision',
                               [pulse('a', 'A'), pulse('b', 'B')], [edge('old-e1', 'a', 'b', -4)])
        with ArtifactCatalog(self.review_path) as catalog:
            report, _ = audit(catalog, [old, old], [('A', 'B'), ('B', 'A'), ('B', 'B')])
        self.assertEqual(report.package_ids, ('legacy',))
        self.assertEqual([bound.upper_us for bound in report.results], [-4, None, 0])
        self.assertEqual([len(bound.witness) for bound in report.results], [1, 0, 0])

    def test_conflicting_copies_do_not_change_frozen_origin(self):
        left, right, _ = external_batch()
        altered = json.loads(left)
        altered['package_id'] = 'another-package'
        altered['evidence']['comparisons'][1]['upper_us'] = 6
        with ArtifactCatalog(self.review_path) as catalog:
            with self.assertRaises(InvalidPackage):
                audit(catalog, [left, json.dumps(altered)], [])
            altered = json.loads(right)
            altered['package_id'] = 'outside-a'
            with self.assertRaises(InvalidPackage):
                audit(catalog, [left, json.dumps(altered)], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))
