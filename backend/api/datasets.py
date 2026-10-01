from fastapi import APIRouter
from sqlalchemy import select

from backend.api import jobs, schemas
from database.models import DatasetVersion
from backend.dependencies import AdminUser, DbSession, ResearchUser
from knowledge import (
    anatomy,
    confounders,
    diseases,
    medications,
    pain_types,
    qualities,
    questions,
    rules,
    symptoms,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

WARNING = "SYNTHETIC DATA. Not clinical data and not representative of any real population."


def _versions(db) -> list[schemas.DatasetOut]:
    rows = db.scalars(select(DatasetVersion).order_by(DatasetVersion.generated_at.desc()))
    return [schemas.DatasetOut.model_validate(row) for row in rows]


@router.get("", response_model=list[schemas.DatasetOut])
def list_datasets(db: DbSession, user: ResearchUser) -> list[schemas.DatasetOut]:
    return _versions(db)


@router.get("/explorer", response_model=schemas.DatasetExplorerOut)
def explorer(db: DbSession, user: ResearchUser) -> schemas.DatasetExplorerOut:
    versions = _versions(db)
    return schemas.DatasetExplorerOut(
        latest=versions[0] if versions else None,
        versions=versions,
        anatomy=anatomy.counts(),
        pain_types=len(pain_types.PAIN_TYPES),
        pain_qualities=len(qualities.QUALITIES),
        symptoms=len(symptoms.SYMPTOMS),
        diseases=len(diseases.DISEASES),
        medication_classes=len(medications.MEDICATION_CLASSES),
        confounders=len(confounders.CONFOUNDERS),
        questions=len(questions.QUESTIONS),
        rules=len(rules.RED_FLAGS),
    )


@router.post("/generate", response_model=schemas.JobOut, status_code=202)
def generate(
    payload: schemas.DatasetRequest, db: DbSession, admin: AdminUser
) -> schemas.JobOut:
    job = jobs.enqueue(db, jobs.GENERATE_DATASET, payload.model_dump(), admin.id)
    return schemas.JobOut.model_validate(job)
