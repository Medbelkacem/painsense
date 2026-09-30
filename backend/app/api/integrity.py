"""Ledger and audit-chain verification."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.api import schemas
from app.blockchain import ledger, verification
from app.dependencies import CurrentUser, DbSession, client_ip
from app.security import audit

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


def status_for(db) -> schemas.IntegrityStatus:
    chain = verification.verify_chain(db)
    audit_chain = verification.verify_audit_chain(db)
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
    result = status_for(db)
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
