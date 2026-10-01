import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from backend.api import schemas
from backend.dependencies import AdminUser, DbSession, ResearchUser, client_ip
from database.models import BackgroundJob, JobStatus
from security import audit

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

GENERATE_DATASET = "generate_dataset"
TRAIN_MODEL = "train_model"
REWRAP_KEYS = "rewrap_keys"
SYNC_DATASETS = "sync_datasets"
TRAIN_EXTERNAL_BASELINE = "train_external_baseline"


def enqueue(db, kind: str, parameters: dict, requested_by: uuid.UUID | None) -> BackgroundJob:
    job = BackgroundJob(kind=kind, parameters=parameters, requested_by=requested_by)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[schemas.JobOut])
def list_jobs(
    db: DbSession,
    user: ResearchUser,
    kind: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[schemas.JobOut]:
    filters = [BackgroundJob.kind == kind] if kind else []
    rows = db.scalars(
        select(BackgroundJob)
        .where(*filters)
        .order_by(BackgroundJob.created_at.desc())
        .limit(limit)
    )
    return [schemas.JobOut.model_validate(row) for row in rows]


@router.get("/{job_id}", response_model=schemas.JobOut)
def read_job(job_id: uuid.UUID, db: DbSession, user: ResearchUser) -> schemas.JobOut:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    return schemas.JobOut.model_validate(job)


@router.post("/{job_id}/cancel", response_model=schemas.JobOut)
def cancel_job(
    job_id: uuid.UUID, request: Request, db: DbSession, admin: AdminUser
) -> schemas.JobOut:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status is not JobStatus.QUEUED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Only a job that has not started can be cancelled"
        )
    job.status = JobStatus.FAILED
    job.error = "Cancelled before it started"
    db.commit()
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=admin.id,
        actor_label=admin.email,
        resource="job",
        resource_id=str(job.id),
        client_ip=client_ip(request),
        meta={"action": "job_cancelled", "kind": job.kind},
    )
    return schemas.JobOut.model_validate(job)
