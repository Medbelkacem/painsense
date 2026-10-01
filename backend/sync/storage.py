"""Where acquired datasets live on disk.

One directory per acquired version, named by source, dataset and version, so the layout
is readable without the database and a version can be deleted by removing one directory.
The database holds the key; this module is the only thing that turns a key into a path, so
moving to object storage later means changing `resolve` and the two callers that write.

Archives are extracted through `safe_extract`, which refuses absolute paths, parent
traversal and symlinks. A zip from a public dataset site is untrusted input.
"""

from __future__ import annotations

import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from config import get_settings

FILESYSTEM = "filesystem"
_SAFE = re.compile(r"[^a-z0-9._-]+")


class UnsafeArchive(RuntimeError):
    """An archive member would have been written outside its destination."""


def slug(value: str, *, limit: int = 80) -> str:
    cleaned = _SAFE.sub("-", value.strip().casefold()).strip("-.")
    return (cleaned or "unnamed")[:limit]


def key_for(source_code: str, external_id: str, version: str) -> str:
    return f"{slug(source_code, limit=32)}/{slug(external_id)}/{slug(version, limit=40)}"


def root() -> Path:
    return get_settings().external_dataset_path


def resolve(key: str) -> Path:
    """Turn a stored key into an absolute path, refusing anything that escapes the root."""
    base = root().resolve()
    path = (base / key).resolve()
    if path != base and base not in path.parents:
        raise UnsafeArchive(f"storage key {key!r} escapes the dataset root")
    return path


def prepare(key: str) -> Path:
    path = resolve(key)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def discard(key: str) -> None:
    path = resolve(key)
    if path.exists():
        shutil.rmtree(path)


@dataclass(frozen=True)
class StoredFile:
    name: str
    bytes: int
    sha256: str

    def as_dict(self) -> dict:
        return {"name": self.name, "bytes": self.bytes, "sha256": self.sha256}


def _reject(name: str, destination: Path) -> Path:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or name.startswith("/"):
        raise UnsafeArchive(f"archive member {name!r} points outside the destination")
    target = (destination / candidate).resolve()
    if destination.resolve() not in target.parents and target != destination.resolve():
        raise UnsafeArchive(f"archive member {name!r} resolves outside the destination")
    return target


def safe_extract(archive: Path, destination: Path, *, max_bytes: int) -> list[Path]:
    """Unpack a zip or tar, refusing traversal, symlinks and a decompression bomb.

    `max_bytes` is checked against the declared uncompressed total before anything is
    written, which is what stops a few kilobytes of zip from becoming a full volume.
    """
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        return _extract_zip(archive, destination, max_bytes)
    if tarfile.is_tarfile(archive):
        return _extract_tar(archive, destination, max_bytes)
    return []


def _extract_zip(archive: Path, destination: Path, max_bytes: int) -> list[Path]:
    written: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        total = sum(member.file_size for member in bundle.infolist())
        if total > max_bytes:
            raise UnsafeArchive(
                f"{archive.name} expands to {total} bytes, over the {max_bytes} byte limit"
            )
        for member in bundle.infolist():
            if member.is_dir():
                continue
            # The high half of external_attr carries the unix mode; 0xA000 is a symlink.
            if (member.external_attr >> 16) & 0xF000 == 0xA000:
                raise UnsafeArchive(f"archive member {member.filename!r} is a symlink")
            target = _reject(member.filename, destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle, 1 << 20)
            written.append(target)
    return sorted(written)


def _extract_tar(archive: Path, destination: Path, max_bytes: int) -> list[Path]:
    written: list[Path] = []
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        total = sum(member.size for member in members if member.isfile())
        if total > max_bytes:
            raise UnsafeArchive(
                f"{archive.name} expands to {total} bytes, over the {max_bytes} byte limit"
            )
        for member in members:
            if member.issym() or member.islnk():
                raise UnsafeArchive(f"archive member {member.name!r} is a link")
            if not member.isfile():
                continue
            target = _reject(member.name, destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle, 1 << 20)
            written.append(target)
    return sorted(written)


def manifest(directory: Path) -> list[StoredFile]:
    """Every stored file with its size and digest, relative to the version directory."""
    from backend.sync.fingerprint import sha256_of

    files = [path for path in sorted(directory.rglob("*")) if path.is_file()]
    return [
        StoredFile(
            name=str(path.relative_to(directory)),
            bytes=path.stat().st_size,
            sha256=sha256_of(path),
        )
        for path in files
    ]
