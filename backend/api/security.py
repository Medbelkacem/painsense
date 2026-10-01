from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from backend.api import jobs, schemas
from backend.api.integrity import status_for
from config import get_settings
from database.models import AuditLog, MedicalDocument, Patient, SessionToken, User
from backend.dependencies import AuditUser, DbSession, SuperAdminUser, client_ip
from security import audit, encryption, key_management, pqc

router = APIRouter(prefix="/api/security", tags=["security"])

SECURITY_EVENTS = (
    "LOGIN_FAILED",
    "SECURITY_EVENT",
    "INTEGRITY_VERIFIED",
    "LOGOUT",
    "KEY_ROTATED",
    "DATA_EXPORTED",
)
RECENT_EVENT_LIMIT = 12
ROTATABLE = (key_management.LEDGER_SIGNING, key_management.TRANSPORT_KEM)


def _probe_aes() -> tuple[str, str]:
    payload = {"probe": "aes-256-gcm"}
    ciphertext, wrapped = encryption.encrypt_record(payload, aad=b"probe")
    recovered = encryption.decrypt_record(ciphertext, wrapped, aad=b"probe")
    if recovered != payload:
        return "FAILING", "A sealed record did not survive a round trip."
    version = encryption.wrap_version(wrapped)
    return (
        "ACTIVE",
        f"Records sealed under a per-record data key, wrapped by master key version {version}.",
    )


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
    return "ACTIVE", f"Hybrid signatures over every ledger block ({len(signature)} bytes each)."


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
            name=pqc.kem_scheme(),
            purpose="Key establishment",
            status=kem_status,
            detail=kem_detail,
        ),
        schemas.AlgorithmStatus(
            name=pqc.sign_scheme(),
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
            detail=f"{integrity.blocks} blocks verified against their signing key versions.",
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


def _keys(db) -> list[schemas.KeyVersionOut]:
    service = key_management.KeyManagementService(db)
    service.sync()
    return [
        schemas.KeyVersionOut(
            label=row.label,
            purpose=row.purpose,
            version=row.version,
            algorithm=row.algorithm,
            fingerprint=row.fingerprint,
            is_current=row.is_current,
            created_at=row.created_at,
            rotated_at=row.rotated_at,
            retired_at=row.retired_at,
        )
        for row in service.records()
    ]


@router.get("", response_model=schemas.SecurityStatus)
def security_status(db: DbSession, user: AuditUser) -> schemas.SecurityStatus:
    now = datetime.now(timezone.utc)
    events = db.scalars(
        select(AuditLog)
        .where(AuditLog.event_type.in_(SECURITY_EVENTS))
        .order_by(AuditLog.seq.desc())
        .limit(RECENT_EVENT_LIMIT)
    )
    settings = get_settings()
    return schemas.SecurityStatus(
        algorithms=_algorithms(db),
        keys=_keys(db),
        pqc_kem_level=settings.pqc_kem_level,
        pqc_sign_level=settings.pqc_sign_level,
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
            .where(SessionToken.revoked.is_(False), SessionToken.expires_at > now)
        )
        or 0,
        failed_logins_24h=db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.event_type == audit.LOGIN_FAILED,
                AuditLog.timestamp >= now - timedelta(hours=24),
            )
        )
        or 0,
        locked_accounts=db.scalar(
            select(func.count()).select_from(User).where(User.locked_until > now)
        )
        or 0,
        documents_encrypted=db.scalar(select(func.count()).select_from(MedicalDocument)) or 0,
        patients_sealed=db.scalar(
            select(func.count()).select_from(Patient).where(Patient.identity_blob.is_not(None))
        )
        or 0,
        master_key_versions_in_ring=len(settings.master_keys),
    )


@router.post("/keys/{label}/rotate", response_model=list[schemas.KeyVersionOut])
def rotate_key(
    label: str, request: Request, db: DbSession, admin: SuperAdminUser
) -> list[schemas.KeyVersionOut]:
    if label not in ROTATABLE:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Only the ledger signing key and the transport key rotate here. The master "
            "key rotates through configuration followed by a re-wrap job.",
        )
    pair = key_management.KeyManagementService(db).rotate(label)
    audit.record(
        db,
        event_type=audit.KEY_ROTATED,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="key",
        resource_id=pair.key_id,
        client_ip=client_ip(request),
        meta={"label": label, "version": pair.version, "scheme": pair.scheme},
        ledger_payload={
            "key_id": pair.key_id,
            "scheme": pair.scheme,
            "fingerprint": pair.fingerprint,
        },
    )
    return _keys(db)


@router.post("/keys/master/rewrap", response_model=schemas.JobOut, status_code=202)
def rewrap_master(request: Request, db: DbSession, admin: SuperAdminUser) -> schemas.JobOut:
    job = jobs.enqueue(db, jobs.REWRAP_KEYS, {}, admin.id)
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="job",
        resource_id=str(job.id),
        client_ip=client_ip(request),
        meta={"action": "rewrap_requested"},
    )
    return schemas.JobOut.model_validate(job)
