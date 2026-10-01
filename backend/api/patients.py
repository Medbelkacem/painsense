import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.ai import trajectory
from backend.ai.quality import VITAL_LABELS
from backend.api import schemas, serializers
from database.models import (
    ADMIN_ROLES,
    Disease,
    MedicalDocument,
    PainAssessment,
    Patient,
    PatientBaseline,
    PatientCondition,
    PatientMedication,
    User,
)
from backend.dependencies import ClinicalUser, DbSession, client_ip
from knowledge import medications as medications_kb
from knowledge import rules
from security import audit

router = APIRouter(prefix="/api/patients", tags=["patients"])

CODE_PREFIX = "PS"
NAME_SEARCH_CEILING = 2000
CODE_RETRIES = 5


def next_patient_code(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"{CODE_PREFIX}-{year}-"
    highest = db.scalar(select(func.max(Patient.code)).where(Patient.code.like(f"{prefix}%")))
    counter = int(highest.removeprefix(prefix)) + 1 if highest else 1
    return f"{prefix}{counter:06d}"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _record_view(db: Session, request: Request, user: User, patient: Patient) -> None:
    audit.record(
        db,
        event_type=audit.PATIENT_VIEWED,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient",
        resource_id=patient.code,
        client_ip=client_ip(request),
    )


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


def _may_modify(db: Session, patient: Patient, user: User) -> bool:
    if user.role in ADMIN_ROLES or patient.created_by == user.id:
        return True
    return bool(
        db.scalar(
            select(PainAssessment.id)
            .where(PainAssessment.patient_id == patient.id, PainAssessment.doctor_id == user.id)
            .limit(1)
        )
    )


def require_modify(db: Session, patient: Patient, user: User) -> Patient:
    if not _may_modify(db, patient, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the clinician who created or assessed this patient can change the record",
        )
    return patient


def _check_disease_codes(db: Session, codes: list[str]) -> None:
    if not codes:
        return
    known = set(db.scalars(select(Disease.code).where(Disease.code.in_(codes))))
    unknown = sorted(set(codes) - known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown chronic condition codes: {', '.join(unknown)}",
        )


def _replace_conditions(db: Session, patient: Patient, codes: list[str]) -> None:
    _check_disease_codes(db, codes)
    patient.conditions.clear()
    db.flush()
    for code in dict.fromkeys(codes):
        patient.conditions.append(PatientCondition(patient_id=patient.id, disease_code=code))


def _replace_medications(patient: Patient, medications: list[schemas.MedicationIn]) -> None:
    patient.medications.clear()
    for entry in medications:
        patient.medications.append(
            PatientMedication(patient_id=patient.id, **entry.model_dump())
        )


@router.get("", response_model=schemas.PatientPage)
def list_patients(
    db: DbSession,
    user: ClinicalUser,
    search: Annotated[str | None, Query(max_length=120)] = None,
    ward: Annotated[str | None, Query(max_length=80)] = None,
    include_archived: bool = False,
    synthetic_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.PatientPage:
    filters = []
    if not include_archived:
        filters.append(Patient.archived_at.is_(None))
    if ward:
        filters.append(Patient.ward == ward)
    if synthetic_only:
        filters.append(Patient.is_synthetic.is_(True))

    term = (search or "").strip()
    newest_first = select(Patient).where(*filters).order_by(Patient.created_at.desc())

    if not term:
        total = db.scalar(select(func.count()).select_from(Patient).where(*filters)) or 0
        page = list(db.scalars(newest_first.offset(offset).limit(limit)))
    else:
        escaped = _escape_like(term)
        matched = newest_first.where(
            or_(
                Patient.code.like(f"%{escaped.upper()}%", escape="\\"),
                Patient.ward.ilike(f"%{escaped}%", escape="\\"),
            )
        )
        matches = list(db.scalars(matched))
        if not matches:
            lowered = term.lower()
            matches = [
                row
                for row in db.scalars(newest_first.limit(NAME_SEARCH_CEILING))
                if lowered in serializers.display_name(row).lower()
            ]
        total = len(matches)
        page = matches[offset : offset + limit]

    return schemas.PatientPage(
        items=[serializers.patient_summary(db, row) for row in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=schemas.PatientDetail, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: schemas.PatientCreate, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.PatientDetail:
    fields = payload.model_dump(exclude={"identity", "condition_codes", "medications"})

    for attempt in range(CODE_RETRIES):
        code = next_patient_code(db)
        blob, key = serializers.seal_identity(code, payload.identity)
        patient = Patient(
            code=code, identity_blob=blob, identity_key=key, created_by=user.id, **fields
        )
        db.add(patient)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == CODE_RETRIES - 1:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Could not allocate a patient code. Try again.",
                ) from None
    db.flush()
    _replace_conditions(db, patient, payload.condition_codes)
    _replace_medications(patient, payload.medications)
    db.commit()
    db.refresh(patient)

    audit.record(
        db,
        event_type=audit.PATIENT_CREATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient",
        resource_id=code,
        client_ip=client_ip(request),
        meta={"synthetic": patient.is_synthetic},
        ledger_payload={
            "code": code,
            "sex": patient.sex.value,
            "birth_date": patient.birth_date,
            "conditions": sorted(row.disease_code for row in patient.conditions),
            "created_by": str(user.id),
        },
    )
    return serializers.patient_detail(db, patient)


@router.get("/{patient_id}", response_model=schemas.PatientDetail)
def read_patient(
    patient_id: uuid.UUID, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.PatientDetail:
    patient = get_patient(db, patient_id)
    _record_view(db, request, user, patient)
    return serializers.patient_detail(db, patient)


@router.patch("/{patient_id}", response_model=schemas.PatientDetail)
def update_patient(
    patient_id: uuid.UUID,
    payload: schemas.PatientUpdate,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.PatientDetail:
    patient = require_modify(db, get_patient(db, patient_id), user)
    changes = payload.model_dump(exclude_unset=True)

    if "identity" in changes and payload.identity is not None:
        patient.identity_blob, patient.identity_key = serializers.seal_identity(
            patient.code, payload.identity
        )
    if "condition_codes" in changes and payload.condition_codes is not None:
        _replace_conditions(db, patient, payload.condition_codes)
    if "medications" in changes and payload.medications is not None:
        _replace_medications(patient, payload.medications)

    for field, value in changes.items():
        if field not in ("identity", "condition_codes", "medications"):
            setattr(patient, field, value)
    db.commit()
    db.refresh(patient)

    audit.record(
        db,
        event_type=audit.PATIENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient",
        resource_id=patient.code,
        client_ip=client_ip(request),
        meta={"fields": sorted(changes)},
        ledger_payload={
            "code": patient.code,
            "sex": patient.sex.value,
            "birth_date": patient.birth_date,
            "conditions": sorted(row.disease_code for row in patient.conditions),
            "updated_at": patient.updated_at,
        },
    )
    return serializers.patient_detail(db, patient)


@router.post("/{patient_id}/archive", response_model=schemas.PatientDetail)
def archive_patient(
    patient_id: uuid.UUID, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.PatientDetail:
    patient = require_modify(db, get_patient(db, patient_id), user)
    patient.archived_at = patient.archived_at or datetime.now(timezone.utc)
    db.commit()
    audit.record(
        db,
        event_type=audit.PATIENT_ARCHIVED,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient",
        resource_id=patient.code,
        client_ip=client_ip(request),
        ledger_payload={"code": patient.code, "archived_at": patient.archived_at},
    )
    return serializers.patient_detail(db, patient)


@router.get("/{patient_id}/history", response_model=schemas.HistoryOut)
def patient_history(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.HistoryOut:
    return serializers.history(db, get_patient(db, patient_id))


@router.get("/{patient_id}/assessments", response_model=list[schemas.AssessmentSummary])
def patient_assessments(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> list[schemas.AssessmentSummary]:
    get_patient(db, patient_id)
    rows = db.scalars(
        select(PainAssessment)
        .where(PainAssessment.patient_id == patient_id)
        .order_by(PainAssessment.created_at.desc())
    )
    return [serializers.assessment_summary(row) for row in rows]


def _timeline_events(db: Session, patient: Patient) -> list[schemas.TimelineEvent]:
    events: list[schemas.TimelineEvent] = []

    def add(at, kind, title, detail=None, assessment_id=None, value=None, level=None):
        events.append(
            schemas.TimelineEvent(
                at=at,
                kind=kind,
                title=title,
                detail=detail,
                assessment_id=assessment_id,
                value=value,
                level=level,
            )
        )

    assessments = db.scalars(
        select(PainAssessment)
        .where(PainAssessment.patient_id == patient.id)
        .order_by(PainAssessment.created_at)
    )
    for assessment in assessments:
        sites = serializers.structure_labels(assessment) or serializers.location_labels(
            assessment
        )
        add(
            assessment.created_at,
            "ASSESSMENT",
            "Assessment recorded",
            ", ".join(sites) if sites else None,
            assessment.id,
        )
        prediction = assessment.prediction
        if prediction is not None:
            if prediction.refused:
                add(
                    prediction.created_at,
                    "PREDICTION",
                    "Estimate withheld",
                    prediction.refusal_reason,
                    assessment.id,
                )
            else:
                level = rules.priority_level(prediction.priority_score or 0.0)[1]
                add(
                    prediction.created_at,
                    "PREDICTION",
                    f"AI estimated pain {prediction.estimated_pain:.1f} / 10",
                    f"Clinical priority {prediction.priority_score:.1f} / 10 ({level}), "
                    f"trajectory {prediction.trajectory.lower()}",
                    assessment.id,
                    prediction.estimated_pain,
                    prediction.priority_level,
                )
        if assessment.self_report is not None:
            add(
                assessment.self_report.reported_at,
                "SELF_REPORT",
                f"Patient-reported score {assessment.self_report.nrs:g} / 10",
                assessment.self_report.note,
                assessment.id,
                assessment.self_report.nrs,
            )
        measurement = assessment.measurement
        if measurement is not None:
            parts = []
            for name, label in VITAL_LABELS.items():
                value = getattr(measurement, name, None)
                if value is not None:
                    parts.append(f"{label} {value:g}")
            if parts:
                add(
                    measurement.recorded_at,
                    "MEASUREMENT",
                    "Measurements recorded",
                    ", ".join(parts),
                    assessment.id,
                )
        for row in assessment.medications:
            entry = medications_kb.BY_CODE.get(row.class_code)
            add(
                assessment.created_at,
                "MEDICATION",
                entry.label if entry else row.class_code,
                row.name,
                assessment.id,
            )
        if assessment.validated_at is not None:
            agreement = (
                assessment.review_agreement.value.lower()
                if assessment.review_agreement
                else "reviewed"
            )
            add(
                assessment.validated_at,
                "REVIEW",
                "Reviewed and signed off by the clinician",
                f"Position on the estimate: {agreement}"
                + (f". {assessment.review_comment}" if assessment.review_comment else ""),
                assessment.id,
            )
        for note in assessment.notes:
            add(note.created_at, "NOTE", "Clinical note", note.body, assessment.id)

    documents = db.scalars(
        select(MedicalDocument).where(MedicalDocument.patient_id == patient.id)
    )
    for document in documents:
        add(
            document.uploaded_at,
            "DOCUMENT",
            f"{document.kind.value.title()} document uploaded",
            document.original_filename,
            document.assessment_id,
        )
    reports = db.scalars(
        select(audit.AuditLog)
        .where(
            audit.AuditLog.event_type == audit.REPORT_GENERATED,
            audit.AuditLog.meta["patient_code"].as_string() == patient.code,
        )
        .order_by(audit.AuditLog.timestamp)
    )
    for entry in reports:
        add(entry.timestamp, "REPORT", "PDF report generated", entry.actor_label, None)

    events.sort(key=lambda event: event.at, reverse=True)
    return events


@router.get("/{patient_id}/timeline", response_model=schemas.TimelineOut)
def patient_timeline(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.TimelineOut:
    patient = get_patient(db, patient_id)
    return schemas.TimelineOut(
        patient_id=patient.id, patient_code=patient.code, events=_timeline_events(db, patient)
    )


@router.get("/{patient_id}/baseline", response_model=schemas.BaselineOut)
def patient_baseline(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BaselineOut:
    patient = get_patient(db, patient_id)
    ordered = sorted(patient.assessments, key=lambda row: row.created_at)
    latest = ordered[-1] if ordered else None
    earlier = []
    for row in ordered[:-1]:
        vitals = {}
        if row.measurement is not None:
            for name in trajectory.BASELINE_TOLERANCE:
                value = getattr(row.measurement, name)
                if value is not None:
                    vitals[name] = float(value)
        earlier.append(
            trajectory.EarlierAssessment(
                created_at=row.created_at,
                estimated_pain=row.prediction.estimated_pain if row.prediction else None,
                vitals=vitals,
            )
        )
    current_vitals = {}
    current_pain = None
    if latest is not None:
        if latest.measurement is not None:
            for name in trajectory.BASELINE_TOLERANCE:
                value = getattr(latest.measurement, name)
                if value is not None:
                    current_vitals[name] = float(value)
        if latest.prediction is not None:
            current_pain = latest.prediction.estimated_pain
    comparison = trajectory.compare(earlier, current_pain, current_vitals)
    return schemas.BaselineOut(
        patient_id=patient.id,
        assessments_used=len(earlier),
        vitals=[
            schemas.BaselineVital(
                field=name,
                label=VITAL_LABELS[name],
                baseline=entry["baseline"],
                current=entry.get("current"),
                delta=entry.get("delta"),
                readings=int(entry["readings"]),
                departed=name in comparison.departures,
            )
            for name, entry in comparison.vitals.items()
        ],
        previous_pain=comparison.previous_pain,
        current_pain=current_pain,
        trajectory=comparison.trajectory,
        pain_change=comparison.pain_change,
    )


@router.put("/{patient_id}/calibration", response_model=schemas.CalibrationOut)
def record_calibration(
    patient_id: uuid.UUID,
    payload: schemas.CalibrationIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.CalibrationOut:
    """Record the patient at rest. This is the short initial calibration the brief asks for
    in section 18: once it exists, later readings are compared against this patient's own
    resting values instead of against the median of earlier visits, which are not resting
    states. Recording a new one replaces the old one."""
    patient = get_patient(db, patient_id)
    if patient.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This patient record is archived")

    baseline = patient.baseline
    if baseline is None:
        baseline = PatientBaseline(patient_id=patient.id)
        db.add(baseline)

    baseline.recorded_at = datetime.now(timezone.utc)
    baseline.recorded_by = user.id
    for field, value in payload.model_dump().items():
        setattr(baseline, field, value)
    db.commit()
    db.refresh(baseline)

    audit.record(
        db,
        event_type=audit.PATIENT_UPDATED,
        actor_id=user.id,
        resource="patient",
        resource_id=str(patient.id),
        client_ip=client_ip(request),
        meta={"calibration": sorted(baseline.vitals)},
    )
    return schemas.CalibrationOut.model_validate(baseline)


@router.get("/{patient_id}/calibration", response_model=schemas.CalibrationOut | None)
def read_calibration(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.CalibrationOut | None:
    baseline = get_patient(db, patient_id).baseline
    return None if baseline is None else schemas.CalibrationOut.model_validate(baseline)
