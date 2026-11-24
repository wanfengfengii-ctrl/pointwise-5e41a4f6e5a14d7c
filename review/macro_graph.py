from collections.abc import Iterable
from dataclasses import dataclass

from record.revisions import RevisionOrigin

MacroNode = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ref:
    origin: RevisionOrigin
    comparison_id: str

    def order_key(self) -> tuple[str, str, str, str]:
        return (self.origin.station, self.origin.recording, self.origin.revision, self.comparison_id)

    def to_witness(self) -> dict:
        return {'origin': self.origin.to_payload(), 'id': self.comparison_id}


@dataclass(frozen=True, slots=True)
class MacroEdge:
    start: MacroNode
    end: MacroNode
    upper_us: int
    refs: tuple[Ref, ...]

    def order_key(self) -> tuple:
        return (
            self.start, self.end, self.upper_us,
            tuple(ref.order_key() for ref in self.refs),
        )


@dataclass(frozen=True, slots=True)
class MacroBound:
    upper_us: int | None
    witness: tuple[Ref, ...]


def _ordered_edges(edges: Iterable[MacroEdge]) -> tuple[MacroEdge, ...]:
    return tuple(sorted(set(edges), key=MacroEdge.order_key))


def assert_macro_feasible(nodes: Iterable[MacroNode], edges: Iterable[MacroEdge]) -> None:
    node_set = set(nodes)
    ordered = _ordered_edges(edges)
    for edge in ordered:
        if edge.start not in node_set or edge.end not in node_set:
            raise ValueError('macro edge endpoint is not registered')
    if not node_set:
        return
    # Initial zero distances are equivalent to a virtual origin connected to every node.
    distances = dict.fromkeys(node_set, 0)
    total_nodes = len(node_set)
    for _ in range(total_nodes):
        changed = False
        for edge in ordered:
            candidate = distances[edge.start] + edge.upper_us
            if candidate < distances[edge.end]:
                distances[edge.end] = candidate
                changed = True
        if not changed:
            return
    # With all shortest paths settled after the passes above, any further
    # relaxation proves a negative cycle.
    for edge in ordered:
        if distances[edge.start] + edge.upper_us < distances[edge.end]:
            from station.checks import InconsistentConstraints
            raise InconsistentConstraints('comparisons contain a negative cycle')


def macro_bounds(
    nodes: Iterable[MacroNode],
    edges: Iterable[MacroEdge],
    source: MacroNode,
    targets: Iterable[MacroNode],
) -> dict[MacroNode, MacroBound]:
    """Shortest directed bounds with the joint adjudication tie rules.

    Order of preference for equal end points: smallest exact upper bound,
    then the fewest original comparisons, then the lexicographically smallest
    complete ordered reference sequence keyed by
    (station, recording, revision, id).
    """
    node_tuple = tuple(sorted(set(nodes)))
    node_set = set(node_tuple)
    if source not in node_set:
        raise ValueError('bound source is not a registered graph node')
    for edge in _ordered_edges(edges):
        if edge.start not in node_set or edge.end not in node_set:
            raise ValueError('macro edge endpoint is not registered')
    ordered = _ordered_edges(edges)

    distances = {source: 0}
    for _ in range(len(node_tuple) - 1):
        changed = False
        for edge in ordered:
            current = distances.get(edge.start)
            if current is None:
                continue
            candidate = current + edge.upper_us
            known = distances.get(edge.end)
            if known is None or candidate < known:
                distances[edge.end] = candidate
                changed = True
        if not changed:
            break

    # Tight edges preserve every shortest distance; select the chain by the
    # reference count and the full ordered reference sequence.
    tight = tuple(
        edge for edge in ordered
        if distances.get(edge.start) is not None
        and distances.get(edge.end) == distances[edge.start] + edge.upper_us
    )
    labels: dict[MacroNode, tuple[int, tuple[tuple[str, str, str, str], ...]]] = {
        source: (0, ()),
    }
    predecessor: dict[MacroNode, MacroEdge] = {}
    for _ in range(len(node_tuple) - 1):
        changed = False
        for edge in tight:
            current = labels.get(edge.start)
            if current is None:
                continue
            candidate = (
                current[0] + len(edge.refs),
                current[1] + tuple(ref.order_key() for ref in edge.refs),
            )
            known = labels.get(edge.end)
            if known is None or candidate < known:
                labels[edge.end] = candidate
                predecessor[edge.end] = edge
                changed = True
        if not changed:
            break

    ref_lookup = {ref.order_key(): ref for edge in ordered for ref in edge.refs}
    results: dict[MacroNode, MacroBound] = {}
    for target in targets:
        if target == source:
            results[target] = MacroBound(0, ())
        elif target not in distances:
            results[target] = MacroBound(None, ())
        else:
            edge_chain: list[MacroEdge] = []
            current = target
            while current != source:
                edge = predecessor[current]
                edge_chain.append(edge)
                current = edge.start
            witness = tuple(ref for edge in reversed(edge_chain) for ref in edge.refs)
            ordered_keys = tuple(ref.order_key() for ref in witness)
            if ordered_keys != labels[target][1] or len(witness) != labels[target][0]:
                raise RuntimeError('shortest-bound witness reconstruction failed')
            if any(key not in ref_lookup for key in ordered_keys):
                raise RuntimeError('shortest-bound witness references an unknown original comparison')
            results[target] = MacroBound(distances[target], witness)
    return results
