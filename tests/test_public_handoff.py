import json
import sqlite3

from archive import ArtifactCatalog, PublicationError, fetch
from exchange import InvalidPackage, issue, issue_public, receive_any
from public_handoff_sample import (
    ALPHA, BETA, GAMMA, PREFIX_ALPHA, PREFIX_BETA, freeze_sample,
)
from record import RevisionStore, freeze
from review import UnknownQueryEndpoint, audit_mixed
from station import InconsistentConstraints
from tests import WorkspaceTest, edge, pulse, reject_commit_for, stored_ids


def _issue(sample, public, *, source_path=None, station_path=None):
    with RevisionStore(source_path or ':memory:') as source, \
            ArtifactCatalog(station_path or ':memory:') as station:
        revision = freeze_sample(source, sample)
        receipt = (issue_public if public else issue)(source, station, revision)
        return fetch(station, receipt.artifact_id).payload


def v2_envelope(package_id, origin, public, bounds, *, version=2):
    return json.dumps({
        'version': version,
        'package_id': package_id,
        'origin': origin,
        'evidence': {'public': public, 'bounds': bounds},
    })


def origin_of(payload):
    return json.loads(payload)['origin']


class PublicIssuanceTests(WorkspaceTest):
    def test_v2_envelope_is_limited_disclosure(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze_sample(source, ALPHA)
            receipt = issue_public(source, station, revision)
        with ArtifactCatalog(self.station_path) as station:
            archived = fetch(station, receipt.artifact_id)
        wire = json.loads(archived.payload)
        self.assertEqual(archived.kind, 'station-package')
        self.assertEqual(set(wire), {'version', 'package_id', 'origin', 'evidence'})
        self.assertEqual((wire['version'], wire['package_id']), (2, receipt.artifact_id))
        self.assertEqual(wire['origin'], {
            'station': ALPHA[0], 'recording': ALPHA[1], 'revision': revision,
        })
        evidence = wire['evidence']
        self.assertEqual(set(evidence), {'public', 'bounds'})
        # Public sync identifiers, including the isolated point I, each once.
        self.assertEqual(evidence['public'], ['I', 'S', 'T', 'U'])
        flat_text = archived.payload
        # Private pulse names, private endpoints and the V1 pulse list stay at
        # the station; only public points, bounds and opaque refs are disclosed.
        for private in ('hidden-shift', 'quiet', 'pulses'):
            self.assertNotIn(private, flat_text)
        for row in evidence['bounds']:
            self.assertEqual(set(row), {'start', 'end', 'upper_us', 'refs'})
            self.assertTrue(all(isinstance(ref, str) for ref in row['refs']))
        bounds = {(row['start'], row['end']): row for row in evidence['bounds']}
        self.assertEqual(bounds[('S', 'U')]['upper_us'], 3)
        self.assertEqual(bounds[('S', 'U')]['refs'], ['a1', 'a2', 'a3'])
        self.assertEqual(bounds[('S', 'T')]['upper_us'], 2)
        self.assertEqual(bounds[('S', 'T')]['refs'], ['a1', 'a2'])
        # Unreachable pairs and same-point rows are absent.
        self.assertNotIn(('U', 'S'), bounds)
        self.assertNotIn(('S', 'S'), bounds)
        for row in evidence['bounds']:
            self.assertIsInstance(row['upper_us'], int)
            self.assertTrue(row['refs'])

    def test_receive_any_reads_both_versions(self):
        v2 = _issue(ALPHA, True)
        v1 = _issue(BETA, False)
        self.assertEqual(receive_any(v2).__class__.__name__, 'ReceivedV2Package')
        self.assertEqual(receive_any(v1).__class__.__name__, 'ReceivedPackage')

    def test_issue_public_blocks_any_component_conflict(self):
        pulses = [pulse('s', 'S'), pulse('h', None), pulse('x', None), pulse('y', None)]
        comparisons = [
            edge('a1', 's', 'h', 1),
            edge('xy', 'x', 'y', 0), edge('yx', 'y', 'x', -1),
        ]
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze(source, 'alpha', 'limited', pulses, comparisons)
            with self.assertRaises(InconsistentConstraints):
                issue_public(source, station, revision)
        self.assertEqual(stored_ids(self.station_path), ((), ()))

    def test_empty_public_revision_issues_empty_evidence(self):
        pulses = [pulse('h1', None), pulse('h2', None)]
        comparisons = [edge('a1', 'h1', 'h2', 2)]
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze(source, 'alpha', 'private', pulses, comparisons)
            receipt = issue_public(source, station, revision)
            payload = fetch(station, receipt.artifact_id).payload
        self.assertEqual(json.loads(payload)['evidence'], {'public': [], 'bounds': []})

    def test_negative_and_zero_integer_bounds_survive(self):
        pulses = [pulse('s', 'S'), pulse('t', 'T')]
        comparisons = [edge('a1', 's', 't', -2)]
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze(source, 'example', 'shift', pulses, comparisons)
            receipt = issue_public(source, station, revision)
            wire = json.loads(fetch(station, receipt.artifact_id).payload)
        self.assertEqual(wire['evidence']['bounds'], [{
            'start': 'S', 'end': 'T', 'upper_us': -2, 'refs': ['a1'],
        }])

    def test_issue_public_commit_failure_leaves_no_artifact(self):
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze_sample(source, ALPHA)
            receipt = issue_public(source, station, revision)
            initial = fetch(station, receipt.artifact_id)
        reject_commit_for(self.station_path, 'station-package')
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            with self.assertRaises(PublicationError) as failure:
                issue_public(source, station, revision)
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        with ArtifactCatalog(self.station_path) as station:
            self.assertEqual(fetch(station, receipt.artifact_id), initial)
        self.assertEqual(stored_ids(self.station_path),
                         ((receipt.artifact_id,), (receipt.artifact_id,)))


class MixedAuditTests(WorkspaceTest):
    def test_alpha_v2_only_matches_full_evidence(self):
        alpha = _issue(ALPHA, True)
        with ArtifactCatalog(self.review_path) as night:
            report, receipt = audit_mixed(
                night, [alpha], [('S', 'U'), ('U', 'S'), ('S', 'I'), ('I', 'I')],
            )
            archived = fetch(night, receipt.artifact_id)
        self.assertEqual([(r['upper_us'], [w['id'] for w in r['witness']]) for r in report['results']], [
            (3, ['a1', 'a2', 'a3']), (None, []), (None, []), (0, []),
        ])
        body = json.loads(archived.payload)
        self.assertEqual(body['report_id'], receipt.artifact_id)
        self.assertEqual(body['version'], 2)
        self.assertEqual(body['package_ids'], report['package_ids'])

    def test_mixed_picks_b2_a3_independent_of_package_order(self):
        alpha = _issue(ALPHA, True)
        beta = _issue(BETA, False)
        with ArtifactCatalog(self.review_path) as night:
            first, _ = audit_mixed(night, [alpha, beta], [('S', 'U')])
            swapped, _ = audit_mixed(night, [beta, alpha], [('S', 'U')])
        expected = [(3, [('beta', 'b2'), ('alpha', 'a3')])]
        for report in (first, swapped):
            actual = [(r['upper_us'], [(w['origin']['station'], w['id']) for w in r['witness']])
                      for r in report['results']]
            self.assertEqual(actual, expected)

    def test_tie_breaks_by_count_then_lexicographic_sequence(self):
        alpha = _issue(PREFIX_ALPHA, True)
        beta = _issue(PREFIX_BETA, False)
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [alpha, beta], [('S', 'D')])
        row = report['results'][0]
        self.assertEqual(row['upper_us'], 2)
        self.assertEqual([(w['origin']['station'], w['id']) for w in row['witness']], [
            ('alpha', 'a1'), ('alpha', 'a2'), ('beta', 'b2'),
        ])

    def test_query_order_and_duplicate_positions_are_retained(self):
        alpha = _issue(ALPHA, True)
        beta = _issue(BETA, False)
        queries = [('S', 'U'), ('S', 'U'), ('T', 'S')]
        with ArtifactCatalog(self.review_path) as night:
            report, receipt = audit_mixed(night, [alpha, beta], queries)
            rows = json.loads(fetch(night, receipt.artifact_id).payload)['results']
        self.assertEqual([r['position'] for r in rows], [0, 1, 2])
        self.assertEqual([(r['start'], r['end']) for r in rows], queries)
        self.assertEqual(rows[0]['witness'], rows[1]['witness'])
        self.assertIsNone(rows[2]['upper_us'])
        self.assertEqual(rows[2]['witness'], [])

    def test_empty_query_still_adjudicates_the_whole_batch(self):
        packages = [_issue(ALPHA, True), _issue(BETA, False), _issue(GAMMA, False)]
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(InconsistentConstraints):
                audit_mixed(night, packages, [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_distinct_point_zero_bound_keeps_witness(self):
        pulses = [pulse('a', 'A'), pulse('b', 'B')]
        comparisons = [edge('z1', 'a', 'b', 0)]
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze(source, 'zero', 'shift', pulses, comparisons)
            package = fetch(station, issue_public(source, station, revision).artifact_id).payload
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [package], [('A', 'B'), ('A', 'A')])
        self.assertEqual(report['results'][0]['upper_us'], 0)
        self.assertEqual([w['id'] for w in report['results'][0]['witness']], ['z1'])
        self.assertEqual(report['results'][1], {
            'position': 1, 'start': 'A', 'end': 'A', 'upper_us': 0, 'witness': [],
        })

    def test_unknown_query_endpoint_and_bad_query_shape(self):
        alpha = _issue(ALPHA, True)
        with ArtifactCatalog(self.review_path) as night:
            for query in (('S', 'missing'), ('S', 'hidden-shift'), ('S',), ('S', [])):
                with self.subTest(query=query):
                    with self.assertRaises(UnknownQueryEndpoint):
                        audit_mixed(night, [alpha], [query])
        self.assertEqual(stored_ids(self.review_path), ((), ()))


class MixedIntakeTests(WorkspaceTest):
    def _alpha_v2(self):
        return _issue(ALPHA, True, source_path=self.source_path, station_path=self.station_path)

    def test_duplicate_resubmission_counts_once(self):
        alpha = self._alpha_v2()
        beta = _issue(BETA, False, source_path=self.source_path, station_path=self.station_path)
        with ArtifactCatalog(self.review_path) as night:
            report, receipt = audit_mixed(night, [alpha, alpha, beta, beta], [('S', 'U')])
            body = json.loads(fetch(night, receipt.artifact_id).payload)
        self.assertEqual(report['package_ids'], sorted([
            json.loads(alpha)['package_id'], json.loads(beta)['package_id'],
        ]))
        self.assertEqual(body['package_ids'], report['package_ids'])

    def test_same_number_different_text_is_rejected(self):
        alpha = self._alpha_v2()
        altered = json.loads(alpha)
        altered['evidence']['bounds'][0]['upper_us'] = 99
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(InvalidPackage):
                audit_mixed(night, [alpha, json.dumps(altered)], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_same_origin_v1_and_v2_together_is_rejected(self):
        # V1 and V2 packages of the same frozen origin may not be mixed.
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze_sample(source, ALPHA)
            v2 = fetch(station, issue_public(source, station, revision).artifact_id).payload
            v1 = fetch(station, issue(source, station, revision).artifact_id).payload
        self.assertEqual(origin_of(v1), origin_of(v2))
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(InvalidPackage):
                audit_mixed(night, [v2, v1], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_same_origin_conflicting_facts_are_rejected(self):
        alpha = self._alpha_v2()
        wire = json.loads(alpha)
        conflict = dict(wire)
        conflict['package_id'] = 'other-pkg'
        conflict['evidence'] = {
            'public': wire['evidence']['public'],
            'bounds': [{**row, 'upper_us': row['upper_us'] + 1} for row in wire['evidence']['bounds']],
        }
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(InvalidPackage):
                audit_mixed(night, [alpha, json.dumps(conflict)], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_same_facts_under_different_package_ids_are_both_kept(self):
        first = self._alpha_v2()
        second = self._alpha_v2()
        self.assertNotEqual(json.loads(first)['package_id'], json.loads(second)['package_id'])
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [first, second], [('S', 'U')])
        self.assertEqual(report['package_ids'], sorted([
            json.loads(first)['package_id'], json.loads(second)['package_id'],
        ]))

    def test_field_and_list_order_do_not_change_fact_identity(self):
        alpha = self._alpha_v2()
        wire = json.loads(alpha)
        reordered = {
            'evidence': {
                'bounds': list(reversed(wire['evidence']['bounds'])),
                'public': wire['evidence']['public'],
            },
            'origin': wire['origin'],
            'package_id': wire['package_id'],
            'version': wire['version'],
        }
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [alpha, json.dumps(reordered)], [])
        self.assertEqual(len(report['package_ids']), 1)

    def test_invalid_v2_packages_are_rejected(self):
        good = self._alpha_v2()
        good_wire = json.loads(good)
        origin = good_wire['origin']
        cases = [
            v2_envelope('p', origin, ['S'], [{'start': 'S', 'end': 'S', 'upper_us': 1, 'refs': ['a1']}]),
            v2_envelope('p', origin, ['S', 'S'], []),
            v2_envelope('p', origin, ['S', 'T'],
                        [{'start': 'S', 'end': 'T', 'upper_us': True, 'refs': ['a1']}]),
            v2_envelope('p', origin, ['S', 'T'],
                        [{'start': 'S', 'end': 'T', 'upper_us': 1, 'refs': []}]),
            v2_envelope('p', origin, ['S'],
                        [{'start': 'S', 'end': 'T', 'upper_us': 1, 'refs': ['a1']}]),
            v2_envelope('p', origin, ['S', 'T'],
                        [
                            {'start': 'S', 'end': 'T', 'upper_us': 1, 'refs': ['a1']},
                            {'start': 'S', 'end': 'T', 'upper_us': 2, 'refs': ['a2']},
                        ]),
            v2_envelope('p', origin, ['S'], [], version=3),
            'not-json',
        ]
        with ArtifactCatalog(self.review_path) as night:
            for invalid in cases:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(InvalidPackage):
                        audit_mixed(night, [good, invalid], [])
                    self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_failed_report_commit_adds_nothing(self):
        packages = [_issue(ALPHA, True), _issue(BETA, False)]
        with ArtifactCatalog(self.review_path) as night:
            _, old_receipt = audit_mixed(night, packages, [('S', 'U')])
            old = fetch(night, old_receipt.artifact_id)
        reject_commit_for(self.review_path, 'report')
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(PublicationError) as failure:
                audit_mixed(night, packages, [('T', 'S')])
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        with ArtifactCatalog(self.review_path) as night:
            self.assertEqual(fetch(night, old_receipt.artifact_id), old)
        self.assertEqual(stored_ids(self.review_path),
                         ((old_receipt.artifact_id,), (old_receipt.artifact_id,)))

    def test_reopen_catalog_retrieves_report_and_receipt(self):
        alpha = _issue(ALPHA, True, source_path=self.source_path, station_path=self.station_path)
        with ArtifactCatalog(self.review_path) as night:
            _, receipt = audit_mixed(night, [alpha], [('S', 'U')])
        with ArtifactCatalog(self.review_path) as reopened:
            archived = fetch(reopened, receipt.artifact_id)
        self.assertEqual(archived.receipt, receipt)
        self.assertEqual(json.loads(archived.payload)['results'][0]['upper_us'], 3)


class ExternalV2Tests(WorkspaceTest):
    def test_externally_produced_v2_package_is_accepted(self):
        origin = {'station': 'outside', 'recording': 'shift', 'revision': 'r1'}
        package = v2_envelope('outside-v2', origin, ['A', 'B'], [
            {'start': 'A', 'end': 'B', 'upper_us': 4, 'refs': ['o1', 'o2']},
        ])
        with ArtifactCatalog(self.review_path) as night:
            report, receipt = audit_mixed(night, [package, package], [('A', 'B'), ('B', 'A')])
            body = json.loads(fetch(night, receipt.artifact_id).payload)
        self.assertEqual(tuple(report['package_ids']), ('outside-v2',))
        self.assertEqual(body['results'][0]['witness'], [
            {'origin': origin, 'id': 'o1'}, {'origin': origin, 'id': 'o2'},
        ])
        self.assertIsNone(body['results'][1]['upper_us'])

    def test_equal_weight_prefers_fewer_original_comparisons(self):
        origin = {'station': 'a', 'recording': 'r', 'revision': '1'}
        package = v2_envelope('short', origin, ['A', 'B', 'M'], [
            {'start': 'A', 'end': 'B', 'upper_us': 5, 'refs': ['one']},
            {'start': 'A', 'end': 'M', 'upper_us': 2, 'refs': ['x1']},
            {'start': 'M', 'end': 'B', 'upper_us': 3, 'refs': ['y1', 'y2']},
        ])
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [package], [('A', 'B')])
        row = report['results'][0]
        self.assertEqual(row['upper_us'], 5)
        self.assertEqual([w['id'] for w in row['witness']], ['one'])

    def test_ref_order_is_part_of_the_facts(self):
        origin = {'station': 'a', 'recording': 'r', 'revision': '1'}
        first = v2_envelope('p', origin, ['A', 'B'], [
            {'start': 'A', 'end': 'B', 'upper_us': 3, 'refs': ['y1', 'y2']},
        ])
        second = v2_envelope('p', origin, ['A', 'B'], [
            {'start': 'A', 'end': 'B', 'upper_us': 3, 'refs': ['y2', 'y1']},
        ])
        with ArtifactCatalog(self.review_path) as night:
            with self.assertRaises(InvalidPackage):
                audit_mixed(night, [first, second], [])
        self.assertEqual(stored_ids(self.review_path), ((), ()))

    def test_large_integer_bound_is_exact_through_v2(self):
        big = 10 ** 4400
        with RevisionStore(self.source_path) as source, ArtifactCatalog(self.station_path) as station:
            revision = freeze(
                source, 'big', 'shift',
                [pulse('s', 'S'), pulse('t', 'T')],
                [edge('e1', 's', 't', big)],
            )
            package = fetch(station, issue_public(source, station, revision).artifact_id).payload
        with ArtifactCatalog(self.review_path) as night:
            report, _ = audit_mixed(night, [package], [('S', 'T')])
        self.assertTrue(report['results'][0]['upper_us'] == big)

    def test_empty_batch_and_empty_queries_still_publishes(self):
        with ArtifactCatalog(self.review_path) as night:
            report, receipt = audit_mixed(night, [], [])
            body = json.loads(fetch(night, receipt.artifact_id).payload)
        self.assertEqual(report, {
            'version': 2, 'package_ids': [], 'results': [], 'report_id': receipt.artifact_id,
        })
        self.assertEqual(body['results'], [])
