from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from record.pulses import Pulse, require_fields, require_identifier

MICROSECOND_UNIT = 'us'


@dataclass(frozen=True, slots=True)
class Comparison:
    evidence_id: str
    start: str
    end: str
    upper_us: int

    def to_payload(self) -> dict:
        return {
            'id': self.evidence_id,
            'start': self.start,
            'end': self.end,
            'upper_us': self.upper_us,
            'unit': MICROSECOND_UNIT,
        }


def build_comparisons(rows: Iterable[Mapping], pulses: Mapping[str, Pulse]) -> tuple[Comparison, ...]:
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, Mapping)):
        raise ValueError('comparisons must be a sequence of rows')
    comparisons = []
    identifiers = set()
    for entry in rows:
        row = require_fields(entry, {'id', 'start', 'end', 'upper_us', 'unit'}, 'comparison')
        evidence_id = require_identifier(row['id'], 'comparison id')
        if evidence_id in identifiers:
            raise ValueError(f'duplicate comparison id {evidence_id!r}')
        start = require_identifier(row['start'], 'comparison start')
        end = require_identifier(row['end'], 'comparison end')
        for endpoint in (start, end):
            if endpoint not in pulses:
                raise ValueError(f'comparison {evidence_id!r} refers to unknown pulse {endpoint!r}')
        if row['unit'] != MICROSECOND_UNIT:
            raise ValueError(f'comparison {evidence_id!r} must use microseconds (us)')
        upper = row['upper_us']
        if type(upper) is not int:
            raise ValueError(f'comparison {evidence_id!r} must have an integer upper_us')
        identifiers.add(evidence_id)
        comparisons.append(Comparison(evidence_id, start, end, upper))
    return tuple(comparisons)
