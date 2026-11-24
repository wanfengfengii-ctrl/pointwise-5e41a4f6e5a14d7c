import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive import ArtifactCatalog, fetch
from exchange import issue
from record import RevisionStore, freeze
from review import audit
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


def main() -> None:
    with TemporaryDirectory(prefix='metering-shift-') as directory:
        run_shift(Path(directory))


if __name__ == '__main__':
    main()
