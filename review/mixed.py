from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from archive.catalog import ArtifactCatalog
from archive.publication import publish
from archive.receipts import REPORT, SuccessReceipt
from exchange.evidence import FrozenEvidence
from exchange.receiver import InvalidPackage, ReceivedAnyPackage, ReceivedPackage, receive_any
from exchange.v2 import ReceivedV2Package
from record.revisions import RevisionOrigin, dump_measurement_json
from review.macro_graph import MacroEdge, Ref, assert_macro_feasible, macro_bounds
from review.queries import resolve_queries
from station.network import Node


@dataclass(frozen=True, slots=True)
class MixedScope:
    by_local: Mapping[tuple[RevisionOrigin, str], Node]
    public: Mapping[str, Node]


def _v1_facts(evidence: FrozenEvidence):
    return frozenset(evidence.pulses), frozenset(evidence.comparisons)


def _v2_facts(package: ReceivedV2Package):
    return frozenset(package.public), frozenset(package.bounds)


def _signature(package: ReceivedAnyPackage):
    if isinstance(package, ReceivedPackage):
        return 1, _v1_facts(package.evidence)
    return 2, _v2_facts(package)


def _origin_of(package: ReceivedAnyPackage) -> RevisionOrigin:
    if isinstance(package, ReceivedPackage):
        return package.evidence.origin
    return package.origin


def receive_mixed(packages: Iterable[str]) -> tuple[ReceivedAnyPackage, ...]:
    if not isinstance(packages, Iterable) or isinstance(packages, (str, bytes, Mapping)):
        raise InvalidPackage('audit packages must be a collection of fixed JSON payloads')
    by_id: dict[str, ReceivedAnyPackage] = {}
    by_origin: dict[RevisionOrigin, tuple[int, object]] = {}
    for payload in packages:
        package = receive_any(payload)
        origin = _origin_of(package)
        signature = _signature(package)

        existing = by_id.get(package.package_id)
        if existing is not None:
            # Same number and same facts: accept the resubmission only once.
            # Same number with different text is rejected outright.
            if _signature(existing) != signature or _origin_of(existing) != origin:
                raise InvalidPackage(f'package {package.package_id!r} has conflicting contents')
            continue

        if origin in by_origin:
            previous_version, previous_facts = by_origin[origin]
            if previous_version != signature[0]:
                raise InvalidPackage(
                    f'frozen origin {(origin.station, origin.recording, origin.revision)} '
                    'presents both V1 and V2 packages'
                )
            if previous_facts != signature[1]:
                raise InvalidPackage(
                    f'frozen origin {(origin.station, origin.recording, origin.revision)} '
                    'presents conflicting facts'
                )
        by_origin[origin] = signature
        by_id[package.package_id] = package
    return tuple(by_id.values())


def build_mixed_scope(packages: Iterable[ReceivedAnyPackage]) -> MixedScope:
    by_local: dict[tuple[RevisionOrigin, str], Node] = {}
    public: dict[str, Node] = {}
    for package in packages:
        if not isinstance(package, ReceivedPackage):
            continue
        origin = package.evidence.origin
        for pulse in package.evidence.pulses:
            if pulse.sync is None:
                node = ('temporary', origin.station, origin.recording, origin.revision, pulse.name)
            else:
                node = ('public', pulse.sync)
                public[pulse.sync] = node
            by_local[origin, pulse.name] = node
    for package in packages:
        if isinstance(package, ReceivedV2Package):
            for sync in package.public:
                public.setdefault(sync, ('public', sync))
    return MixedScope(MappingProxyType(by_local), MappingProxyType(public))


def build_mixed_edges(packages: Iterable[ReceivedAnyPackage], scope: MixedScope) -> tuple[MacroEdge, ...]:
    edges: list[MacroEdge] = []
    for package in packages:
        if isinstance(package, ReceivedPackage):
            origin = package.evidence.origin
            for item in package.evidence.comparisons:
                edges.append(MacroEdge(
                    scope.by_local[origin, item.start],
                    scope.by_local[origin, item.end],
                    item.upper_us,
                    (Ref(origin, item.evidence_id),),
                ))
        else:
            origin = package.origin
            for bound in package.bounds:
                edges.append(MacroEdge(
                    scope.public[bound.start],
                    scope.public[bound.end],
                    bound.upper_us,
                    tuple(Ref(origin, ref) for ref in bound.refs),
                ))
    return tuple(edges)


def _encode_report(report: dict, report_id: str) -> str:
    return dump_measurement_json({**report, 'report_id': report_id})


def audit_mixed(
    catalog: ArtifactCatalog,
    packages: Iterable[str],
    queries: Iterable[tuple[str, str]],
) -> tuple[dict, SuccessReceipt]:
    incoming = receive_mixed(packages)
    scope = build_mixed_scope(incoming)
    request = resolve_queries(queries, scope)
    edges = build_mixed_edges(incoming, scope)
    nodes = set(scope.public.values()) | set(scope.by_local.values()) | {
        endpoint for edge in edges for endpoint in (edge.start, edge.end)
    }

    # Whole-batch feasibility covers comparisons untouched by the queries and
    # is therefore also performed for an empty query list.
    assert_macro_feasible(nodes, edges)

    targets_by_source: dict[Node, list[Node]] = {}
    for query in request:
        targets_by_source.setdefault(query.start_node, [])
        if query.end_node not in targets_by_source[query.start_node]:
            targets_by_source[query.start_node].append(query.end_node)

    cache: dict[Node, dict[Node, object]] = {}
    for source, targets in targets_by_source.items():
        cache[source] = macro_bounds(nodes, edges, source, targets)

    results = []
    for query in request:
        bound = cache[query.start_node][query.end_node]
        results.append({
            'position': query.position,
            'start': query.start,
            'end': query.end,
            'upper_us': bound.upper_us,
            'witness': [ref.to_witness() for ref in bound.witness],
        })

    report = {
        'version': 2,
        'package_ids': sorted(package.package_id for package in incoming),
        'results': results,
    }
    receipt = publish(catalog, REPORT, lambda artifact_id: _encode_report(report, artifact_id))
    report = {**report, 'report_id': receipt.artifact_id}
    return report, receipt
