from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from review.sync import PulseScope
from station.network import Node


class UnknownQueryEndpoint(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuditQuery:
    position: int
    start: str
    end: str
    start_node: Node
    end_node: Node


def resolve_queries(queries: Iterable[tuple[str, str]], scope: PulseScope) -> tuple[AuditQuery, ...]:
    if not isinstance(queries, Iterable) or isinstance(queries, (str, bytes, Mapping)):
        raise UnknownQueryEndpoint('queries must be an ordered collection of pairs')
    resolved = []
    for position, pair in enumerate(queries):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise UnknownQueryEndpoint(f'query {position} must be a pair')
        start, end = pair
        for identifier in (start, end):
            if not isinstance(identifier, str) or identifier not in scope.public:
                raise UnknownQueryEndpoint(f'query {position} has an unknown sync identifier {identifier!r}')
        resolved.append(AuditQuery(position, start, end, scope.public[start], scope.public[end]))
    return tuple(resolved)
