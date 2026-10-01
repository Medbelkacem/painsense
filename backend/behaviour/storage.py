"""Where a clip goes, and when it goes away.

The default is that it goes away. A clip is measured, the measures are stored, and the
video and audio are deleted — because a recording of a patient's face and voice is the most
identifying thing this platform ever touches, and once the thirty numbers are out of it
there is no clinical question the file answers that they do not.

A clinician can ask for one to be kept, and then it is encrypted at rest under its own data
key the same way an uploaded document is, in its own directory so that a retention rule can
be applied to clips without touching anything else.

The digest is taken before either decision and kept in both cases. It is what ties a set of
measures to the clip they came from if a copy of that clip is ever produced from elsewhere,
and on its own it identifies nobody.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from config import get_settings
from security import encryption


def root() -> Path:
    return get_settings().observation_store_path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _aad(observation_id: uuid.UUID) -> bytes:
    """Additional authenticated data, so a clip cannot be moved between observations.

    The ciphertext is bound to the row that owns it: decryption with another row's id
    fails rather than returning somebody else's recording.
    """
    return f"behaviour-observation:{observation_id}".encode()


def retain(observation_id: uuid.UUID, data: bytes) -> tuple[str, bytes]:
    """Encrypt and write a clip. Returns its storage name and its wrapped data key."""
    name = uuid.uuid4().hex
    ciphertext, wrapped = encryption.encrypt_blob(data, aad=_aad(observation_id))
    root().mkdir(parents=True, exist_ok=True)
    (root() / name).write_bytes(ciphertext)
    return name, wrapped


def read(observation_id: uuid.UUID, name: str, wrapped_key: bytes) -> bytes:
    path = root() / name
    if not path.exists():
        raise FileNotFoundError(f"the retained clip {name} is no longer on disk")
    return encryption.decrypt_blob(
        path.read_bytes(), wrapped_key, aad=_aad(observation_id)
    )


def discard(name: str | None) -> None:
    """Delete a retained clip. Silent when there is nothing there, so that withdrawing
    consent twice is not an error."""
    if not name:
        return
    path = root() / name
    path.unlink(missing_ok=True)
