from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from backend.ai import drift, features, model
from backend.api import jobs, schemas
from database.models import ModelVersion, PainPrediction
from backend.dependencies import AdminUser, DbSession, ResearchUser

router = APIRouter(prefix="/api/model", tags=["model"])

DRIFT_WINDOW = 500

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
    (
        "Feature contributions describe what moved this estimate. They are associations "
        "learned from synthetic records, not causes of the pain."
    ),
    "No imaging model is implemented. Documents are stored and read by the clinician.",
)

EXCLUDED = (
    "Patient self-reported score (the training reference, never an inference feature)",
    (
        "The intensity recorded against each anatomical site. It rates the same thing the "
        "estimate is for, so the structures are read and their intensities are not."
    ),
    "Any earlier prediction, and anything recorded after the assessment",
    "Patient name, telephone and emergency contact",
    "Free-text history fields and clinical notes",
)


@router.get("", response_model=schemas.ModelStatus)
def model_status(db: DbSession, user: ResearchUser) -> schemas.ModelStatus:
    rows = list(db.scalars(select(ModelVersion).order_by(ModelVersion.trained_at.desc())))
    active = next((row for row in rows if row.is_active), None)
    return schemas.ModelStatus(
        trained=active is not None,
        active=schemas.ModelOut.model_validate(active) if active else None,
        versions=[schemas.ModelOut.model_validate(row) for row in rows],
        feature_count=len(features.NAMES),
        feature_schema_version=features.FEATURE_SCHEMA_VERSION,
        excluded_from_features=list(EXCLUDED),
        limitations=list(LIMITATIONS),
        prediction_count=db.scalar(
            select(func.count())
            .select_from(PainPrediction)
            .where(PainPrediction.refused.is_(False))
        )
        or 0,
    )


@router.get("/features", response_model=list[dict])
def feature_list(user: ResearchUser) -> list[dict]:
    return [{"name": name, "label": features.LABELS[name]} for name in features.NAMES]


@router.get("/drift", response_model=schemas.DriftOut)
def model_drift(db: DbSession, user: ResearchUser) -> schemas.DriftOut:
    try:
        bundle, row = model.active(db)
    except model.ModelUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    profile = row.training_profile or bundle.training_profile
    recent = list(
        db.scalars(
            select(PainPrediction)
            .where(
                PainPrediction.refused.is_(False),
                PainPrediction.model_version == row.version,
            )
            .order_by(PainPrediction.created_at.desc())
            .limit(DRIFT_WINDOW)
        )
    )
    report = drift.assess(
        profile,
        [dict(item.features or {}) for item in recent],
        [item.estimated_pain for item in recent if item.estimated_pain is not None],
    )
    return schemas.DriftOut(
        level=report.level,
        sample_size=report.sample_size,
        warnings=report.warnings,
        features=report.features,
        prediction_shift=report.prediction_shift,
    )


@router.post("/train", response_model=schemas.JobOut, status_code=202)
def train_model(
    payload: schemas.TrainingRequest, db: DbSession, admin: AdminUser
) -> schemas.JobOut:
    job = jobs.enqueue(db, jobs.TRAIN_MODEL, payload.model_dump(), admin.id)
    return schemas.JobOut.model_validate(job)


@router.post("/{version}/activate", response_model=schemas.ModelOut)
def activate_model(version: str, db: DbSession, admin: AdminUser) -> schemas.ModelOut:
    try:
        row = model.activate(db, version)
    except model.ModelUnavailable as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ModelOut.model_validate(row)
