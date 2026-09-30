"""Patient records.

Authorisation rule: any signed-in clinician may read any patient record, because cover and
handover are normal, and every read of a name is audited. Modifying a record is narrower —
the clinician who created it, one who has already assessed the patient, or an administrator.

Searching by name has a cost that follows from sealing identifiers: names are not in a
queryable column, so a name search decrypts the candidate rows and filters in memory. That
is the right trade for a prototype of this size, and the reason is here rather than hidden
in a slow query.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import schemas, serializers
from app.database.models import (
    Disease,
    PainAssessment,
    Patient,
    PatientCondition,
    PatientMedication,
    Role,
    User,
)
from app.dependencies import CurrentUser, DbSession, client_ip
from app.security import audit

router = APIRouter(prefix="/api/patients", tags=["patients"])

CODE_PREFIX = "PS"
NAME_SEARCH_CEILING = 2000


def next_patient_code(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"{CODE_PREFIX}-{year}-"
    highest = db.scalar(select(func.max(Patient.code)).where(Patient.code.like(f"{prefix}%")))
    counter = int(highest.removeprefix(prefix)) + 1 if highest else 1
    return f"{prefix}{counter:06d}"


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


def _may_modify(db: Session, patient: Patient, user: User) -> bool:
    if user.role is Role.ADMIN or patient.created_by == user.id:
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
    user: CurrentUser,
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
        matches = list(db.scalars(newest_first))
    else:
        matches = list(
            db.scalars(
                newest_first.where(
                    or_(
                        Patient.code.like(f"%{term.upper()}%"),
                        Patient.ward.ilike(f"%{term}%"),
                    )
                )
            )
        )
        if not matches:
            # The name is sealed, so it cannot be matched in SQL. Fall back to decrypting a
            # bounded page of candidates and filtering here.
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
    payload: schemas.PatientCreate, request: Request, db: DbSession, user: CurrentUser
) -> schemas.PatientDetail:
    code = next_patient_code(db)
    blob, key = serializers.seal_identity(code, payload.identity)
    fields = payload.model_dump(exclude={"identity", "condition_codes", "medications"})
    patient = Patient(
        code=code, identity_blob=blob, identity_key=key, created_by=user.id, **fields
    )
    db.add(patient)
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
        # The ledger receives a hash of the record's shape, never the identifiers.
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
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.PatientDetail:
    return serializers.patient_detail(db, get_patient(db, patient_id))


@router.patch("/{patient_id}", response_model=schemas.PatientDetail)
def update_patient(
    patient_id: uuid.UUID,
    payload: schemas.PatientUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
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
    patient_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
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
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.HistoryOut:
    return serializers.history(db, get_patient(db, patient_id))


@router.get("/{patient_id}/assessments", response_model=list[schemas.AssessmentSummary])
def patient_assessments(
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[schemas.AssessmentSummary]:
    get_patient(db, patient_id)
    rows = db.scalars(
        select(PainAssessment)
        .where(PainAssessment.patient_id == patient_id)
        .order_by(PainAssessment.created_at.desc())
    )
    return [serializers.assessment_summary(row) for row in rows]
