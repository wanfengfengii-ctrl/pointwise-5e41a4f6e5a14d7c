from collections.abc import Iterable
from dataclasses import dataclass

from exchange.receiver import ReceivedPackage
from record.revisions import dump_measurement_json
from review.constraints import QueryBound


@dataclass(frozen=True, slots=True)
class AuditReport:
    package_ids: tuple[str, ...]
    results: tuple[QueryBound, ...]


def make_report(packages: Iterable[ReceivedPackage], results: Iterable[QueryBound]) -> AuditReport:
    return AuditReport(tuple(sorted(package.package_id for package in packages)), tuple(results))


def encode_report(report: AuditReport, report_id: str) -> str:
    results = []
    for bound in report.results:
        results.append({
            'position': bound.query.position,
            'start': bound.query.start,
            'end': bound.query.end,
            'upper_us': bound.upper_us,
            'witness': [
                {'origin': edge.origin.to_payload(), **edge.comparison.to_payload()}
                for edge in bound.witness
            ],
        })
    return dump_measurement_json({
        'version': 1, 'report_id': report_id, 'package_ids': list(report.package_ids), 'results': results,
    })
