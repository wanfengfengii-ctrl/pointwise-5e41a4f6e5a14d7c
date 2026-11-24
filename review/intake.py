from collections.abc import Iterable, Mapping

from archive.catalog import ArtifactCatalog
from archive.publication import publish
from archive.receipts import REPORT, SuccessReceipt
from exchange.receiver import InvalidPackage, ReceivedPackage, receive
from review.constraints import build_joint_graph, evaluate_joint_bounds
from review.queries import resolve_queries
from review.report import AuditReport, encode_report, make_report
from review.sync import join_pulses


def _receive_packages(payloads: Iterable[str]) -> tuple[ReceivedPackage, ...]:
    if not isinstance(payloads, Iterable) or isinstance(payloads, (str, bytes, Mapping)):
        raise InvalidPackage('audit packages must be a collection of fixed JSON payloads')
    by_id: dict[str, ReceivedPackage] = {}
    by_origin = {}
    for payload in payloads:
        package = receive(payload)
        evidence = package.evidence
        facts = (frozenset(evidence.pulses), frozenset(evidence.comparisons))
        existing = by_id.setdefault(package.package_id, package)
        if existing.evidence.origin != evidence.origin:
            raise InvalidPackage(f'package {package.package_id!r} has conflicting origins')
        if by_origin.setdefault(evidence.origin, facts) != facts:
            raise InvalidPackage(f'conflicting evidence for revision {evidence.origin.revision!r}')
    return tuple(by_id.values())


def audit(
    catalog: ArtifactCatalog,
    packages: Iterable[str],
    queries: Iterable[tuple[str, str]],
) -> tuple[AuditReport, SuccessReceipt]:
    incoming = _receive_packages(packages)
    scope = join_pulses(incoming)
    request = resolve_queries(queries, scope)
    graph = build_joint_graph(incoming, scope)
    report = make_report(incoming, evaluate_joint_bounds(graph, request))
    receipt = publish(catalog, REPORT, lambda artifact_id: encode_report(report, artifact_id))
    return report, receipt
