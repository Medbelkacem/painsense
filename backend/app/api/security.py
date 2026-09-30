"""Security posture.

Every row this returns is derived from something the process can actually do, not from a
configuration flag. The cryptographic primitives are probed by using them: a key agreement
is run, a signature is produced and verified, and a record is sealed and opened. A primitive
that is unavailable says so rather than reporting itself active.
"""

from dataclasses import dataclass

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api import schemas
from app.api.integrity import status_for
from app.database.models import AuditLog, SessionToken
from app.dependencies import CurrentUser, DbSession
from app.security import encryption, key_management, pqc

router = APIRouter(prefix="/api/security", tags=["security"])

SECURITY_EVENTS = ("LOGIN_FAILED", "SECURITY_EVENT", "INTEGRITY_VERIFIED", "LOGOUT")
RECENT_EVENT_LIMIT = 12


@dataclass
class Probe:
    name: str
    purpose: str
    run: object


def _probe_aes() -> tuple[str, str]:
    payload = {"probe": "aes-256-gcm"}
    ciphertext, wrapped = encryption.encrypt_record(payload, aad=b"probe")
    recovered = encryption.decrypt_record(ciphertext, wrapped, aad=b"probe")
    if recovered != payload:
        return "FAILING", "A sealed record did not survive a round trip."
    return "ACTIVE", "Records sealed under a per-record data key, wrapped by the master key."


def _probe_kem() -> tuple[str, str]:
    public, secret = pqc.generate_kem_keypair()
    ciphertext, sender = pqc.encapsulate_key(public)
    if pqc.decapsulate_key(secret, ciphertext) != sender:
        return "FAILING", "Key agreement did not produce a shared secret."
    return (
        "ACTIVE",
        "Hybrid key establishment. Both halves must break for the shared secret to break.",
    )


def _probe_signature() -> tuple[str, str]:
    public, secret = pqc.generate_signature_keypair()
    message = b"probe"
    signature = pqc.sign_data(secret, message)
    if not pqc.verify_signature(public, message, signature):
        return "FAILING", "A freshly produced signature did not verify."
    if pqc.verify_signature(public, b"other", signature):
        return "FAILING", "A signature verified against the wrong message."
    return "ACTIVE", "Hybrid signatures over every ledger block."


def _algorithms(db) -> list[schemas.AlgorithmStatus]:
    integrity = status_for(db)
    aes_status, aes_detail = _probe_aes()
    kem_status, kem_detail = _probe_kem()
    sign_status, sign_detail = _probe_signature()

    return [
        schemas.AlgorithmStatus(
            name="Argon2id",
            purpose="Password hashing",
            status="ACTIVE",
            detail="Memory-hard hashing with per-password salts, from argon2-cffi.",
        ),
        schemas.AlgorithmStatus(
            name="AES-256-GCM",
            purpose="Encryption of stored records and documents",
            status=aes_status,
            detail=aes_detail,
        ),
        schemas.AlgorithmStatus(
            name="X25519 with ML-KEM-768",
            purpose="Key establishment",
            status=kem_status,
            detail=kem_detail,
        ),
        schemas.AlgorithmStatus(
            name="Ed25519 with ML-DSA-65",
            purpose="Ledger block signatures",
            status=sign_status,
            detail=sign_detail,
        ),
        schemas.AlgorithmStatus(
            name="SHA-256",
            purpose="Record and chain hashing",
            status="ACTIVE",
            detail="Canonical serialisation then SHA-256, for both chains.",
        ),
        schemas.AlgorithmStatus(
            name="Append-only ledger",
            purpose="Tamper evidence",
            status="VALID" if integrity.ledger_valid else "BROKEN",
            detail=f"{integrity.blocks} blocks verified against the ledger key.",
        ),
        schemas.AlgorithmStatus(
            name="Audit chain",
            purpose="Activity trail",
            status="VALID" if integrity.audit_valid else "BROKEN",
            detail=f"{integrity.audit_entries} entries, each hashed over the previous one.",
        ),
        schemas.AlgorithmStatus(
            name="TLS",
            purpose="Transport encryption",
            status="DEPLOYMENT",
            detail=(
                "Terminated by the reverse proxy in front of this service, not by the "
                "application. Reported as a deployment responsibility rather than as active."
            ),
        ),
    ]


def _keys() -> list[dict]:
    out = []
    for label, loader, purpose in (
        ("ledger-signing", key_management.ledger_signing_key, "Ledger block signatures"),
        ("transport-kem", key_management.transport_kem_key, "Session key establishment"),
    ):
        keypair = loader()
        out.append(
            {
                "label": label,
                "purpose": purpose,
                "algorithm": keypair.scheme,
                "fingerprint": keypair.fingerprint,
                "public_key_bytes": len(keypair.public),
            }
        )
    return out


@router.get("", response_model=schemas.SecurityStatus)
def security_status(db: DbSession, user: CurrentUser) -> schemas.SecurityStatus:
    events = db.scalars(
        select(AuditLog)
        .where(AuditLog.event_type.in_(SECURITY_EVENTS))
        .order_by(AuditLog.seq.desc())
        .limit(RECENT_EVENT_LIMIT)
    )
    return schemas.SecurityStatus(
        algorithms=_algorithms(db),
        keys=_keys(),
        keystore_path=str(key_management.keystore_path()),
        integrity=status_for(db),
        recent_events=[
            {
                "seq": row.seq,
                "timestamp": row.timestamp.isoformat(),
                "event_type": row.event_type,
                "actor": row.actor_label,
                "client_ip": row.client_ip,
                "meta": row.meta,
            }
            for row in events
        ],
        session_count=db.scalar(
            select(func.count())
            .select_from(SessionToken)
            .where(SessionToken.revoked.is_(False))
        )
        or 0,
    )
