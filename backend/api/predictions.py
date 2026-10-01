import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from backend.ai import estimator, inputs
from backend.api import schemas, serializers
from backend.api.assessments import get_assessment
from backend.dependencies import ClinicalUser, DbSession, ResearchUser, client_ip
from database.models import (
    AssessmentAnatomicalSite,
    AssessmentMedication,
    PainAssessment,
    PainPrediction,
    PainSiteRole,
    PhysiologicalMeasurement,
)
from knowledge import rules
from knowledge.context import FUNCTIONAL_DOMAINS
from security import audit

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

SIMULATION_NOTICE = (
    "Research simulation. The inputs were changed for the purpose of seeing how the "
    "estimate responds. Nothing here was recorded on the patient's file."
)


@router.get("", response_model=list[schemas.AssessmentSummary])
def list_predictions(
    db: DbSession,
    user: ClinicalUser,
    min_priority: Annotated[float, Query(ge=0, le=10)] | None = None,
    level: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> list[schemas.AssessmentSummary]:
    filters = [PainPrediction.refused.is_(False)]
    if min_priority is not None:
        filters.append(PainPrediction.priority_score >= min_priority)
    if level:
        filters.append(PainPrediction.priority_level == level.upper())
    rows = db.scalars(
        select(PainAssessment)
        .join(PainPrediction, PainPrediction.assessment_id == PainAssessment.id)
        .where(*filters)
        .order_by(PainPrediction.priority_score.desc(), PainPrediction.created_at.desc())
        .limit(limit)
    )
    return [serializers.assessment_summary(row) for row in rows]


def _simulated_assessment(
    base: PainAssessment, payload: schemas.WhatIfRequest
) -> PainAssessment:
    shadow = PainAssessment(
        id=base.id,
        patient_id=base.patient_id,
        doctor_id=base.doctor_id,
        created_at=base.created_at,
        patient_age_years=base.patient_age_years,
    )
    for column in (
        "onset",
        "onset_speed",
        "duration_hours",
        "pattern",
        "course",
        "recurrent",
        "episodes_per_day",
        "episode_minutes",
        "night_pain",
        "morning_pain",
        "afternoon_pain",
        "evening_pain",
        "variable_timing",
        "pain_after_activity",
        "pain_at_rest",
        "radiates",
        "recent_trauma",
        "recent_surgery",
        *(f"impact_{domain}" for domain in FUNCTIONAL_DOMAINS),
    ):
        setattr(shadow, column, getattr(base, column))
    shadow.patient = base.patient
    shadow.locations = list(base.locations)
    shadow.anatomical_sites = list(base.anatomical_sites)
    shadow.qualities = list(base.qualities)
    shadow.symptoms = list(base.symptoms)
    shadow.factors = list(base.factors)
    shadow.confounders = list(base.confounders)
    shadow.medications = list(base.medications)
    shadow.answers = list(base.answers)
    shadow.measurement = base.measurement

    for field in ("onset", "pattern", "course", "duration_hours", "radiates"):
        value = getattr(payload, field)
        if value is not None:
            setattr(shadow, field, value)
    if payload.functional_impact is not None:
        for domain, score in payload.functional_impact.model_dump().items():
            setattr(shadow, f"impact_{domain}", score)
    if payload.measurement is not None:
        values = payload.measurement.model_dump(exclude={"recorded_at"})
        shadow.measurement = PhysiologicalMeasurement(
            assessment_id=base.id, recorded_at=datetime.now(timezone.utc), **values
        )
    if payload.symptom_codes is not None:
        shadow.symptoms = [
            type(base.symptoms[0])(symptom_code=code)
            if base.symptoms
            else _row("symptom_code", code)
            for code in payload.symptom_codes
        ]
    if payload.quality_codes is not None:
        shadow.qualities = [_row("quality_code", code) for code in payload.quality_codes]
    if payload.confounder_codes is not None:
        shadow.confounders = [
            _row("confounder_code", code) for code in payload.confounder_codes
        ]
    if payload.medications is not None:
        shadow.medications = [
            AssessmentMedication(assessment_id=base.id, **entry.model_dump())
            for entry in payload.medications
        ]
    if payload.anatomical_sites is not None:
        shadow.anatomical_sites = [
            AssessmentAnatomicalSite(
                assessment_id=base.id,
                structure_code=entry.structure_code,
                side=entry.side,
                role=entry.role,
                sequence=index,
                radiation_from_code=entry.radiation_from_code,
                radiation_from_side=entry.radiation_from_side,
                quality_codes=list(entry.quality_codes),
                onset=entry.onset,
                pattern=entry.pattern,
                course=entry.course,
                intensity=entry.intensity,
                is_primary=entry.role is PainSiteRole.PRIMARY,
            )
            for index, entry in enumerate(payload.anatomical_sites)
        ]
    return shadow


class _row:
    def __init__(self, attribute: str, code: str) -> None:
        setattr(self, attribute, code)


def _prediction_snapshot(result: estimator.Estimate, base: PainAssessment) -> PainPrediction:
    prediction = PainPrediction(
        assessment_id=base.id,
        patient_id=base.patient_id,
        created_at=datetime.now(timezone.utc),
        model_name=result.model_name,
        model_version=result.model_version,
        dataset_version=result.dataset_version,
        feature_schema_version=result.feature_schema_version,
        inference_ms=result.inference_ms,
        estimated_pain=result.interval.point if result.interval else None,
        interval_low=result.interval.low if result.interval else None,
        interval_high=result.interval.high if result.interval else None,
        band=result.band_code,
        priority_score=result.priority.score,
        priority_level=result.priority.level,
        priority_factors=[
            {"code": f.code, "label": f.label, "points": f.points}
            for f in result.priority.factors
        ],
        trajectory=result.baseline.trajectory,
        baseline=result.baseline.to_dict(),
        data_quality=result.quality.level,
        data_quality_score=result.quality.score,
        quality_issues=list(result.quality.issues) + list(result.quality.outliers),
        missing_fields=list(result.quality.missing),
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        features=result.feature_values,
        confounder_notes=[],
    )
    prediction.contributions = []
    prediction.categories = []
    prediction.alerts = []
    return prediction


@router.post("/{assessment_id}/what-if", response_model=schemas.WhatIfOut)
def what_if(
    assessment_id: uuid.UUID,
    payload: schemas.WhatIfRequest,
    request: Request,
    db: DbSession,
    user: ResearchUser,
) -> schemas.WhatIfOut:
    base = get_assessment(db, assessment_id)
    shadow = _simulated_assessment(base, payload)
    ctx = inputs.context_for(shadow)
    result = estimator.estimate(db, ctx, estimator.earlier_assessments(base))

    simulated = _prediction_snapshot(result, base)
    original = base.prediction
    changed = []
    if original is not None and original.features:
        for name, after in result.feature_values.items():
            before = original.features.get(name)
            if before != after:
                changed.append({"feature": name, "before": before, "after": after})

    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(base.id),
        client_ip=client_ip(request),
        meta={"action": "what_if_simulation", "changed_features": len(changed)},
    )

    db.expunge_all()
    return schemas.WhatIfOut(
        assessment_id=base.id,
        original=serializers.prediction_out(original) if original else None,
        simulated=serializers.prediction_out(simulated),
        changed_features=changed,
        notice=SIMULATION_NOTICE,
    )


@router.get("/levels", response_model=list[dict])
def priority_levels(user: ClinicalUser) -> list[dict]:
    return [
        {"code": code, "label": label, "upper_bound": upper}
        for upper, code, label in rules.PRIORITY_LEVELS
    ] + [{"code": "DISCLAIMER", "label": rules.PRIORITY_DISCLAIMER, "upper_bound": None}]


@router.get("/{assessment_id}", response_model=schemas.PredictionOut)
def read_prediction(
    assessment_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.PredictionOut:
    assessment = get_assessment(db, assessment_id)
    if assessment.prediction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No prediction has been produced")
    return serializers.prediction_out(assessment.prediction)
