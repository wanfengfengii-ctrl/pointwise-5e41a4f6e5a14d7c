from collections.abc import Callable
import sqlite3
from uuid import uuid4

from archive.catalog import ArtifactCatalog
from archive.receipts import ARTIFACT_KINDS, STATION_PACKAGE, SuccessReceipt, encode_receipt, make_receipt


class PublicationError(RuntimeError):
    pass


def publish(catalog: ArtifactCatalog, kind: str, make_payload: Callable[[str], str]) -> SuccessReceipt:
    if kind not in ARTIFACT_KINDS:
        raise ValueError('unsupported artifact kind')
    prefix = 'pkg' if kind == STATION_PACKAGE else 'report'
    artifact_id = f'{prefix}-{uuid4().hex}'
    receipt = make_receipt(artifact_id, kind)
    snapshot = make_payload(artifact_id)
    receipt_payload = encode_receipt(receipt)
    try:
        with catalog.transaction():
            catalog.insert_snapshot(artifact_id, kind, snapshot)
            catalog.insert_receipt(artifact_id, kind, receipt_payload)
    except sqlite3.Error as exc:
        raise PublicationError(f'{kind} publication failed: {exc}') from exc
    return receipt
