"""The two digests this pipeline keeps, and why they are not the same digest.

`metadata_fingerprint` covers what the publisher *says* about a dataset: its title,
licence, stated version, stated update time, size and download URL. It changes when the
publisher revises the listing, and it is computable from a discovery call that downloads
no data at all. That is what makes "is there anything new?" answerable cheaply every few
hours.

`content_fingerprint` is the SHA-256 of the bytes that arrived. It is the duplicate check:
a publisher that bumps a version number without changing a byte produces a new metadata
fingerprint and the same content fingerprint, and the pipeline records that it already
holds this data instead of storing it twice.

Both are stable across machines and across Python runs, which rules out `hash()` and
anything that iterates a dict in insertion order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CHUNK = 1 << 20


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def of_metadata(fields: dict[str, Any]) -> str:
    payload = json.dumps(_canonical(fields), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def of_directory(directory: Path) -> str:
    """A digest over every file in a directory, by relative path then content.

    Paths go into the digest as well as bytes, so two versions holding the same files
    under different names are correctly seen as different.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_of(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
