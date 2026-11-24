from dataclasses import dataclass

from record.comparisons import Comparison
from record.pulses import Pulse
from record.revisions import RecordingRevision, RevisionOrigin


@dataclass(frozen=True, slots=True)
class FrozenEvidence:
    origin: RevisionOrigin
    pulses: tuple[Pulse, ...]
    comparisons: tuple[Comparison, ...]


def collect_evidence(revision: RecordingRevision) -> FrozenEvidence:
    return FrozenEvidence(revision.origin, revision.pulses, revision.comparisons)


def encode_evidence(evidence: FrozenEvidence) -> dict:
    return {
        'origin': evidence.origin.to_payload(),
        'pulses': [pulse.to_payload() for pulse in evidence.pulses],
        'comparisons': [item.to_payload() for item in evidence.comparisons],
    }


def decode_evidence(payload: dict, claimed_origin: RevisionOrigin) -> FrozenEvidence:
    snapshot = RecordingRevision.from_payload(payload)
    if snapshot.origin != claimed_origin:
        raise ValueError('station envelope origin differs from evidence origin')
    return FrozenEvidence(snapshot.origin, snapshot.pulses, snapshot.comparisons)
