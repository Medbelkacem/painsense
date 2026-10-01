"""The external dataset catalogue, as the interface reads it.

Everything here is driven by what is in the database, so a disease or a dataset that
arrives from a publisher tonight appears tomorrow with no change to this file and none to
the frontend. That is the point of `/overview`: one request returns the sources, every
disease with its dataset counts, and the recent run and event log, which is what a
dashboard needs to render itself from data rather than from a hard-coded list.

Reading is open to research and administrator accounts. Changing a source's schedule or
starting a run is restricted to administrators, and both are written to the audit trail,
because a sync run makes outbound requests on the institution's behalf.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.api import jobs, schemas
from backend.dependencies import AdminUser, DbSession, ResearchUser, client_ip
from backend.sync import sources as connectors
from backend.sync.sources.kaggle import credentials as kaggle_credentials
from database.models import (
    Availability,
    Disease,
    ExternalDataset,
    ExternalDatasetVersion,
    ExternalSource,
    SourceAccess,
    SyncEvent,
    SyncRun,
)
from security import audit

router = APIRouter(prefix="/api/external-datasets", tags=["external datasets"])

NOTICE = (
    "Access status is what the publisher permits; availability is what this platform "
    "holds. A dataset shown as metadata only was catalogued deliberately and its files "
    "were never requested. Record counts marked as held are measured from stored files; "
    "anything else is the publisher's own figure."
)


def _credentials_present(code: str) -> bool:
    return kaggle_credentials() is not None if code == "kaggle" else False


def _source_out(row: ExternalSource) -> schemas.SyncSourceOut:
    connector = connectors.BY_CODE.get(row.code)
    out = schemas.SyncSourceOut.model_validate(row)
    out.uses_credentials = bool(connector and connector.uses_credentials)
    out.credentials_present = _credentials_present(row.code)
    return out


@router.get("/sources", response_model=list[schemas.SyncSourceOut])
def list_sources(db: DbSession, user: ResearchUser) -> list[schemas.SyncSourceOut]:
    from backend.sync import service

    service.ensure_sources(db)
    rows = db.scalars(select(ExternalSource).order_by(ExternalSource.code))
    return [_source_out(row) for row in rows]


@router.patch("/sources/{code}", response_model=schemas.SyncSourceOut)
def update_source(
    code: str,
    payload: schemas.SyncSourceUpdate,
    request: Request,
    db: DbSession,
    admin: AdminUser,
) -> schemas.SyncSourceOut:
    row = db.get(ExternalSource, code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Source not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    if "poll_interval_minutes" in changes or "enabled" in changes:
        # Re-evaluate on the next scheduler tick rather than waiting out an interval that
        # was set under the old configuration.
        row.next_run_at = None
    db.commit()
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="external_source",
        resource_id=code,
        client_ip=client_ip(request),
        meta={"action": "sync_source_updated", "changes": sorted(changes)},
    )
    return _source_out(row)


@router.get("", response_model=list[schemas.ExternalDatasetOut])
def list_datasets(
    db: DbSession,
    user: ResearchUser,
    source: Annotated[str | None, Query(max_length=32)] = None,
    disease: Annotated[str | None, Query(max_length=48)] = None,
    availability: Availability | None = None,
    access: SourceAccess | None = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[schemas.ExternalDatasetOut]:
    filters = []
    if source:
        filters.append(ExternalDataset.source_code == source)
    if disease:
        filters.append(ExternalDataset.disease_code == disease)
    if availability:
        filters.append(ExternalDataset.availability == availability)
    if access:
        filters.append(ExternalDataset.access_status == access)
    if search:
        filters.append(ExternalDataset.name.ilike(f"%{search}%"))
    rows = db.scalars(
        select(ExternalDataset)
        .where(*filters)
        .order_by(ExternalDataset.relevance.desc(), ExternalDataset.name)
        .offset(offset)
        .limit(limit)
    )
    return [schemas.ExternalDatasetOut.model_validate(row) for row in rows]


@router.get("/overview", response_model=schemas.SyncOverviewOut)
def overview(db: DbSession, user: ResearchUser) -> schemas.SyncOverviewOut:
    """Everything the dashboard renders, in one request.

    Counts are computed in the database rather than by loading every dataset: the
    catalogue grows without bound as publishers add material, and a dashboard that
    degrades as the catalogue grows would stop being used.
    """
    from backend.sync import service

    service.ensure_sources(db)

    held = (
        select(
            ExternalDataset.disease_code.label("code"),
            func.count(func.distinct(ExternalDatasetVersion.dataset_id)).label("with_data"),
            func.coalesce(func.sum(ExternalDatasetVersion.records), 0).label("records"),
            func.max(ExternalDatasetVersion.acquired_at).label("last_acquired"),
        )
        .join(ExternalDatasetVersion, ExternalDatasetVersion.dataset_id == ExternalDataset.id)
        .group_by(ExternalDataset.disease_code)
        .subquery()
    )
    by_disease = {
        row.code: row for row in db.execute(select(held)).all() if row.code is not None
    }

    tallies: dict[str, dict] = {}
    rows = db.execute(
        select(
            ExternalDataset.disease_code,
            ExternalDataset.source_code,
            ExternalDataset.availability,
            func.count().label("n"),
        ).group_by(
            ExternalDataset.disease_code,
            ExternalDataset.source_code,
            ExternalDataset.availability,
        )
    ).all()
    for code, source_code, availability, count in rows:
        entry = tallies.setdefault(code, {"datasets": 0, "available": 0, "metadata_only": 0, "sources": set()})
        entry["datasets"] += count
        entry["sources"].add(source_code)
        if availability is Availability.AVAILABLE:
            entry["available"] += count
        elif availability is Availability.METADATA_ONLY:
            entry["metadata_only"] += count

    diseases = []
    for disease in db.scalars(select(Disease).order_by(Disease.category, Disease.label)):
        tally = tallies.get(disease.code)
        measured = by_disease.get(disease.code)
        if tally is None and disease.origin == "knowledge_base":
            # A curated comorbidity no publisher covers would otherwise fill the dashboard
            # with empty rows; it stays in the clinical catalogue either way.
            continue
        diseases.append(
            schemas.DiseaseDatasetSummary(
                code=disease.code,
                label=disease.label,
                category=disease.category,
                pain_relevant=disease.pain_relevant,
                curated=disease.curated,
                origin=disease.origin,
                discovered_at=disease.discovered_at,
                datasets=(tally or {}).get("datasets", 0),
                available=(tally or {}).get("available", 0),
                metadata_only=(tally or {}).get("metadata_only", 0),
                records_held=int(measured.records) if measured else 0,
                sources=sorted((tally or {}).get("sources", ())),
                last_acquired_at=measured.last_acquired if measured else None,
            )
        )

    unattributed = tallies.get(None)
    totals = {
        "sources": db.scalar(select(func.count()).select_from(ExternalSource)) or 0,
        "datasets": db.scalar(select(func.count()).select_from(ExternalDataset)) or 0,
        "available": db.scalar(
            select(func.count())
            .select_from(ExternalDataset)
            .where(ExternalDataset.availability == Availability.AVAILABLE)
        )
        or 0,
        "metadata_only": db.scalar(
            select(func.count())
            .select_from(ExternalDataset)
            .where(ExternalDataset.availability == Availability.METADATA_ONLY)
        )
        or 0,
        "versions": db.scalar(select(func.count()).select_from(ExternalDatasetVersion)) or 0,
        "trainable_versions": db.scalar(
            select(func.count())
            .select_from(ExternalDatasetVersion)
            .where(ExternalDatasetVersion.trainable.is_(True))
        )
        or 0,
        "bytes_held": int(
            db.scalar(select(func.coalesce(func.sum(ExternalDatasetVersion.bytes), 0))) or 0
        ),
        "datasets_without_disease": (unattributed or {}).get("datasets", 0),
    }

    return schemas.SyncOverviewOut(
        sources=[_source_out(row) for row in db.scalars(select(ExternalSource).order_by(ExternalSource.code))],
        diseases=diseases,
        totals=totals,
        recent_runs=[
            schemas.SyncRunOut.model_validate(row)
            for row in db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(10))
        ],
        recent_events=[
            schemas.SyncEventOut.model_validate(row)
            for row in db.scalars(select(SyncEvent).order_by(SyncEvent.at.desc()).limit(50))
        ],
        notice=NOTICE,
    )


@router.get("/runs", response_model=list[schemas.SyncRunOut])
def list_runs(
    db: DbSession,
    user: ResearchUser,
    source: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[schemas.SyncRunOut]:
    filters = [SyncRun.source_code == source] if source else []
    rows = db.scalars(
        select(SyncRun).where(*filters).order_by(SyncRun.started_at.desc()).limit(limit)
    )
    return [schemas.SyncRunOut.model_validate(row) for row in rows]


@router.get("/events", response_model=list[schemas.SyncEventOut])
def list_events(
    db: DbSession,
    user: ResearchUser,
    dataset_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[schemas.SyncEventOut]:
    filters = []
    if dataset_id:
        filters.append(SyncEvent.dataset_id == dataset_id)
    if run_id:
        filters.append(SyncEvent.run_id == run_id)
    rows = db.scalars(
        select(SyncEvent).where(*filters).order_by(SyncEvent.at.desc()).limit(limit)
    )
    return [schemas.SyncEventOut.model_validate(row) for row in rows]


@router.post("/sync", response_model=schemas.JobOut, status_code=202)
def start_sync(
    payload: schemas.SyncRequest, request: Request, db: DbSession, admin: AdminUser
) -> schemas.JobOut:
    """Queue a run now. The worker picks it up; this returns immediately with the job."""
    if payload.source and payload.source not in connectors.BY_CODE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown source")
    parameters = {k: v for k, v in payload.model_dump().items() if v is not None}
    job = jobs.enqueue(db, jobs.SYNC_DATASETS, {**parameters, "trigger": "manual"}, admin.id)
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="external_sync",
        resource_id=payload.source or "all",
        client_ip=client_ip(request),
        meta={"action": "sync_requested", "job_id": str(job.id)},
    )
    return schemas.JobOut.model_validate(job)


@router.get("/{dataset_id}", response_model=schemas.ExternalDatasetDetailOut)
def read_dataset(
    dataset_id: uuid.UUID, db: DbSession, user: ResearchUser
) -> schemas.ExternalDatasetDetailOut:
    row = db.scalar(
        select(ExternalDataset)
        .where(ExternalDataset.id == dataset_id)
        .options(selectinload(ExternalDataset.versions))
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return schemas.ExternalDatasetDetailOut.model_validate(row)
