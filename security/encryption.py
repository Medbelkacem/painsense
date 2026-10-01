import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import get_settings

NONCE_LEN = 12
TAG_LEN = 16
DATA_KEY_LEN = 32

_LEGACY_WRAP_LEN = NONCE_LEN + DATA_KEY_LEN + TAG_LEN
_WRAP_MAGIC = b"PK"


class KeyVersionUnavailable(Exception):
    pass


def _seal(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _unseal(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)


def wrap_key(dek: bytes) -> bytes:
    settings = get_settings()
    version = settings.master_key_version
    return _WRAP_MAGIC + bytes([version]) + _seal(settings.master_key_bytes, dek)


def wrap_version(wrapped: bytes) -> int:
    if len(wrapped) == _LEGACY_WRAP_LEN:
        return 1
    if wrapped[:2] == _WRAP_MAGIC and len(wrapped) == _LEGACY_WRAP_LEN + 3:
        return wrapped[2]
    raise ValueError("wrapped key has an unrecognised shape")


def unwrap_key(wrapped: bytes) -> bytes:
    version = wrap_version(wrapped)
    key = get_settings().master_keys.get(version)
    if key is None:
        raise KeyVersionUnavailable(f"master key version {version} is not in the key ring")
    body = wrapped if len(wrapped) == _LEGACY_WRAP_LEN else wrapped[3:]
    return _unseal(key, body)


def rewrap_key(wrapped: bytes) -> bytes:
    if wrap_version(wrapped) == get_settings().master_key_version:
        return wrapped
    return wrap_key(unwrap_key(wrapped))


def encrypt_record(payload: dict, aad: bytes | None = None) -> tuple[bytes, bytes]:
    dek = os.urandom(DATA_KEY_LEN)
    ciphertext = _seal(dek, json.dumps(payload, separators=(",", ":")).encode(), aad)
    return ciphertext, wrap_key(dek)


def decrypt_record(ciphertext: bytes, wrapped_key: bytes, aad: bytes | None = None) -> dict:
    return json.loads(_unseal(unwrap_key(wrapped_key), ciphertext, aad))


def encrypt_blob(data: bytes, aad: bytes | None = None) -> tuple[bytes, bytes]:
    dek = os.urandom(DATA_KEY_LEN)
    return _seal(dek, data, aad), wrap_key(dek)


def decrypt_blob(ciphertext: bytes, wrapped_key: bytes, aad: bytes | None = None) -> bytes:
    return _unseal(unwrap_key(wrapped_key), ciphertext, aad)
