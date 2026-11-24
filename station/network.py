from collections.abc import Iterable
from dataclasses import dataclass

from record.comparisons import Comparison
from record.revisions import RecordingRevision, RevisionOrigin

Node = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConstraintEdge:
    start: Node
    end: Node
    origin: RevisionOrigin
    comparison: Comparison

    @property
    def upper_us(self) -> int:
        return self.comparison.upper_us

    def order_key(self) -> tuple:
        return self.origin, self.comparison.evidence_id, self.start, self.end, self.upper_us


@dataclass(frozen=True, slots=True)
class ConstraintGraph:
    nodes: tuple[Node, ...]
    edges: tuple[ConstraintEdge, ...]

    def relax(self, distances: dict[Node, int]) -> bool:
        changed = False
        for edge in self.edges:
            start_distance = distances.get(edge.start)
            if start_distance is None:
                continue
            candidate = start_distance + edge.upper_us
            current = distances.get(edge.end)
            if current is None or candidate < current:
                distances[edge.end] = candidate
                changed = True
        return changed


def build_graph(nodes: Iterable[Node], edges: Iterable[ConstraintEdge]) -> ConstraintGraph:
    registered = set(nodes)
    ordered_edges = tuple(sorted(set(edges), key=ConstraintEdge.order_key))
    for edge in ordered_edges:
        if edge.start not in registered or edge.end not in registered:
            raise ValueError('graph edge endpoint is not registered')
    return ConstraintGraph(tuple(sorted(registered)), ordered_edges)


def local_node(name: str) -> Node:
    return ('local', name)


def graph_for_revision(revision: RecordingRevision) -> ConstraintGraph:
    return build_graph(
        (local_node(pulse.name) for pulse in revision.pulses),
        (
            ConstraintEdge(local_node(item.start), local_node(item.end), revision.origin, item)
            for item in revision.comparisons
        ),
    )
