"""Synthetic dataset versions."""

from fastapi import APIRouter
from sqlalchemy import select

from app.api import schemas
from app.database.models import DatasetVersion
from app.datasets import generate
from app.dependencies import AdminUser, CurrentUser, DbSession

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

WARNING = "SYNTHETIC DATA. Not clinical data and not representative of any real population."


@router.get("", response_model=list[schemas.DatasetOut])
def list_datasets(db: DbSession, user: CurrentUser) -> list[schemas.DatasetOut]:
    rows = db.scalars(select(DatasetVersion).order_by(DatasetVersion.generated_at.desc()))
    return [schemas.DatasetOut.model_validate(row) for row in rows]


@router.post("/generate", response_model=schemas.DatasetOut)
def regenerate(
    payload: schemas.DatasetRequest, db: DbSession, admin: AdminUser
) -> schemas.DatasetOut:
    path, metadata = generate.write(payload.rows, payload.seed)
    generate.register(metadata, path)
    row = db.scalar(select(DatasetVersion).where(DatasetVersion.version == metadata["version"]))
    return schemas.DatasetOut.model_validate(row)
