from station.network import ConstraintGraph


class InconsistentConstraints(ValueError):
    pass


def assert_feasible(graph: ConstraintGraph) -> None:
    if not graph.nodes:
        return
    # Initial zero distances are equivalent to a virtual origin connected to every node.
    distances = dict.fromkeys(graph.nodes, 0)
    for _ in graph.nodes:
        if not graph.relax(distances):
            return
    raise InconsistentConstraints('comparisons contain a negative cycle')
