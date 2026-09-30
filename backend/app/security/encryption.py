import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

NONCE_LEN = 12


def _seal(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _unseal(key: bytes, blob: bytes, aad: bytes | None = None) -> bytes:
    return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)


def encrypt_record(payload: dict, aad: bytes | None = None) -> tuple[bytes, bytes]:
    """Seal a payload under a fresh data key and return (ciphertext, wrapped data key)."""
    dek = os.urandom(32)
    ciphertext = _seal(dek, json.dumps(payload, separators=(",", ":")).encode(), aad)
    wrapped = _seal(get_settings().master_key_bytes, dek)
    return ciphertext, wrapped


def decrypt_record(ciphertext: bytes, wrapped_key: bytes, aad: bytes | None = None) -> dict:
    dek = _unseal(get_settings().master_key_bytes, wrapped_key)
    return json.loads(_unseal(dek, ciphertext, aad))


def encrypt_blob(data: bytes, aad: bytes | None = None) -> tuple[bytes, bytes]:
    """Seal arbitrary bytes under a fresh data key and return (ciphertext, wrapped key)."""
    dek = os.urandom(32)
    return _seal(dek, data, aad), _seal(get_settings().master_key_bytes, dek)


def decrypt_blob(ciphertext: bytes, wrapped_key: bytes, aad: bytes | None = None) -> bytes:
    dek = _unseal(get_settings().master_key_bytes, wrapped_key)
    return _unseal(dek, ciphertext, aad)
