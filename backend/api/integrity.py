import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from backend.api import schemas
from security import ledger
from database.models import AuditLog, LedgerBlock
from backend.dependencies import CurrentUser, DbSession, client_ip
from security import audit

router = APIRouter(prefix="/api/integrity", tags=["integrity"])

CACHE_SECONDS = 60.0
_cache: dict = {"key": None, "at": 0.0, "value": None}
_cache_lock = threading.Lock()


def _chain_lengths(db) -> tuple[int, int]:
    blocks = db.scalar(select(func.count()).select_from(LedgerBlock)) or 0
    entries = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    return blocks, entries


def status_for(db, fresh: bool = False) -> schemas.IntegrityStatus:
    key = _chain_lengths(db)
    with _cache_lock:
        cached = _cache["value"]
        if (
            not fresh
            and cached is not None
            and _cache["key"] == key
            and time.monotonic() - _cache["at"] < CACHE_SECONDS
        ):
            return cached
    result = _verify(db)
    with _cache_lock:
        _cache.update(key=key, at=time.monotonic(), value=result)
    return result


def _verify(db) -> schemas.IntegrityStatus:
    chain = ledger.verify_chain(db)
    audit_chain = ledger.verify_audit_chain(db)
    problems = [
        schemas.IntegrityProblem(height=item.height, kind=item.kind, detail=item.detail)
        for item in [*chain.problems, *audit_chain.problems]
    ]
    return schemas.IntegrityStatus(
        ledger_valid=chain.valid,
        blocks=chain.blocks_checked,
        signature_scheme=chain.signature_scheme,
        key_fingerprint=chain.key_fingerprint,
        audit_valid=audit_chain.valid,
        audit_entries=audit_chain.entries_checked,
        problems=problems,
        verified_at=datetime.now(timezone.utc),
    )


@router.get("/status", response_model=schemas.IntegrityStatus)
def read_status(db: DbSession, user: CurrentUser) -> schemas.IntegrityStatus:
    return status_for(db)


@router.post("/verify", response_model=schemas.IntegrityStatus)
def verify(request: Request, db: DbSession, user: CurrentUser) -> schemas.IntegrityStatus:
    result = status_for(db, fresh=True)
    audit.record(
        db,
        event_type=audit.INTEGRITY_VERIFIED,
        actor_id=user.id,
        actor_label=user.email,
        resource="ledger",
        resource_id=str(ledger.height(db)),
        client_ip=client_ip(request),
        meta={
            "ledger_valid": result.ledger_valid,
            "audit_valid": result.audit_valid,
            "blocks": result.blocks,
            "problems": len(result.problems),
        },
    )
    return result
