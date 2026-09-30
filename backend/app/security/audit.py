"""Audit trail.

Every entry is chained to the one before it, so an entry cannot be altered or removed
without breaking the chain from that point on. The sequence number is assigned here rather
than by the database: `autoincrement` only applies to integer primary keys, and the
sequence has to be handed out in the same order as the hash links.

Events that change clinical meaning also get a ledger block, which adds a signature over
the record hash. The audit chain says what happened; the ledger proves the record that was
involved has not changed since.
"""

import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.blockchain import ledger
from app.blockchain.hashing import ZERO_HASH, digest
from app.blockchain.verification import audit_payload
from app.database.models import AuditLog

ACCOUNT_REGISTERED = "ACCOUNT_REGISTERED"
LOGIN = "LOGIN"
LOGIN_FAILED = "LOGIN_FAILED"
LOGOUT = "LOGOUT"
TOKEN_REFRESH = "TOKEN_REFRESH"
PATIENT_CREATED = "PATIENT_CREATED"
PATIENT_UPDATED = "PATIENT_UPDATED"
PATIENT_ARCHIVED = "PATIENT_ARCHIVED"
ASSESSMENT_CREATED = "ASSESSMENT_CREATED"
ASSESSMENT_UPDATED = "ASSESSMENT_UPDATED"
ASSESSMENT_VALIDATED = "ASSESSMENT_VALIDATED"
DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
DOCUMENT_VIEWED = "DOCUMENT_VIEWED"
PREDICTION_RUN = "PREDICTION_RUN"
REPORT_GENERATED = "REPORT_GENERATED"
INTEGRITY_VERIFIED = "INTEGRITY_VERIFIED"
DATASET_GENERATED = "DATASET_GENERATED"
MODEL_TRAINED = "MODEL_TRAINED"
SECURITY_EVENT = "SECURITY_EVENT"

# Events that also earn a signed ledger block, with the resource they act on.
LEDGERED = {
    PATIENT_CREATED: "patient",
    PATIENT_UPDATED: "patient",
    PATIENT_ARCHIVED: "patient",
    ASSESSMENT_CREATED: "assessment",
    ASSESSMENT_UPDATED: "assessment",
    ASSESSMENT_VALIDATED: "assessment",
    DOCUMENT_UPLOADED: "document",
    PREDICTION_RUN: "prediction",
    REPORT_GENERATED: "report",
    MODEL_TRAINED: "model",
    DATASET_GENERATED: "dataset",
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
    """Append one audit entry, and a ledger block when the event warrants one."""
    with _append_lock:
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
        db.commit()

    if ledger_payload is not None and event_type in LEDGERED:
        ledger.append_block(
            db,
            event_type=event_type,
            resource=LEDGERED[event_type],
            record_id=str(resource_id),
            payload=ledger_payload,
            actor_id=actor_id,
        )
    return entry


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0
