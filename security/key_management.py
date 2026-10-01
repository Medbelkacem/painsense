import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from database.models import KeyMetadata
from security import pqc

LEDGER_SIGNING = "ledger-signing"
TRANSPORT_KEM = "transport-kem"
MASTER = "master-key"

_PURPOSE = {
    LEDGER_SIGNING: "Ledger block signatures",
    TRANSPORT_KEM: "Session key establishment",
    MASTER: "Record and document encryption",
}

_lock = threading.Lock()


@dataclass(frozen=True)
class KeyPair:
    label: str
    version: int
    public: bytes
    secret: bytes
    scheme: str

    @property
    def fingerprint(self) -> str:
        return pqc.fingerprint(self.public)

    @property
    def key_id(self) -> str:
        return f"{self.label}-v{self.version}"


@dataclass(frozen=True)
class KeyRecord:
    label: str
    version: int
    scheme: str
    fingerprint: str
    created_at: str
    retired_at: str | None
    current: bool


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class Keystore:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base or get_settings().key_store_path

    def _index_path(self, label: str) -> Path:
        return self.base / f"{label}.json"

    def _index(self, label: str) -> dict:
        path = self._index_path(label)
        legacy_metadata = None
        if path.exists():
            existing = json.loads(path.read_text())
            if isinstance(existing, dict) and {"current", "versions"} <= existing.keys():
                return existing
            if not isinstance(existing, dict) or "scheme" not in existing:
                raise ValueError(f"unsupported keystore metadata for {label}")
            legacy_metadata = existing

        legacy_pub, legacy_key = self.base / f"{label}.pub", self.base / f"{label}.key"
        if legacy_pub.exists() and legacy_key.exists():
            public = legacy_pub.read_bytes()
            fingerprint = pqc.fingerprint(public)
            if (
                legacy_metadata
                and legacy_metadata.get("fingerprint")
                and legacy_metadata["fingerprint"] != fingerprint
            ):
                raise ValueError(f"keystore fingerprint mismatch for {label}")
            scheme = (
                legacy_metadata.get("scheme") if legacy_metadata else self._legacy_scheme(label)
            )
            self._materialise(label, 1, public, legacy_key.read_bytes())
            index = {
                "current": 1,
                "versions": [
                    {
                        "version": 1,
                        "scheme": scheme,
                        "fingerprint": fingerprint,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "retired_at": None,
                    }
                ],
            }
            self._write_index(label, index)
            return index
        if legacy_metadata:
            raise ValueError(f"legacy keystore metadata has no key files for {label}")
        return {"current": 0, "versions": []}

    def _legacy_scheme(self, label: str) -> str:
        note = self.base / f"{label}.json"
        if note.exists():
            try:
                return json.loads(note.read_text())["scheme"]
            except (KeyError, ValueError):
                pass
        return pqc.sign_scheme() if label == LEDGER_SIGNING else pqc.kem_scheme()

    def _write_index(self, label: str, index: dict) -> None:
        _atomic_write(self._index_path(label), json.dumps(index, indent=2).encode())

    def _materialise(self, label: str, version: int, public: bytes, secret: bytes) -> None:
        _atomic_write(self.base / f"{label}.v{version}.pub", public)
        _atomic_write(self.base / f"{label}.v{version}.key", secret, mode=0o600)

    def _generate(self, label: str) -> tuple[bytes, bytes, str]:
        if label == LEDGER_SIGNING:
            scheme = pqc.sign_scheme()
            public, secret = pqc.generate_signature_keypair(scheme)
        else:
            scheme = pqc.kem_scheme()
            public, secret = pqc.generate_kem_keypair(scheme)
        return public, secret, scheme

    def current(self, label: str) -> KeyPair:
        with _lock:
            index = self._index(label)
            if not index["current"]:
                return self._rotate_locked(label, index)
            return self.version(label, index["current"], index)

    def version(self, label: str, version: int, index: dict | None = None) -> KeyPair:
        index = index or self._index(label)
        entry = next((v for v in index["versions"] if v["version"] == version), None)
        if entry is None:
            raise KeyError(f"{label} version {version} is not in the keystore")
        public = (self.base / f"{label}.v{version}.pub").read_bytes()
        secret = (self.base / f"{label}.v{version}.key").read_bytes()
        return KeyPair(label, version, public, secret, entry["scheme"])

    def rotate(self, label: str) -> KeyPair:
        with _lock:
            return self._rotate_locked(label, self._index(label))

    def _rotate_locked(self, label: str, index: dict) -> KeyPair:
        public, secret, scheme = self._generate(label)
        version = index["current"] + 1
        now = datetime.now(timezone.utc).isoformat()
        for entry in index["versions"]:
            if entry["retired_at"] is None:
                entry["retired_at"] = now
        index["versions"].append(
            {
                "version": version,
                "scheme": scheme,
                "fingerprint": pqc.fingerprint(public),
                "created_at": now,
                "retired_at": None,
            }
        )
        index["current"] = version
        self._materialise(label, version, public, secret)
        self._write_index(label, index)
        return KeyPair(label, version, public, secret, scheme)

    def history(self, label: str) -> list[KeyRecord]:
        index = self._index(label)
        return [
            KeyRecord(
                label=label,
                version=entry["version"],
                scheme=entry["scheme"],
                fingerprint=entry["fingerprint"],
                created_at=entry["created_at"],
                retired_at=entry["retired_at"],
                current=entry["version"] == index["current"],
            )
            for entry in index["versions"]
        ]


def ledger_signing_key() -> KeyPair:
    return Keystore().current(LEDGER_SIGNING)


def ledger_signing_key_version(version: int) -> KeyPair:
    return Keystore().version(LEDGER_SIGNING, version)


def transport_kem_key() -> KeyPair:
    return Keystore().current(TRANSPORT_KEM)


def keystore_path() -> Path:
    return get_settings().key_store_path


class KeyManagementService:
    def __init__(self, db: Session, keystore: Keystore | None = None) -> None:
        self.db = db
        self.keystore = keystore or Keystore()

    def sync(self) -> list[KeyMetadata]:
        rows = []
        for label in (LEDGER_SIGNING, TRANSPORT_KEM):
            self.keystore.current(label)
            for record in self.keystore.history(label):
                rows.append(
                    self._upsert(
                        label,
                        record.version,
                        record.scheme,
                        record.fingerprint,
                        record.current,
                        record.retired_at,
                    )
                )
        settings = get_settings()
        for version, key in sorted(settings.master_keys.items()):
            rows.append(
                self._upsert(
                    MASTER,
                    version,
                    "AES-256-GCM",
                    pqc.fingerprint(key),
                    version == settings.master_key_version,
                    None,
                )
            )
        self.db.commit()
        return rows

    def _upsert(
        self,
        label: str,
        version: int,
        scheme: str,
        fingerprint: str,
        current: bool,
        retired_at: str | None,
    ) -> KeyMetadata:
        row = self.db.scalar(
            select(KeyMetadata).where(
                KeyMetadata.label == label, KeyMetadata.version == version
            )
        )
        if row is None:
            row = KeyMetadata(label=label, version=version, purpose=_PURPOSE[label])
            self.db.add(row)
        row.algorithm = scheme
        row.fingerprint = fingerprint
        row.is_current = current
        if retired_at and row.retired_at is None:
            row.retired_at = datetime.fromisoformat(retired_at)
        elif not current and row.retired_at is None:
            row.retired_at = datetime.now(timezone.utc)
        return row

    def rotate(self, label: str) -> KeyPair:
        pair = self.keystore.rotate(label)
        rows = self.sync()
        for row in rows:
            if row.label == label and row.version == pair.version:
                row.rotated_at = datetime.now(timezone.utc)
        self.db.commit()
        return pair

    def rewrap_all(self) -> int:
        from database.models import MedicalDocument, Patient
        from security import encryption

        changed = 0
        for patient in self.db.scalars(
            select(Patient).where(Patient.identity_key.is_not(None))
        ):
            fresh = encryption.rewrap_key(patient.identity_key)
            if fresh != patient.identity_key:
                patient.identity_key = fresh
                changed += 1
        for document in self.db.scalars(select(MedicalDocument)):
            fresh = encryption.rewrap_key(document.wrapped_key)
            if fresh != document.wrapped_key:
                document.wrapped_key = fresh
                changed += 1
        self.db.commit()
        self.sync()
        return changed

    def records(self) -> list[KeyMetadata]:
        return list(
            self.db.scalars(
                select(KeyMetadata).order_by(KeyMetadata.label, KeyMetadata.version)
            )
        )
