from dataclasses import dataclass

from archive.catalog import ArtifactCatalog
from archive.receipts import SuccessReceipt, decode_receipt
from record.pulses import require_identifier


class ArtifactNotFound(KeyError):
    pass


class ArchiveIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchivedArtifact:
    artifact_id: str
    kind: str
    payload: str
    receipt: SuccessReceipt


def fetch(catalog: ArtifactCatalog, artifact_id: str) -> ArchivedArtifact:
    artifact_id = require_identifier(artifact_id, 'artifact id')
    pair = catalog.read_pair(artifact_id)
    if pair is None:
        raise ArtifactNotFound(artifact_id)
    kind, snapshot, receipt_kind, receipt_payload = pair
    if receipt_kind != kind or receipt_payload is None:
        raise ArchiveIntegrityError(f'artifact {artifact_id!r} has no matching success receipt')
    try:
        receipt = decode_receipt(receipt_payload, artifact_id, kind)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ArchiveIntegrityError(f'artifact {artifact_id!r} has an invalid receipt') from exc
    return ArchivedArtifact(artifact_id, kind, snapshot, receipt)
