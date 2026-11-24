from station.network import ConstraintGraph, Node


def shortest_bounds(graph: ConstraintGraph, source: Node) -> dict[Node, int]:
    """Return finite distances from source in a graph already checked for feasibility."""
    if source not in graph.nodes:
        raise ValueError('bound source is not a registered graph node')
    distances = {source: 0}
    for _ in graph.nodes[1:]:
        if not graph.relax(distances):
            break
    return distances
