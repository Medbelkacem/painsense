"""Model registry and training.

Nothing here reports a metric it did not measure. When no model has been trained the
response says so, and the estimate endpoint refuses rather than returning a number.
"""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.ai import features, model, training
from app.api import schemas
from app.database.models import ModelVersion
from app.dependencies import AdminUser, CurrentUser, DbSession

router = APIRouter(prefix="/api/ai-model", tags=["model"])

LIMITATIONS = (
    (
        "Trained on synthetic data only. Nothing here has been validated against clinical "
        "data, and the metrics describe agreement with synthetic self-reported scores."
    ),
    (
        "The reference is the patient's self-reported score, which is itself subjective and "
        "varies with context. Agreement with it is not the same as measuring pain."
    ),
    (
        "The interval is the 10th to 90th model quantile. The coverage it achieved on "
        "held-out data is reported next to it and is usually below the nominal 80 per cent."
    ),
    "No imaging model is implemented. Documents are stored and read by the clinician.",
)

EXCLUDED = (
    "Patient self-reported score (the training reference, never an inference feature)",
    (
        "The intensity recorded against each anatomical site. It rates the same thing the "
        "estimate is for, so the structures are read and their intensities are not."
    ),
    "Patient name, telephone and emergency contact",
    "Free-text history fields",
)


@router.get("", response_model=schemas.ModelStatus)
def model_status(db: DbSession, user: CurrentUser) -> schemas.ModelStatus:
    rows = list(db.scalars(select(ModelVersion).order_by(ModelVersion.trained_at.desc())))
    active = next((row for row in rows if row.is_active), None)
    return schemas.ModelStatus(
        trained=active is not None,
        active=schemas.ModelOut.model_validate(active) if active else None,
        versions=[schemas.ModelOut.model_validate(row) for row in rows],
        feature_count=len(features.NAMES),
        excluded_from_features=list(EXCLUDED),
        limitations=list(LIMITATIONS),
    )


@router.post("/train", response_model=schemas.ModelOut)
def train_model(
    payload: schemas.TrainingRequest, request: Request, db: DbSession, admin: AdminUser
) -> schemas.ModelOut:
    try:
        row = training.train(
            db,
            test_size=payload.test_size,
            seed=payload.seed,
            cv_folds=payload.cv_folds,
            actor_id=admin.id,
        )
    except training.NoDataset as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.ModelOut.model_validate(row)


@router.post("/{version}/activate", response_model=schemas.ModelOut)
def activate_model(version: str, db: DbSession, admin: AdminUser) -> schemas.ModelOut:
    try:
        row = model.activate(db, version)
    except model.ModelUnavailable as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ModelOut.model_validate(row)
