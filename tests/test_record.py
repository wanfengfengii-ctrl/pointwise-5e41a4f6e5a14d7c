from record import RevisionStore, UnknownRevision, freeze
from tests import WorkspaceTest, alpha, edge, pulse, revision_ids


class RecordTests(WorkspaceTest):
    def test_unknown_pulse(self):
        with RevisionStore(self.source_path) as store:
            with self.assertRaisesRegex(ValueError, 'unknown pulse'):
                freeze(store, 'alpha', 'shift', [pulse('s', 'S')], [edge('e1', 's', 'h', 0)])
        self.assertEqual(revision_ids(self.source_path), ())

    def test_atomic_freeze(self):
        pulses, comparisons = alpha()
        bad_rows = [
            [edge('bad', 's', 'absent', 0)],
            [comparisons[0], {**comparisons[1], 'id': comparisons[0]['id']}],
            [{**comparisons[0], 'unit': 'ms'}],
            [{**comparisons[0], 'upper_us': True}],
            [{**comparisons[0], 'upper_us': 1.5}],
            [{key: value for key, value in comparisons[0].items() if key != 'upper_us'}],
        ]
        with RevisionStore(self.source_path) as store:
            revision_id = freeze(store, 'alpha', 'shift', pulses, comparisons)
            original = store.get(revision_id)
            for rows in bad_rows:
                with self.subTest(rows=rows):
                    with self.assertRaises(ValueError):
                        freeze(store, 'alpha', 'shift', pulses, rows, supersedes=revision_id)
                    self.assertEqual(revision_ids(self.source_path), (revision_id,))
                    self.assertEqual(store.get(revision_id), original)

    def test_pulse_declarations_are_explicit(self):
        with RevisionStore(self.source_path) as store:
            for declarations in (
                [pulse('s', 'S'), pulse('s', None)],
                [pulse('s', 'S'), pulse('alias', 'S')],
                [pulse('s', '')],
                [{'name': 's'}],
            ):
                with self.subTest(declarations=declarations):
                    with self.assertRaises(ValueError):
                        freeze(store, 'alpha', 'shift', declarations, [])
        self.assertEqual(revision_ids(self.source_path), ())

    def test_correction_requires_existing_revision_of_same_recording(self):
        with RevisionStore(self.source_path) as store:
            old = freeze(store, 'alpha', 'shift', *alpha())
            with self.assertRaises(UnknownRevision):
                freeze(store, 'alpha', 'shift', *alpha(6), supersedes='missing')
            for station, recording in [('beta', 'shift'), ('alpha', 'other')]:
                with self.subTest(station=station, recording=recording):
                    with self.assertRaisesRegex(ValueError, 'same recording'):
                        freeze(store, station, recording, *alpha(6), supersedes=old)
            self.assertEqual(store.get(old).comparisons[1].upper_us, 5)
            self.assertEqual(revision_ids(self.source_path), (old,))
