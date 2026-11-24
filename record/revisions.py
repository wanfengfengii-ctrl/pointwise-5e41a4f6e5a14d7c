from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json

from record.comparisons import Comparison, build_comparisons
from record.pulses import Pulse, index_pulses, require_fields, require_identifier


@dataclass(frozen=True, order=True, slots=True)
class RevisionOrigin:
    station: str
    recording: str
    revision: str

    def __post_init__(self) -> None:
        require_identifier(self.station, 'station')
        require_identifier(self.recording, 'recording')
        require_identifier(self.revision, 'revision')

    def to_payload(self) -> dict:
        return {'station': self.station, 'recording': self.recording, 'revision': self.revision}

    @classmethod
    def from_payload(cls, payload: object) -> 'RevisionOrigin':
        row = require_fields(payload, {'station', 'recording', 'revision'}, 'origin')
        return cls(row['station'], row['recording'], row['revision'])


@dataclass(frozen=True, slots=True)
class RecordingRevision:
    origin: RevisionOrigin
    pulses: tuple[Pulse, ...]
    comparisons: tuple[Comparison, ...]
    supersedes: str | None = None

    def to_payload(self) -> dict:
        return {
            'origin': self.origin.to_payload(),
            'pulses': [pulse.to_payload() for pulse in self.pulses],
            'comparisons': [comparison.to_payload() for comparison in self.comparisons],
        }

    @classmethod
    def from_payload(cls, payload: object, *, supersedes: str | None = None) -> 'RecordingRevision':
        row = require_fields(payload, {'origin', 'pulses', 'comparisons'}, 'recording snapshot')
        origin = RevisionOrigin.from_payload(row['origin'])
        if not isinstance(row['pulses'], list) or not isinstance(row['comparisons'], list):
            raise ValueError('snapshot pulses and comparisons must be JSON arrays')
        return build_revision(
            origin.station, origin.recording, origin.revision,
            row['pulses'], row['comparisons'], supersedes=supersedes,
        )


def build_revision(
    station: str,
    recording: str,
    revision: str,
    pulses: Iterable[Mapping],
    comparisons: Iterable[Mapping],
    *,
    supersedes: str | None = None,
) -> RecordingRevision:
    origin = RevisionOrigin(station, recording, revision)
    if supersedes is not None:
        require_identifier(supersedes, 'superseded revision')
    pulse_index = index_pulses(pulses)
    originals = build_comparisons(comparisons, pulse_index)
    return RecordingRevision(origin, tuple(pulse_index.values()), originals, supersedes)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _reject_constant(name: str) -> None:
    raise ValueError(f'invalid JSON number {name}')


def _parse_integer(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        # Convert in bounded groups without changing the process integer conversion limit.
        negative = text.startswith('-')
        digits = text[1:] if negative else text
        value = 0
        for offset in range(0, len(digits), 9):
            group = digits[offset:offset + 9]
            value = value * 10 ** len(group) + int(group)
        return -value if negative else value


def load_measurement_json(text: str) -> object:
    return json.loads(
        text, object_pairs_hook=_unique_object, parse_int=_parse_integer,
        parse_constant=_reject_constant,
    )


def _integer_text(value: int) -> str:
    sign = '-' if value < 0 else ''
    remaining = abs(value)
    groups = []
    while remaining >= 10 ** 9:
        remaining, group = divmod(remaining, 10 ** 9)
        groups.append(f'{group:09d}')
    return sign + str(remaining) + ''.join(reversed(groups))


def _encode_large_integers(value: object) -> str:
    if type(value) is int:
        return _integer_text(value)
    if isinstance(value, dict):
        fields = (
            json.dumps(key) + ':' + _encode_large_integers(item)
            for key, item in sorted(value.items())
        )
        return '{' + ','.join(fields) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(map(_encode_large_integers, value)) + ']'
    return json.dumps(value, allow_nan=False)


def dump_measurement_json(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except ValueError:
        return _encode_large_integers(payload)
