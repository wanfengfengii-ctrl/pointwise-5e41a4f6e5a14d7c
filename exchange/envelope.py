from dataclasses import dataclass

from record.pulses import require_fields, require_identifier
from record.revisions import RevisionOrigin, dump_measurement_json, load_measurement_json


class InvalidEnvelope(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class V1Envelope:
    package_id: str
    origin: RevisionOrigin
    evidence: dict


def encode_envelope(envelope: V1Envelope) -> str:
    return dump_measurement_json({
        'version': 1,
        'package_id': envelope.package_id,
        'origin': envelope.origin.to_payload(),
        'evidence': envelope.evidence,
    })


def decode_envelope(payload: str) -> V1Envelope:
    try:
        if not isinstance(payload, str):
            raise ValueError('station package must be JSON text')
        row = require_fields(
            load_measurement_json(payload), {'version', 'package_id', 'origin', 'evidence'}, 'station envelope',
        )
        if type(row['version']) is not int or row['version'] != 1:
            raise ValueError('expected station envelope version 1')
        package_id = require_identifier(row['package_id'], 'package id')
        origin = RevisionOrigin.from_payload(row['origin'])
        if not isinstance(row['evidence'], dict):
            raise ValueError('station evidence must be an object')
        return V1Envelope(package_id, origin, row['evidence'])
    except (ValueError, RecursionError) as exc:
        raise InvalidEnvelope(str(exc)) from exc
