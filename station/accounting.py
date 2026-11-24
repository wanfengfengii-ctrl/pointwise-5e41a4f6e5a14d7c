from dataclasses import dataclass

from record.pulses import resolve_public_pulse
from record.revisions import RevisionOrigin
from record.storage import RevisionStore
from station.bounds import shortest_bounds
from station.checks import assert_feasible
from station.network import ConstraintEdge, graph_for_revision, local_node
from station.witness import trace_witness


@dataclass(frozen=True, slots=True)
class StationAccount:
    origin: RevisionOrigin
    start: str
    end: str
    upper_us: int | None
    witness: tuple[ConstraintEdge, ...]


def account(store: RevisionStore, revision_id: str, start: str, end: str) -> StationAccount:
    revision = store.get(revision_id)
    source = local_node(resolve_public_pulse(revision.pulses, start).name)
    target = local_node(resolve_public_pulse(revision.pulses, end).name)
    graph = graph_for_revision(revision)
    assert_feasible(graph)
    bounds = shortest_bounds(graph, source)
    return StationAccount(
        revision.origin, start, end, bounds.get(target), trace_witness(graph, bounds, source, target),
    )
