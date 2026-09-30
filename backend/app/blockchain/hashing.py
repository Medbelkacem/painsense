"""Canonical serialisation and record hashing.

A hash is only evidence if two people who hold the same record compute the same digest.
That needs one unambiguous byte encoding, so: keys sorted, no insignificant whitespace,
UTF-8, and every value reduced to a form JSON can hold without losing precision.

Datetimes are normalised to UTC before formatting. A record hashed as +01:00 and rehashed
as UTC would otherwise appear tampered with.
"""

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

ZERO_HASH = "0" * 64


def _plain(value):
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical(payload: dict) -> bytes:
    return json.dumps(
        _plain(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
