from dataclasses import dataclass

from exchange.envelope import decode_envelope
from exchange.evidence import FrozenEvidence, decode_evidence


class InvalidPackage(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReceivedPackage:
    package_id: str
    evidence: FrozenEvidence


def receive(payload: str) -> ReceivedPackage:
    try:
        envelope = decode_envelope(payload)
        evidence = decode_evidence(envelope.evidence, envelope.origin)
    except ValueError as exc:
        raise InvalidPackage(str(exc)) from exc
    return ReceivedPackage(envelope.package_id, evidence)
