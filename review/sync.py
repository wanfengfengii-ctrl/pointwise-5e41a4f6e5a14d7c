from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from exchange.receiver import ReceivedPackage
from record.revisions import RevisionOrigin
from station.network import Node


@dataclass(frozen=True, slots=True)
class PulseScope:
    by_local: Mapping[tuple[RevisionOrigin, str], Node]
    public: Mapping[str, Node]


def join_pulses(packages: Iterable[ReceivedPackage]) -> PulseScope:
    by_local: dict[tuple[RevisionOrigin, str], Node] = {}
    public: dict[str, Node] = {}
    for package in packages:
        evidence = package.evidence
        origin = evidence.origin
        for pulse in evidence.pulses:
            if pulse.sync is None:
                node = ('temporary', origin.station, origin.recording, origin.revision, pulse.name)
            else:
                node = ('public', pulse.sync)
                public[pulse.sync] = node
            by_local[origin, pulse.name] = node
    return PulseScope(MappingProxyType(by_local), MappingProxyType(public))
