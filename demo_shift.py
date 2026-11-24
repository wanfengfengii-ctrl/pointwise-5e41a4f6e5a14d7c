import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive import ArtifactCatalog, fetch
from exchange import InvalidPackage, issue, issue_public
from public_handoff_sample import ALPHA, BETA, GAMMA, PREFIX_ALPHA, PREFIX_BETA, freeze_sample
from record import RevisionStore, freeze
from review import audit, audit_mixed
from station import InconsistentConstraints, account


def comparison(identifier, start, end, upper):
    return {'id': identifier, 'start': start, 'end': end, 'upper_us': upper, 'unit': 'us'}


def declarations(*pairs):
    return [{'name': name, 'sync': sync} for name, sync in pairs]


def alpha_record(upper):
    return (
        declarations(('s', 'S'), ('t-alpha', 'T'), ('h', None), ('quiet', 'X')),
        [comparison('a1', 's', 'h', 0), comparison('a2', 'h', 't-alpha', upper)],
    )


def run_shift(root: Path) -> None:
    source_path = root / 'recordings.sqlite'
    station_path = root / 'stations.sqlite'
    night_path = root / 'night.sqlite'
    alpha = alpha_record(5)
    beta = (
        declarations(('t-beta', 'T'), ('u', 'U'), ('s-ref', 'S'), ('h', None)),
        [comparison('b1', 't-beta', 'h', 1), comparison('b2', 'h', 's-ref', -2), comparison('b3', 't-beta', 'u', 2)],
    )
    gamma = (declarations(('u-ref', 'U'), ('s-ref', 'S')), [comparison('c1', 'u-ref', 's-ref', -8)])

    with RevisionStore(source_path) as source, ArtifactCatalog(station_path) as outgoing:
        alpha_id = freeze(source, 'alpha', 'morning', *alpha)
        beta_id = freeze(source, 'beta', 'morning', *beta)
        gamma_id = freeze(source, 'gamma', 'morning', *gamma)
        daytime = account(source, alpha_id, 's', 't-alpha')
        receipts = [issue(source, outgoing, revision) for revision in (alpha_id, beta_id, gamma_id)]
    if daytime.upper_us != 5 or [edge.comparison.evidence_id for edge in daytime.witness] != ['a1', 'a2']:
        raise RuntimeError('daytime expected the 0 + 5 microsecond witness')

    with ArtifactCatalog(station_path) as outgoing:
        packages = [fetch(outgoing, ticket.artifact_id).payload for ticket in receipts]
    queries = [('S', 'U'), ('X', 'S'), ('S', 'U')]
    expected = {'bounds_us': [7, None, 7], 'witness_ids': ['a1', 'a2', 'b3']}
    with ArtifactCatalog(night_path) as incoming:
        report, report_receipt = audit(incoming, packages[:2], queries)
        actual = {
            'bounds_us': [result.upper_us for result in report.results],
            'witness_ids': [edge.comparison.evidence_id for edge in report.results[0].witness],
        }
        if actual != expected:
            raise RuntimeError(f'PULSE_BOUND_HANDOFF expected {expected}, got {actual}')
        try:
            audit(incoming, packages, [('X', 'X')])
        except InconsistentConstraints:
            conflict = 'rejected'
        else:
            raise RuntimeError('PULSE_BOUND_HANDOFF accepted the three-station negative cycle')

    with RevisionStore(source_path) as source, ArtifactCatalog(station_path) as outgoing:
        corrected = freeze(source, 'alpha', 'morning', *alpha_record(6), supersedes=alpha_id)
        new_ticket = issue(source, outgoing, corrected)
        corrected_payload = fetch(outgoing, new_ticket.artifact_id).payload
        if fetch(outgoing, receipts[0].artifact_id).payload != packages[0]:
            raise RuntimeError('the earlier issued station package changed after correction')

    with ArtifactCatalog(night_path) as incoming:
        saved = fetch(incoming, report_receipt.artifact_id)
        rows = json.loads(saved.payload)['results']
        downstream = {
            'bounds_us': [row['upper_us'] for row in rows],
            'witness_ids': [item['id'] for item in rows[0]['witness']],
        }
        revised_report, _ = audit(incoming, [corrected_payload, packages[1]], [('S', 'U')])
    if downstream != expected or saved.receipt != report_receipt or revised_report.results[0].upper_us != 8:
        raise RuntimeError('the reopened report or corrected-source bound differs from the hand calculation')

    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'V5',
        'input': {
            'alpha': {'pulses': alpha[0], 'comparisons': alpha[1]},
            'beta': {'pulses': beta[0], 'comparisons': beta[1]},
            'queries': queries,
        },
        'expected': expected,
        'actual': actual,
        'downstream_expected': expected,
        'downstream_actual': downstream,
        'code_paths': ['exchange/issuer.py', 'review/sync.py', 'review/constraints.py', 'archive/retrieval.py'],
        'oracle': 'The only way from S to U uses a1, a2 and b3, with weights 0 + 5 + 2. X has no edges.',
    }, sort_keys=True))
    print(json.dumps({
        'day_station_upper_us': daytime.upper_us,
        'three_station_review': conflict,
        'original_report_upper_us': downstream['bounds_us'][0],
        'corrected_review_upper_us': revised_report.results[0].upper_us,
    }, sort_keys=True))


def run_public_handoff(root: Path) -> None:
    """Limited-disclosure V2 issue, mixed V1/V2 audit, conflict and reopen."""
    source_path = root / 'public-recordings.sqlite'
    station_path = root / 'public-stations.sqlite'
    night_path = root / 'public-night.sqlite'

    with RevisionStore(source_path) as source, ArtifactCatalog(station_path) as outgoing:
        ids = {name: freeze_sample(source, sample)
               for name, sample in (('alpha', ALPHA), ('beta', BETA), ('gamma', GAMMA),
                                    ('prefix-alpha', PREFIX_ALPHA), ('prefix-beta', PREFIX_BETA))}
        alpha_v2 = fetch(outgoing, issue_public(source, outgoing, ids['alpha']).artifact_id).payload
        beta_v1 = fetch(outgoing, issue(source, outgoing, ids['beta']).artifact_id).payload
        gamma_v1 = fetch(outgoing, issue(source, outgoing, ids['gamma']).artifact_id).payload
        prefix_alpha_v2 = fetch(outgoing, issue_public(source, outgoing, ids['prefix-alpha']).artifact_id).payload
        prefix_beta_v1 = fetch(outgoing, issue(source, outgoing, ids['prefix-beta']).artifact_id).payload

    wire = json.loads(alpha_v2)
    assert set(wire['evidence']) == {'public', 'bounds'}
    assert 'hidden-shift' not in alpha_v2 and 'pulses' not in alpha_v2, 'private pulses must stay at the station'

    # The recording library is closed from here on: night shift only has fixed texts.
    queries = [('S', 'U'), ('U', 'S'), ('S', 'I'), ('I', 'I'), ('S', 'U')]
    with ArtifactCatalog(night_path) as night:
        alpha_only, alpha_receipt = audit_mixed(night, [alpha_v2], queries)
        mixed, mixed_receipt = audit_mixed(night, [beta_v1, alpha_v2], queries)
        prefix, _ = audit_mixed(night, [prefix_alpha_v2, prefix_beta_v1], [('S', 'D')])

        def summary(report):
            return [
                (row['upper_us'], [(item['origin']['station'], item['id']) for item in row['witness']])
                for row in report['results']
            ]

        if [row['upper_us'] for row in alpha_only['results']] != [3, None, None, 0, 3]:
            raise RuntimeError('limited-disclosure alpha-only bounds differ from the full evidence')
        expected_mixed = [
            (3, [('beta', 'b2'), ('alpha', 'a3')]),
            (None, []),
            (None, []),
            (0, []),
            (3, [('beta', 'b2'), ('alpha', 'a3')]),
        ]
        if summary(mixed) != expected_mixed:
            raise RuntimeError(f'mixed adjudication mismatch: {summary(mixed)!r}')
        if [(item['origin']['station'], item['id']) for item in prefix['results'][0]['witness']] != [
            ('alpha', 'a1'), ('alpha', 'a2'), ('beta', 'b2'),
        ]:
            raise RuntimeError('prefix tie-breaking witness mismatch')

        # Resubmissions count once; same-number different text is refused.
        deduped, _ = audit_mixed(night, [alpha_v2, alpha_v2, beta_v1], [('S', 'U')])
        if deduped['package_ids'] != mixed['package_ids']:
            raise RuntimeError('duplicate package resubmission was counted twice')
        altered = json.loads(alpha_v2)
        altered['evidence']['bounds'][0]['upper_us'] += 1
        try:
            audit_mixed(night, [alpha_v2, json.dumps(altered)], [])
        except InvalidPackage:
            intake = 'refused'
        else:
            raise RuntimeError('same-number conflicting package was accepted')

        try:
            audit_mixed(night, [alpha_v2, beta_v1, gamma_v1], [])
        except InconsistentConstraints:
            conflict = 'refused'
        else:
            raise RuntimeError('negative-cycle batch was accepted for an empty query')

    # Reopen the result library and claim the reports and receipts by id.
    with ArtifactCatalog(night_path) as reopened:
        alpha_report = fetch(reopened, alpha_receipt.artifact_id)
        mixed_report = fetch(reopened, mixed_receipt.artifact_id)
    assert alpha_report.receipt == alpha_receipt and mixed_report.receipt == mixed_receipt
    assert json.loads(mixed_report.payload)['results'][0]['upper_us'] == 3

    print('LIMITED_DISCLOSURE_HANDOFF ' + json.dumps({
        'alpha_only': [(r['upper_us'], [w['id'] for w in r['witness']]) for r in alpha_only['results']],
        'mixed': expected_mixed,
        'prefix_witness': [(w['origin']['station'], w['id']) for w in prefix['results'][0]['witness']],
        'intake_conflict': intake,
        'whole_batch_conflict': conflict,
        'report_ids': [alpha_receipt.artifact_id, mixed_receipt.artifact_id],
        'code_paths': [
            'exchange/public_issuer.py', 'exchange/v2.py', 'review/mixed.py',
            'review/macro_graph.py', 'archive/retrieval.py',
        ],
    }, sort_keys=True))


def main() -> None:
    with TemporaryDirectory(prefix='metering-shift-') as directory:
        root = Path(directory)
        run_shift(root)
        run_public_handoff(root)


if __name__ == '__main__':
    main()
