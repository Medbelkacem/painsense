"""Keeps signing material out of the application database.

Splitting storage matters: the ledger rows live in PostgreSQL, the key that signs them
does not, so a dump of the database is not enough to forge a block.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.security import pqc


@dataclass(frozen=True)
class KeyPair:
    public: bytes
    secret: bytes
    scheme: str

    @property
    def fingerprint(self) -> str:
        return pqc.fingerprint(self.public)


def _load_or_create(name: str, generator, scheme: str) -> KeyPair:
    base = get_settings().key_store_path
    pub_file, sec_file = base / f"{name}.pub", base / f"{name}.key"

    if pub_file.exists() and sec_file.exists():
        return KeyPair(pub_file.read_bytes(), sec_file.read_bytes(), scheme)

    public, secret = generator()
    pub_file.write_bytes(public)
    sec_file.write_bytes(secret)
    sec_file.chmod(0o600)
    (base / f"{name}.json").write_text(
        json.dumps({"scheme": scheme, "fingerprint": pqc.fingerprint(public)}, indent=2)
    )
    return KeyPair(public, secret, scheme)


def ledger_signing_key() -> KeyPair:
    return _load_or_create("ledger-signing", pqc.generate_signature_keypair, pqc.SIGN_SCHEME)


def transport_kem_key() -> KeyPair:
    return _load_or_create("transport-kem", pqc.generate_kem_keypair, pqc.KEM_SCHEME)


def keystore_path() -> Path:
    return get_settings().key_store_path
