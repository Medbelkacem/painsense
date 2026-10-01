"""Digests over the written files.

Separate from `storage` so the manifest can be taken without importing the writer, and so
the same digest function is used when a recording is written and when it is read back — the
point of a digest being that both sides compute it the same way.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def digest_of_session(files: list[dict]) -> str:
    """One digest over a session's files, by name then content digest.

    Names go in as well as content so renaming a file changes the session digest, and the
    order is fixed so the result is reproducible.
    """
    digest = hashlib.sha256()
    for entry in sorted(files, key=lambda item: item["name"]):
        digest.update(entry["name"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
