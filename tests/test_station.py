from record import RevisionStore, UnknownRevision, freeze
from station import InconsistentConstraints, account
from tests import WorkspaceTest, alpha, edge, pulse


class StationTests(WorkspaceTest):
    def test_exact_bound(self):
        with RevisionStore(self.source_path) as store:
            revision = freeze(store, 'alpha', 'shift', *alpha())
            result = account(store, revision, 's', 't-alpha')
        self.assertEqual(result.upper_us, 5)
        self.assertEqual(result.origin.revision, revision)
        self.assertEqual(
            [(item.comparison.evidence_id, item.comparison.start, item.comparison.end, item.upper_us) for item in result.witness],
            [('e1', 's', 'h', 0), ('e2', 'h', 't-alpha', 5)],
        )

    def test_tight_path(self):
        pulses, comparisons = alpha()
        direct = edge('direct', 's', 't-alpha', 8)
        with RevisionStore(self.source_path) as store:
            for rows in ([direct, *comparisons], [*reversed(comparisons), direct]):
                revision = freeze(store, 'alpha', 'shift', pulses, rows)
                result = account(store, revision, 's', 't-alpha')
                self.assertEqual(result.upper_us, 5)
                self.assertEqual([item.comparison.evidence_id for item in result.witness], ['e1', 'e2'])

    def test_boundary_values(self):
        pulses, comparisons = alpha(0)
        with RevisionStore(self.source_path) as store:
            revision = freeze(store, 'alpha', 'shift', pulses, comparisons)
            same = account(store, revision, 's', 's')
            distinct = account(store, revision, 's', 't-alpha')
            disconnected = account(store, revision, 'quiet', 's')
            with self.assertRaises(ValueError):
                account(store, revision, 's', 'h')
            with self.assertRaises(UnknownRevision):
                account(store, 'missing', 's', 's')
        self.assertEqual((same.upper_us, same.witness), (0, ()))
        self.assertEqual((distinct.upper_us, len(distinct.witness)), (0, 2))
        self.assertEqual((disconnected.upper_us, disconnected.witness), (None, ()))

    def test_witness_tie(self):
        pulses, comparisons = alpha()
        pulses.append(pulse('alternate', None))
        comparisons.extend([
            edge('z1', 's', 'alternate', 0), edge('z2', 'alternate', 't-alpha', 5),
            edge('00', 'h', 's', 0),
        ])
        with RevisionStore(self.source_path) as store:
            for rows in (comparisons, list(reversed(comparisons))):
                revision = freeze(store, 'alpha', 'shift', pulses, rows)
                result = account(store, revision, 's', 't-alpha')
                self.assertEqual([item.comparison.evidence_id for item in result.witness], ['e1', 'e2'])
                self.assertEqual(sum(item.upper_us for item in result.witness), 5)

    def test_station_conflict_beyond_query(self):
        pulses, comparisons = alpha()
        pulses.append(pulse('broken', None))
        comparisons.append(edge('loop', 'broken', 'broken', -1))
        with RevisionStore(self.source_path) as store:
            revision = freeze(store, 'alpha', 'shift', pulses, comparisons)
            with self.assertRaises(InconsistentConstraints):
                account(store, revision, 's', 't-alpha')

    def test_large_integer_distance_is_exact(self):
        pulses, comparisons = alpha(10 ** 4400)
        comparisons[0]['upper_us'] = -3
        with RevisionStore(self.source_path) as store:
            revision = freeze(store, 'alpha', 'shift', pulses, comparisons)
            result = account(store, revision, 's', 't-alpha')
        self.assertTrue(result.upper_us == 10 ** 4400 - 3)
        self.assertTrue(result.witness[1].upper_us == 10 ** 4400)
