from collections.abc import Iterable, Mapping
from uuid import uuid4

from record.revisions import build_revision
from record.storage import RevisionStore


def freeze(
    store: RevisionStore,
    station: str,
    recording: str,
    pulses: Iterable[Mapping],
    comparisons: Iterable[Mapping],
    *,
    supersedes: str | None = None,
) -> str:
    revision = build_revision(
        station, recording, f'rev-{uuid4().hex}', pulses, comparisons, supersedes=supersedes,
    )
    return store.append(revision)
