from collections.abc import Iterable
from dataclasses import dataclass

from exchange.receiver import ReceivedPackage
from review.queries import AuditQuery
from review.sync import PulseScope
from station.bounds import shortest_bounds
from station.checks import assert_feasible
from station.network import ConstraintEdge, ConstraintGraph, Node, build_graph
from station.witness import trace_witness


@dataclass(frozen=True, slots=True)
class QueryBound:
    query: AuditQuery
    upper_us: int | None
    witness: tuple[ConstraintEdge, ...]


def build_joint_graph(packages: Iterable[ReceivedPackage], scope: PulseScope) -> ConstraintGraph:
    edges = []
    for package in packages:
        origin = package.evidence.origin
        for item in package.evidence.comparisons:
            edges.append(ConstraintEdge(
                scope.by_local[origin, item.start], scope.by_local[origin, item.end], origin, item,
            ))
    return build_graph(scope.by_local.values(), edges)


def evaluate_joint_bounds(graph: ConstraintGraph, queries: Iterable[AuditQuery]) -> tuple[QueryBound, ...]:
    assert_feasible(graph)
    by_source: dict[Node, dict[Node, int]] = {}
    results = []
    for query in queries:
        start, end = query.start_node, query.end_node
        if start not in by_source:
            by_source[start] = shortest_bounds(graph, start)
        distances = by_source[start]
        results.append(QueryBound(query, distances.get(end), trace_witness(graph, distances, start, end)))
    return tuple(results)
