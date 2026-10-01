import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import AuditLog
from database.session import serialise_appends
from security import ledger
from security.ledger import ZERO_HASH, audit_payload, digest

ACCOUNT_REGISTERED = "ACCOUNT_REGISTERED"
LOGIN = "LOGIN"
LOGIN_FAILED = "LOGIN_FAILED"
LOGOUT = "LOGOUT"
TOKEN_REFRESH = "TOKEN_REFRESH"
PATIENT_CREATED = "PATIENT_CREATED"
PATIENT_VIEWED = "PATIENT_VIEWED"
PATIENT_UPDATED = "PATIENT_UPDATED"
PATIENT_ARCHIVED = "PATIENT_ARCHIVED"
PATIENT_DELETED = "PATIENT_DELETED"
ASSESSMENT_CREATED = "ASSESSMENT_CREATED"
ASSESSMENT_UPDATED = "ASSESSMENT_UPDATED"
ASSESSMENT_VALIDATED = "ASSESSMENT_VALIDATED"
ASSESSMENT_DELETED = "ASSESSMENT_DELETED"
DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
DOCUMENT_UPDATED = "DOCUMENT_UPDATED"
DOCUMENT_VIEWED = "DOCUMENT_VIEWED"
PREDICTION_GENERATED = "PREDICTION_GENERATED"
REPORT_GENERATED = "REPORT_GENERATED"
DATA_EXPORTED = "DATA_EXPORTED"
INTEGRITY_VERIFIED = "INTEGRITY_VERIFIED"
DATASET_GENERATED = "DATASET_GENERATED"
MODEL_TRAINED = "MODEL_TRAINED"
BEHAVIOUR_OBSERVED = "BEHAVIOUR_OBSERVED"
BEHAVIOUR_MEDIA_DISCARDED = "BEHAVIOUR_MEDIA_DISCARDED"
KEY_ROTATED = "KEY_ROTATED"
SECURITY_EVENT = "SECURITY_EVENT"

EVENT_TYPES = (
    ACCOUNT_REGISTERED,
    LOGIN,
    LOGIN_FAILED,
    LOGOUT,
    TOKEN_REFRESH,
    PATIENT_CREATED,
    PATIENT_VIEWED,
    PATIENT_UPDATED,
    PATIENT_ARCHIVED,
    ASSESSMENT_CREATED,
    ASSESSMENT_UPDATED,
    ASSESSMENT_VALIDATED,
    DOCUMENT_UPLOADED,
    DOCUMENT_UPDATED,
    DOCUMENT_VIEWED,
    PREDICTION_GENERATED,
    REPORT_GENERATED,
    DATA_EXPORTED,
    INTEGRITY_VERIFIED,
    DATASET_GENERATED,
    MODEL_TRAINED,
    KEY_ROTATED,
    SECURITY_EVENT,
)

LEDGERED = {
    PATIENT_CREATED: "patient",
    PATIENT_UPDATED: "patient",
    PATIENT_ARCHIVED: "patient",
    ASSESSMENT_CREATED: "assessment",
    ASSESSMENT_UPDATED: "assessment",
    ASSESSMENT_VALIDATED: "assessment",
    DOCUMENT_UPLOADED: "document",
    DOCUMENT_UPDATED: "document",
    PREDICTION_GENERATED: "prediction",
    REPORT_GENERATED: "report",
    DATA_EXPORTED: "export",
    MODEL_TRAINED: "model",
    DATASET_GENERATED: "dataset",
    KEY_ROTATED: "key",
}

_append_lock = threading.Lock()


def record(
    db: Session,
    *,
    event_type: str,
    actor_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    resource: str | None = None,
    resource_id: str | None = None,
    client_ip: str | None = None,
    meta: dict | None = None,
    ledger_payload: dict | None = None,
) -> AuditLog:
    with _append_lock:
        serialise_appends(db, "audit")
        previous = db.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
        entry = AuditLog(
            seq=1 if previous is None else previous.seq + 1,
            timestamp=datetime.now(timezone.utc),
            actor_id=actor_id,
            actor_label=actor_label,
            event_type=event_type,
            resource=resource,
            resource_id=resource_id,
            client_ip=client_ip,
            meta=meta or {},
            previous_hash=ZERO_HASH if previous is None else previous.entry_hash,
            entry_hash="",
        )
        entry.entry_hash = digest(audit_payload(entry))
        db.add(entry)
        db.flush()

        if ledger_payload is not None and event_type in LEDGERED:
            ledger.append_block(
                db,
                event_type=event_type,
                resource=LEDGERED[event_type],
                record_id=str(resource_id),
                payload=ledger_payload,
                actor_id=actor_id,
                commit=False,
            )
        db.commit()
    return entry


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0
