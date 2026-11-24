from dataclasses import dataclass
from typing import Union

from exchange.envelope import decode_envelope
from exchange.errors import InvalidPackage
from exchange.evidence import FrozenEvidence, decode_evidence
from exchange.v2 import ReceivedV2Package, decode_v2_envelope
from record.revisions import load_measurement_json


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


ReceivedAnyPackage = Union[ReceivedPackage, ReceivedV2Package]


def receive_any(payload: str) -> ReceivedAnyPackage:
    """Read either a V1 full-evidence package or a V2 limited-disclosure package."""
    if not isinstance(payload, str):
        raise InvalidPackage('station package must be JSON text')
    try:
        wire = load_measurement_json(payload)
    except (ValueError, RecursionError) as exc:
        raise InvalidPackage(str(exc)) from exc
    if not isinstance(wire, dict) or type(wire.get('version')) is not int:
        raise InvalidPackage('station envelope requires an integer version')
    if wire['version'] == 1:
        return receive(payload)
    if wire['version'] == 2:
        return decode_v2_envelope(payload)
    raise InvalidPackage(f'unsupported station envelope version {wire["version"]}')
