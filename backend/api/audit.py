import csv
import io
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select

from backend.api import schemas
from backend.dependencies import AuditUser, CurrentUser, DbSession, client_ip
from database.models import ADMIN_ROLES, AuditLog, Role
from security import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])

EXPORT_LIMIT = 10_000


def _scope(user) -> list:
    if user.role in ADMIN_ROLES or user.role is Role.AUDITOR:
        return []
    return [AuditLog.actor_id == user.id]


@router.get("", response_model=schemas.AuditPage)
def read_audit(
    db: DbSession,
    user: CurrentUser,
    event_type: Annotated[str | None, Query(max_length=48)] = None,
    resource_id: Annotated[str | None, Query(max_length=64)] = None,
    actor: Annotated[str | None, Query(max_length=190)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AuditPage:
    filters = _scope(user)
    if event_type:
        filters.append(AuditLog.event_type == event_type.upper())
    if resource_id:
        filters.append(AuditLog.resource_id == resource_id)
    if actor:
        filters.append(AuditLog.actor_label == actor)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.seq.desc())
        .offset(offset)
        .limit(limit)
    )
    return schemas.AuditPage(
        items=[schemas.AuditEntryOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/event-types", response_model=list[str])
def event_types(user: CurrentUser) -> list[str]:
    return list(audit.EVENT_TYPES)


@router.get("/summary", response_model=dict)
def summary(db: DbSession, user: AuditUser) -> dict:
    counts = db.execute(
        select(AuditLog.event_type, func.count()).group_by(AuditLog.event_type)
    ).all()
    return {
        "total": sum(count for _, count in counts),
        "by_event": {event: count for event, count in sorted(counts)},
    }


@router.get("/export")
def export_audit(request: Request, db: DbSession, user: AuditUser) -> Response:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.seq).limit(EXPORT_LIMIT)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "seq",
            "timestamp",
            "event_type",
            "actor",
            "resource",
            "resource_id",
            "client_ip",
            "hash",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.seq,
                row.timestamp.isoformat(),
                row.event_type,
                row.actor_label or "",
                row.resource or "",
                row.resource_id or "",
                row.client_ip or "",
                row.entry_hash,
            ]
        )
    audit.record(
        db,
        event_type=audit.DATA_EXPORTED,
        actor_id=user.id,
        actor_label=user.email,
        resource="export",
        resource_id="audit-trail",
        client_ip=client_ip(request),
        meta={"rows": len(rows), "format": "csv"},
        ledger_payload={"export": "audit-trail", "rows": len(rows), "by": str(user.id)},
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="painsense-audit.csv"',
            "Cache-Control": "no-store",
        },
    )
