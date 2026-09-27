"""Keyset (cursor) pagination on (created_at, id).

Unlike OFFSET, a keyset page is stable while rows are inserted, and the database
seeks straight to the position via an index instead of scanning skipped rows.
The cursor is opaque to clients but not secret: forging one only changes the
position, never the organization/visibility filters.
"""

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.errors import UnprocessableError

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class KeysetCursor:
    created_at: datetime
    id: uuid.UUID


def encode_cursor(cursor: KeysetCursor) -> str:
    payload = json.dumps([cursor.created_at.isoformat(), str(cursor.id)])
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(raw: str) -> KeysetCursor:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        created_at, row_id = json.loads(base64.urlsafe_b64decode(padded))
        cursor = KeysetCursor(datetime.fromisoformat(created_at), uuid.UUID(row_id))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise UnprocessableError("Invalid cursor") from exc
    if cursor.created_at.tzinfo is None:
        raise UnprocessableError("Invalid cursor")
    return cursor
