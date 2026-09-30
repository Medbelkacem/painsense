"""Turning stored rows into response shapes.

Identity decryption lives here so there is one place that opens a sealed patient record,
and one place to look when asking who is allowed to see a name.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas
from app.database.models import (
    PainAssessment,
    PainPrediction,
    Patient,
    PredictionCategory,
)
from app.knowledge import anatomy, causes, locations, rules
from app.security import encryption

TREND_THRESHOLD = 0.5


def identity_aad(code: str) -> bytes:
    """Binds a sealed identity to its patient code, so a blob cannot be moved between rows."""
    return f"patient:{code}".encode()


def seal_identity(code: str, identity: schemas.PatientIdentity) -> tuple[bytes, bytes]:
    return encryption.encrypt_record(identity.model_dump(), aad=identity_aad(code))


def open_identity(patient: Patient) -> schemas.PatientIdentity | None:
    if not patient.identity_blob or not patient.identity_key:
        return None
    payload = encryption.decrypt_record(
        patient.identity_blob, patient.identity_key, aad=identity_aad(patient.code)
    )
    return schemas.PatientIdentity(**payload)


def display_name(patient: Patient) -> str:
    identity = open_identity(patient)
    if identity is None:
        return patient.code
    return f"{identity.given_name} {identity.family_name}"


def trend_of(values: list[float]) -> str:
    if len(values) < 2:
        return "UNKNOWN"
    change = values[-1] - values[-2]
    if change > TREND_THRESHOLD:
        return "RISING"
    if change < -TREND_THRESHOLD:
        return "FALLING"
    return "STABLE"


def _ordered_assessments(db: Session, patient_id: uuid.UUID) -> list[PainAssessment]:
    return list(
        db.scalars(
            select(PainAssessment)
            .where(PainAssessment.patient_id == patient_id)
            .order_by(PainAssessment.created_at)
        )
    )


def patient_summary(db: Session, patient: Patient) -> schemas.PatientSummary:
    assessments = _ordered_assessments(db, patient.id)
    estimates = [
        a.prediction.estimated_pain
        for a in assessments
        if a.prediction and a.prediction.estimated_pain is not None
    ]
    latest = assessments[-1] if assessments else None
    return schemas.PatientSummary(
        id=patient.id,
        code=patient.code,
        display_name=display_name(patient),
        sex=patient.sex,
        age=patient.age_on(latest.created_at.date() if latest else patient.updated_at.date()),
        ward=patient.ward,
        is_synthetic=patient.is_synthetic,
        archived=patient.archived_at is not None,
        assessment_count=len(assessments),
        latest_assessment_at=latest.created_at if latest else None,
        latest_estimated_pain=estimates[-1] if estimates else None,
        latest_self_report=(latest.self_report.nrs if latest and latest.self_report else None),
        trend=trend_of(estimates),
    )


def patient_detail(db: Session, patient: Patient) -> schemas.PatientDetail:
    summary = patient_summary(db, patient)
    return schemas.PatientDetail(
        **summary.model_dump(),
        identity=open_identity(patient),
        birth_date=patient.birth_date,
        smoking_status=patient.smoking_status,
        medical_history=patient.medical_history,
        previous_surgeries=patient.previous_surgeries,
        allergies=patient.allergies,
        family_history=patient.family_history,
        lifestyle_notes=patient.lifestyle_notes,
        conditions=[schemas.ConditionOut.model_validate(row) for row in patient.conditions],
        medications=[schemas.MedicationOut.model_validate(row) for row in patient.medications],
        created_at=patient.created_at,
    )


def category_out(row: PredictionCategory) -> schemas.CategoryOut:
    cause = causes.BY_CODE.get(row.cause_code)
    return schemas.CategoryOut(
        cause_code=row.cause_code,
        label=cause.label if cause else row.cause_code,
        group=cause.group if cause else "",
        score=row.score,
        matched=list(row.matched or []),
        missing=list(row.missing or []),
        pain_types=list(cause.pain_types) if cause else [],
        note=cause.note if cause else "",
    )


def prediction_out(
    prediction: PainPrediction, coverage: float | None = None
) -> schemas.PredictionOut:
    band_label = None
    if prediction.estimated_pain is not None:
        band_label = rules.band(prediction.estimated_pain)[1]
    return schemas.PredictionOut(
        created_at=prediction.created_at,
        model_version=prediction.model_version,
        dataset_version=prediction.dataset_version,
        refused=prediction.refused,
        refusal_reason=prediction.refusal_reason,
        estimated_pain=prediction.estimated_pain,
        interval_low=prediction.interval_low,
        interval_high=prediction.interval_high,
        band=prediction.band,
        band_label=band_label,
        interval_nominal_level=None if prediction.refused else 0.8,
        interval_observed_coverage=coverage,
        priority_score=prediction.priority_score,
        priority_factors=list(prediction.priority_factors or []),
        data_quality=prediction.data_quality,
        quality_issues=list(prediction.quality_issues or []),
        missing_fields=list(prediction.missing_fields or []),
        confounder_notes=list(prediction.confounder_notes or []),
        features=dict(prediction.features or {}),
        contributions=[
            schemas.ContributionOut.model_validate(row)
            for row in sorted(prediction.contributions, key=lambda row: row.rank)
        ],
        categories=[
            category_out(row)
            for row in sorted(prediction.categories, key=lambda row: row.score, reverse=True)
        ],
        alerts=[schemas.AlertOut.model_validate(row) for row in prediction.alerts],
    )


def _ordered_sites(assessment: PainAssessment) -> list:
    return sorted(
        assessment.anatomical_sites,
        key=lambda row: (not row.is_primary, row.structure_code, row.side),
    )


def anatomical_sites(assessment: PainAssessment) -> list[schemas.AnatomicalSiteOut]:
    sites = []
    for row in _ordered_sites(assessment):
        structure = anatomy.BY_CODE.get(row.structure_code)
        sites.append(
            schemas.AnatomicalSiteOut(
                structure_code=row.structure_code,
                side=row.side,
                intensity=row.intensity,
                is_primary=row.is_primary,
                note=row.note,
                label=structure.label if structure else row.structure_code,
                latin=structure.latin if structure else "",
                structure_type=structure.type if structure else "",
                region=structure.region if structure else "",
                location_code=structure.location_for(row.side) if structure else "",
            )
        )
    return sites


def structure_labels(assessment: PainAssessment) -> list[str]:
    """The localised structures as one line each, for the report and the record list."""
    labels = []
    for row in _ordered_sites(assessment):
        structure = anatomy.BY_CODE.get(row.structure_code)
        label = structure.label if structure else row.structure_code
        if row.side not in ("MIDLINE", "NOT_APPLICABLE"):
            label = f"{label} ({row.side.lower()})"
        if row.intensity is not None:
            label = f"{label} {row.intensity:g}/10"
        labels.append(label)
    return labels


def location_labels(assessment: PainAssessment) -> list[str]:
    labels = []
    for row in assessment.locations:
        entry = locations.BY_CODE.get(row.location_code)
        label = entry.label if entry else row.location_code
        if row.side not in ("NOT_APPLICABLE", "MIDLINE"):
            label = f"{label} ({row.side.lower()})"
        labels.append(label)
    return labels


def assessment_summary(assessment: PainAssessment) -> schemas.AssessmentSummary:
    prediction = assessment.prediction
    return schemas.AssessmentSummary(
        id=assessment.id,
        patient_id=assessment.patient_id,
        patient_code=assessment.patient.code,
        status=assessment.status,
        created_at=assessment.created_at,
        patient_age_years=assessment.patient_age_years,
        location_labels=location_labels(assessment),
        estimated_pain=prediction.estimated_pain if prediction else None,
        band=prediction.band if prediction else None,
        priority_score=prediction.priority_score if prediction else None,
        self_report=assessment.self_report.nrs if assessment.self_report else None,
        alert_count=len(prediction.alerts) if prediction else 0,
        is_synthetic=assessment.is_synthetic,
    )


def assessment_detail(
    db: Session, assessment: PainAssessment, coverage: float | None = None
) -> schemas.AssessmentDetail:
    summary = assessment_summary(assessment)
    document_count = db.scalar(
        select(func.count())
        .select_from(PainAssessment)
        .where(PainAssessment.id == assessment.id)
        .join(PainAssessment.documents)
    )
    return schemas.AssessmentDetail(
        **summary.model_dump(),
        doctor_id=assessment.doctor_id,
        updated_at=assessment.updated_at,
        validated_at=assessment.validated_at,
        onset=assessment.onset,
        started_at=assessment.started_at,
        duration_hours=assessment.duration_hours,
        pattern=assessment.pattern,
        course=assessment.course,
        episodes_per_day=assessment.episodes_per_day,
        episode_minutes=assessment.episode_minutes,
        night_pain=assessment.night_pain,
        morning_pain=assessment.morning_pain,
        pain_after_activity=assessment.pain_after_activity,
        pain_at_rest=assessment.pain_at_rest,
        radiates=assessment.radiates,
        radiation_description=assessment.radiation_description,
        radiation_numbness=assessment.radiation_numbness,
        radiation_tingling=assessment.radiation_tingling,
        radiation_weakness=assessment.radiation_weakness,
        recent_trauma=assessment.recent_trauma,
        recent_surgery=assessment.recent_surgery,
        locations=[
            schemas.LocationIn(code=row.location_code, side=row.side, is_primary=row.is_primary)
            for row in assessment.locations
        ],
        anatomical_sites=anatomical_sites(assessment),
        quality_codes=[row.quality_code for row in assessment.qualities],
        symptom_codes=[row.symptom_code for row in assessment.symptoms],
        factor_codes=[row.factor_code for row in assessment.factors],
        confounder_codes=[row.confounder_code for row in assessment.confounders],
        answers={row.question_code: row.value for row in assessment.answers},
        measurement=(
            schemas.MeasurementOut.model_validate(assessment.measurement)
            if assessment.measurement
            else None
        ),
        self_report_detail=(
            schemas.SelfReportOut.model_validate(assessment.self_report)
            if assessment.self_report
            else None
        ),
        prediction=(
            prediction_out(assessment.prediction, coverage) if assessment.prediction else None
        ),
        notes=[
            schemas.NoteOut.model_validate(row)
            for row in sorted(assessment.notes, key=lambda row: row.created_at)
        ],
        document_count=document_count or 0,
    )


def history(db: Session, patient: Patient) -> schemas.HistoryOut:
    assessments = _ordered_assessments(db, patient.id)
    points = []
    for assessment in assessments:
        measurement = assessment.measurement
        prediction = assessment.prediction
        points.append(
            schemas.HistoryPoint(
                assessment_id=assessment.id,
                created_at=assessment.created_at,
                estimated_pain=prediction.estimated_pain if prediction else None,
                self_report=assessment.self_report.nrs if assessment.self_report else None,
                priority_score=prediction.priority_score if prediction else None,
                band=prediction.band if prediction else None,
                hr=measurement.hr if measurement else None,
                resp_rate=measurement.resp_rate if measurement else None,
                sbp=measurement.sbp if measurement else None,
                dbp=measurement.dbp if measurement else None,
                spo2=measurement.spo2 if measurement else None,
                temperature_c=measurement.temperature_c if measurement else None,
            )
        )
    estimates = [point.estimated_pain for point in points if point.estimated_pain is not None]
    return schemas.HistoryOut(
        patient_id=patient.id,
        patient_code=patient.code,
        points=points,
        trend=trend_of(estimates),
        change_from_previous=(
            round(estimates[-1] - estimates[-2], 1) if len(estimates) >= 2 else None
        ),
    )
