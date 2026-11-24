from archive.catalog import ArtifactCatalog
from archive.publication import publish
from archive.receipts import STATION_PACKAGE, SuccessReceipt
from exchange.envelope import V1Envelope, encode_envelope
from exchange.evidence import collect_evidence, encode_evidence
from record.storage import RevisionStore
from station.checks import assert_feasible
from station.network import graph_for_revision


def issue(store: RevisionStore, catalog: ArtifactCatalog, revision_id: str) -> SuccessReceipt:
    revision = store.get(revision_id)
    assert_feasible(graph_for_revision(revision))
    evidence = collect_evidence(revision)
    wire_evidence = encode_evidence(evidence)

    def payload_for(package_id: str) -> str:
        return encode_envelope(V1Envelope(package_id, evidence.origin, wire_evidence))

    return publish(catalog, STATION_PACKAGE, payload_for)
