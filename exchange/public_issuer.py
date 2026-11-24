from archive.catalog import ArtifactCatalog
from archive.publication import publish
from archive.receipts import STATION_PACKAGE, SuccessReceipt
from exchange.v2 import PublicBound, encode_v2_envelope
from record.storage import RevisionStore
from review.macro_graph import MacroBound, MacroEdge, Ref, macro_bounds
from station.checks import assert_feasible
from station.network import graph_for_revision, local_node


def _public_pairs(revision):
    public = tuple(sorted(pulse.sync for pulse in revision.pulses if pulse.sync is not None))
    node_of = {pulse.sync: local_node(pulse.name) for pulse in revision.pulses if pulse.sync is not None}
    return public, node_of


def collect_public_bounds(revision) -> tuple[tuple[str, ...], tuple[PublicBound, ...]]:
    """Project a frozen revision onto public sync identifiers only.

    Private pulses, private endpoints and per-edge weights stay at the
    station; only public identifiers, public-to-public directed bounds and
    the ordered original comparison ids leave the building.
    """
    public, node_of = _public_pairs(revision)
    edges = tuple(
        MacroEdge(
            local_node(item.start),
            local_node(item.end),
            item.upper_us,
            (Ref(revision.origin, item.evidence_id),),
        )
        for item in revision.comparisons
    )
    nodes = tuple(local_node(pulse.name) for pulse in revision.pulses)
    bounds: list[PublicBound] = []
    for start in public:
        targets = [node_of[end] for end in public if end != start]
        if not targets:
            continue
        result = macro_bounds(nodes, edges, node_of[start], targets)
        for end in public:
            if end == start:
                continue
            bound: MacroBound = result[node_of[end]]
            if bound.upper_us is None:
                continue
            bounds.append(PublicBound(
                start, end, bound.upper_us, tuple(ref.comparison_id for ref in bound.witness),
            ))
    return tuple(public), tuple(bounds)


def issue_public(store: RevisionStore, catalog: ArtifactCatalog, revision_id: str) -> SuccessReceipt:
    revision = store.get(revision_id)
    # The whole frozen revision, including disconnected components, must be
    # feasible before any limited-disclosure package can be issued.
    assert_feasible(graph_for_revision(revision))
    public, bounds = collect_public_bounds(revision)

    def payload_for(package_id: str) -> str:
        return encode_v2_envelope(package_id, revision.origin, public, bounds)

    return publish(catalog, STATION_PACKAGE, payload_for)
