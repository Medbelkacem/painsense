"""The activity trail.

A clinician sees their own entries. Administrators see everything. Nobody can edit an entry
through the API: the only writer is the append path, and any change made behind it breaks
the hash chain that /api/integrity checks.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api import schemas
from app.database.models import AuditLog, Role
from app.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=schemas.AuditPage)
def read_audit(
    db: DbSession,
    user: CurrentUser,
    event_type: Annotated[str | None, Query(max_length=48)] = None,
    resource_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AuditPage:
    filters = []
    if user.role is not Role.ADMIN:
        filters.append(AuditLog.actor_id == user.id)
    if event_type:
        filters.append(AuditLog.event_type == event_type)
    if resource_id:
        filters.append(AuditLog.resource_id == resource_id)

    rows = list(db.scalars(select(AuditLog).where(*filters).order_by(AuditLog.seq.desc())))
    return schemas.AuditPage(
        items=[
            schemas.AuditEntryOut.model_validate(row) for row in rows[offset : offset + limit]
        ],
        total=len(rows),
        limit=limit,
        offset=offset,
    )
