from collections import defaultdict, deque
from collections.abc import Mapping

from station.network import ConstraintEdge, ConstraintGraph, Node


def trace_witness(
    graph: ConstraintGraph,
    distances: Mapping[Node, int],
    start: Node,
    end: Node,
) -> tuple[ConstraintEdge, ...]:
    if start == end or end not in distances:
        return ()
    outgoing: dict[Node, list[ConstraintEdge]] = defaultdict(list)
    for edge in graph.edges:
        source_distance = distances.get(edge.start)
        if source_distance is not None and distances.get(edge.end) == source_distance + edge.upper_us:
            outgoing[edge.start].append(edge)

    visited = {start}
    predecessor: dict[Node, ConstraintEdge] = {}
    queue = deque([start])
    while queue and end not in visited:
        current = queue.popleft()
        for edge in outgoing[current]:
            if edge.end not in visited:
                visited.add(edge.end)
                predecessor[edge.end] = edge
                queue.append(edge.end)

    if end not in predecessor:
        raise RuntimeError('finite distance has no chain of tight original comparisons')
    chain = []
    current = end
    while current != start:
        edge = predecessor[current]
        chain.append(edge)
        current = edge.start
    return tuple(reversed(chain))
