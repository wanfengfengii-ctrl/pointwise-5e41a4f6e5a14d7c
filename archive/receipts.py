from dataclasses import dataclass
import json
from uuid import uuid4

from record.pulses import require_fields, require_identifier

STATION_PACKAGE = 'station-package'
REPORT = 'report'
ARTIFACT_KINDS = (STATION_PACKAGE, REPORT)


@dataclass(frozen=True, slots=True)
class SuccessReceipt:
    receipt_id: str
    artifact_id: str
    kind: str

    def __post_init__(self) -> None:
        require_identifier(self.receipt_id, 'receipt id')
        require_identifier(self.artifact_id, 'artifact id')
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError('unknown receipt artifact kind')


def make_receipt(artifact_id: str, kind: str) -> SuccessReceipt:
    return SuccessReceipt(f'receipt-{uuid4().hex}', artifact_id, kind)


def encode_receipt(receipt: SuccessReceipt) -> str:
    return json.dumps({
        'version': 1,
        'receipt_id': receipt.receipt_id,
        'artifact_id': receipt.artifact_id,
        'kind': receipt.kind,
    }, sort_keys=True, separators=(',', ':'))


def decode_receipt(payload: str, artifact_id: str, kind: str) -> SuccessReceipt:
    row = require_fields(json.loads(payload), {'version', 'receipt_id', 'artifact_id', 'kind'}, 'receipt')
    if type(row['version']) is not int or row['version'] != 1:
        raise ValueError('unknown receipt version')
    receipt = SuccessReceipt(row['receipt_id'], row['artifact_id'], row['kind'])
    if (receipt.artifact_id, receipt.kind) != (artifact_id, kind):
        raise ValueError('receipt does not match the archived artifact')
    return receipt
