from dataclasses import dataclass

from exchange.errors import InvalidPackage
from record.pulses import require_fields, require_identifier
from record.revisions import RevisionOrigin, dump_measurement_json, load_measurement_json

V2_VERSION = 2


@dataclass(frozen=True, slots=True)
class PublicBound:
    start: str
    end: str
    upper_us: int
    refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReceivedV2Package:
    package_id: str
    origin: RevisionOrigin
    public: tuple[str, ...]
    bounds: tuple[PublicBound, ...]


def encode_v2_envelope(
    package_id: str,
    origin: RevisionOrigin,
    public: tuple[str, ...],
    bounds: tuple[PublicBound, ...],
) -> str:
    return dump_measurement_json({
        'version': V2_VERSION,
        'package_id': package_id,
        'origin': origin.to_payload(),
        'evidence': {
            'public': list(public),
            'bounds': [
                {
                    'start': bound.start,
                    'end': bound.end,
                    'upper_us': bound.upper_us,
                    'refs': list(bound.refs),
                }
                for bound in bounds
            ],
        },
    })


def decode_v2_envelope(payload: str) -> ReceivedV2Package:
    try:
        if not isinstance(payload, str):
            raise ValueError('station package must be JSON text')
        row = require_fields(
            load_measurement_json(payload),
            {'version', 'package_id', 'origin', 'evidence'},
            'station envelope',
        )
        if type(row['version']) is not int or row['version'] != V2_VERSION:
            raise ValueError('expected station envelope version 2')
        package_id = require_identifier(row['package_id'], 'package id')
        origin = RevisionOrigin.from_payload(row['origin'])
        evidence = require_fields(row['evidence'], {'public', 'bounds'}, 'V2 evidence')

        public_rows = evidence['public']
        if not isinstance(public_rows, list):
            raise ValueError('V2 evidence public must be a JSON array')
        public: list[str] = []
        declared: set[str] = set()
        for sync in public_rows:
            identifier = require_identifier(sync, 'public sync identifier')
            if identifier in declared:
                raise ValueError(f'duplicate public sync identifier {identifier!r}')
            declared.add(identifier)
            public.append(identifier)

        bound_rows = evidence['bounds']
        if not isinstance(bound_rows, list):
            raise ValueError('V2 evidence bounds must be a JSON array')
        bounds: list[PublicBound] = []
        seen_pairs: set[tuple[str, str]] = set()
        for entry in bound_rows:
            bound_row = require_fields(entry, {'start', 'end', 'upper_us', 'refs'}, 'V2 bound')
            start = require_identifier(bound_row['start'], 'bound start')
            end = require_identifier(bound_row['end'], 'bound end')
            if start not in declared or end not in declared:
                raise ValueError(f'bound {start!r}->{end!r} uses an undeclared public sync identifier')
            if start == end:
                raise ValueError('V2 bounds must connect distinct public sync identifiers')
            if (start, end) in seen_pairs:
                raise ValueError(f'duplicate directed bound {start!r}->{end!r}')
            seen_pairs.add((start, end))
            upper = bound_row['upper_us']
            if type(upper) is not int:
                raise ValueError('V2 bound upper_us must be an exact integer')
            refs_row = bound_row['refs']
            if not isinstance(refs_row, list) or not refs_row:
                raise ValueError('V2 bound refs must be a non-empty ordered array')
            refs = tuple(require_identifier(ref, 'original comparison id') for ref in refs_row)
            bounds.append(PublicBound(start, end, upper, refs))
    except (ValueError, RecursionError) as exc:
        raise InvalidPackage(str(exc)) from exc
    return ReceivedV2Package(package_id, origin, tuple(public), tuple(bounds))
