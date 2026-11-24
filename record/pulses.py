from collections.abc import Iterable, Mapping
from dataclasses import dataclass


def require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or '\x00' in value:
        raise ValueError(f'{field} must be a nonempty identifier without surrounding whitespace')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError(f'{field} must be valid Unicode') from exc
    return value


def require_fields(value: object, fields: set[str], label: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f'{label} requires fields {", ".join(sorted(fields))}')
    return value


@dataclass(frozen=True, slots=True)
class Pulse:
    name: str
    sync: str | None

    def to_payload(self) -> dict:
        return {'name': self.name, 'sync': self.sync}


def index_pulses(declarations: Iterable[Mapping]) -> dict[str, Pulse]:
    if not isinstance(declarations, Iterable) or isinstance(declarations, (str, bytes, Mapping)):
        raise ValueError('pulses must be a sequence of declarations')
    by_name: dict[str, Pulse] = {}
    sync_ids: set[str] = set()
    for declaration in declarations:
        row = require_fields(declaration, {'name', 'sync'}, 'pulse')
        name = require_identifier(row['name'], 'pulse name')
        if name in by_name:
            raise ValueError(f'duplicate pulse name {name!r}')
        sync = row['sync']
        if sync is not None:
            sync = require_identifier(sync, 'sync identifier')
            if sync in sync_ids:
                raise ValueError(f'duplicate sync identifier {sync!r} in recording')
            sync_ids.add(sync)
        by_name[name] = Pulse(name, sync)
    return by_name


def resolve_public_pulse(pulses: Iterable[Pulse], name: str) -> Pulse:
    name = require_identifier(name, 'query pulse name')
    for pulse in pulses:
        if pulse.name == name and pulse.sync is not None:
            return pulse
    raise ValueError(f'no public pulse named {name!r} in this revision')
