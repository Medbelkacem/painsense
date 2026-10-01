import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.ai import estimator, inputs, model
from backend.api import schemas, serializers
from backend.api.patients import get_patient, require_view
from backend.dependencies import ClinicalUser, DbSession, ViewerUser, client_ip
from database.models import (
    ADMIN_ROLES,
    AnatomicalStructure,
    AssessmentAnatomicalSite,
    AssessmentAnswer,
    AssessmentConfounder,
    AssessmentFactor,
    AssessmentLocation,
    AssessmentMedication,
    AssessmentQuality,
    AssessmentStatus,
    AssessmentSymptom,
    ClinicalNote,
    ClinicalQuestion,
    Confounder,
    MedicationClass,
    PainAssessment,
    PainFactor,
    PainLocation,
    PainQuality,
    PainSiteRole,
    PhysiologicalMeasurement,
    Role,
    SelfReport,
    Symptom,
    User,
)
from knowledge import anatomy, scales
from knowledge import symptoms as symptoms_kb
from knowledge.context import FUNCTIONAL_DOMAINS
from security import audit

router = APIRouter(prefix="/api/assessments", tags=["assessments"])

COMPARISON_FIELDS = (
    ("estimated_pain", "Estimated pain"),
    ("self_report", "Patient-reported score"),
    ("priority_score", "Clinical priority indicator"),
    ("hr", "Heart rate"),
    ("resp_rate", "Respiratory rate"),
    ("sbp", "Systolic blood pressure"),
    ("dbp", "Diastolic blood pressure"),
    ("spo2", "Oxygen saturation"),
    ("temperature_c", "Temperature"),
)


def get_assessment(db: Session, assessment_id: uuid.UUID) -> PainAssessment:
    assessment = db.get(PainAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def require_owner(assessment: PainAssessment, user: User) -> PainAssessment:
    if user.role not in ADMIN_ROLES and assessment.doctor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the clinician who recorded this assessment can change it",
        )
    return assessment


def require_doctor(user: User) -> User:
    if user.role is not Role.DOCTOR:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Only a doctor can validate an assessment"
        )
    return user


def _set_duration(assessment: PainAssessment) -> None:
    value, unit = assessment.duration_value, assessment.duration_unit
    if value is None or unit is None:
        assessment.duration_value = assessment.duration_unit = assessment.duration_hours = None
        return
    assessment.duration_hours = round(value * schemas.HOURS_PER_UNIT[unit], 4)


def require_open(assessment: PainAssessment) -> PainAssessment:
    if assessment.status is AssessmentStatus.VALIDATED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This assessment has been validated. Record a new assessment instead.",
        )
    return assessment


def _validate_codes(db: Session, table, codes: list[str], label: str) -> list[str]:
    unique = list(dict.fromkeys(codes))
    if not unique:
        return unique
    known = set(db.scalars(select(table.code).where(table.code.in_(unique))))
    unknown = sorted(set(unique) - known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown {label} codes: {', '.join(unknown)}",
        )
    return unique


def _set_measurement(
    db: Session, assessment: PainAssessment, payload: schemas.MeasurementIn
) -> None:
    values = payload.model_dump(exclude={"recorded_at"})
    recorded_at = payload.recorded_at or datetime.now(timezone.utc)
    if assessment.measurement is None:
        assessment.measurement = PhysiologicalMeasurement(
            assessment_id=assessment.id, recorded_at=recorded_at, **values
        )
        return
    assessment.measurement.recorded_at = recorded_at
    for field, value in values.items():
        setattr(assessment.measurement, field, value)


def _set_self_report(
    db: Session, assessment: PainAssessment, payload: schemas.SelfReportIn
) -> None:
    reported_at = payload.reported_at or datetime.now(timezone.utc)
    scale = scales.BY_CODE[payload.scale_code]
    if assessment.self_report is None:
        assessment.self_report = SelfReport(
            assessment_id=assessment.id,
            patient_id=assessment.patient_id,
            nrs=payload.nrs,
            scale_code=payload.scale_code,
            raw_score=payload.raw_score,
            raw_max=scale.maximum,
            items=dict(payload.items),
            observed=bool(payload.observed),
            reported_at=reported_at,
            note=payload.note,
        )
        return
    assessment.self_report.nrs = payload.nrs
    assessment.self_report.scale_code = payload.scale_code
    assessment.self_report.raw_score = payload.raw_score
    assessment.self_report.raw_max = scale.maximum
    assessment.self_report.items = dict(payload.items)
    assessment.self_report.observed = bool(payload.observed)
    assessment.self_report.reported_at = reported_at
    assessment.self_report.note = payload.note


def _recorded_locations(sites) -> dict[str, tuple[str, bool]]:
    recorded: dict[str, tuple[str, bool]] = {}
    for row in sites:
        for code, side in anatomy.projected_locations(row.structure_code, row.side):
            previous = recorded.get(code)
            recorded[code] = (
                (anatomy.combine_sides(previous[0], side), previous[1] or row.is_primary)
                if previous is not None
                else (side, row.is_primary)
            )
    return recorded


def _write_sites(
    db: Session, assessment: PainAssessment, entries: list[schemas.AnatomicalSiteIn]
) -> None:
    _validate_codes(
        db,
        AnatomicalStructure,
        [entry.structure_code for entry in entries],
        "anatomical structure",
    )
    _validate_codes(
        db,
        PainQuality,
        [code for entry in entries for code in entry.quality_codes],
        "pain quality",
    )
    assessment.anatomical_sites.clear()
    db.flush()

    unique: list[schemas.AnatomicalSiteIn] = []
    seen = set()
    for entry in entries:
        key = (entry.structure_code, entry.side)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)

    primaries = [entry for entry in unique if entry.role is PainSiteRole.PRIMARY]
    if unique and not primaries:
        unique[0].role = PainSiteRole.PRIMARY
        unique[0].is_primary = True
    for extra in primaries[1:]:
        extra.role = PainSiteRole.SECONDARY
        extra.is_primary = False

    for sequence, entry in enumerate(unique):
        structure = anatomy.BY_CODE.get(entry.structure_code)
        if structure is not None and not structure.accepts(entry.side):
            accepted = ", ".join(anatomy.SIDES_FOR_LATERALITY[structure.laterality])
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{structure.label} cannot be recorded on the "
                    f"{entry.side.lower().replace('_', ' ')} side. It accepts: {accepted}."
                ),
            )
        origin = None
        if entry.role is PainSiteRole.RADIATING and entry.radiation_from_code:
            origin = (entry.radiation_from_code, entry.radiation_from_side)
            if origin not in seen or origin == (entry.structure_code, entry.side):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"The radiating site {entry.structure_code} names an origin that is "
                        "not among the recorded sites."
                    ),
                )
        assessment.anatomical_sites.append(
            AssessmentAnatomicalSite(
                assessment_id=assessment.id,
                structure_code=entry.structure_code,
                side=entry.side,
                role=entry.role,
                sequence=sequence,
                radiation_from_code=origin[0] if origin else None,
                radiation_from_side=origin[1] if origin else None,
                quality_codes=list(dict.fromkeys(entry.quality_codes)),
                onset=entry.onset,
                pattern=entry.pattern,
                course=entry.course,
                intensity=entry.intensity,
                is_primary=entry.role is PainSiteRole.PRIMARY,
                note=entry.note,
            )
        )


def _apply_sites(
    db: Session,
    assessment: PainAssessment,
    locations_in: list[schemas.LocationIn] | None,
    sites_in: list[schemas.AnatomicalSiteIn] | None,
) -> None:
    if locations_in is None and sites_in is None:
        return

    recorded_before = _recorded_locations(assessment.anatomical_sites)
    if locations_in is not None:
        _validate_codes(
            db, PainLocation, [entry.code for entry in locations_in], "pain location"
        )
        merged = {entry.code: (entry.side, entry.is_primary) for entry in locations_in}
    else:
        merged = {
            row.location_code: (row.side, row.is_primary)
            for row in assessment.locations
            if row.location_code not in recorded_before
        }

    if sites_in is not None:
        _write_sites(db, assessment, sites_in)

    for code, (side, is_primary) in _recorded_locations(assessment.anatomical_sites).items():
        previous = merged.get(code)
        merged[code] = (
            (anatomy.combine_sides(previous[0], side), previous[1] or is_primary)
            if previous is not None
            else (side, is_primary)
        )

    assessment.locations.clear()
    db.flush()
    for code, (side, is_primary) in merged.items():
        assessment.locations.append(
            AssessmentLocation(
                assessment_id=assessment.id,
                location_code=code,
                side=side,
                is_primary=is_primary,
            )
        )


def _apply_collections(db: Session, assessment: PainAssessment, changes: dict) -> None:
    _apply_sites(db, assessment, changes.get("locations"), changes.get("anatomical_sites"))

    simple = (
        ("quality_codes", PainQuality, AssessmentQuality, "quality_code", "pain quality"),
        ("symptom_codes", Symptom, AssessmentSymptom, "symptom_code", "symptom"),
        ("factor_codes", PainFactor, AssessmentFactor, "factor_code", "factor"),
        (
            "confounder_codes",
            Confounder,
            AssessmentConfounder,
            "confounder_code",
            "contextual factor",
        ),
    )
    collections = {
        "quality_codes": assessment.qualities,
        "symptom_codes": assessment.symptoms,
        "factor_codes": assessment.factors,
        "confounder_codes": assessment.confounders,
    }
    for field, table, row_model, column, label in simple:
        if field not in changes or changes[field] is None:
            continue
        codes = _validate_codes(db, table, changes[field], label)
        collections[field].clear()
        db.flush()
        for code in codes:
            collections[field].append(
                row_model(**{"assessment_id": assessment.id, column: code})
            )

    if "answers" in changes and changes["answers"] is not None:
        answers = changes["answers"]
        _validate_codes(db, ClinicalQuestion, list(answers), "clinical question")
        assessment.answers.clear()
        db.flush()
        for code, value in answers.items():
            assessment.answers.append(
                AssessmentAnswer(assessment_id=assessment.id, question_code=code, value=value)
            )

    if changes.get("medications") is not None:
        entries = changes["medications"]
        _validate_codes(
            db, MedicationClass, [entry["class_code"] for entry in entries], "medication class"
        )
        assessment.medications.clear()
        db.flush()
        for entry in entries:
            assessment.medications.append(
                AssessmentMedication(assessment_id=assessment.id, **entry)
            )

    if changes.get("functional_impact") is not None:
        for domain, score in changes["functional_impact"].items():
            if domain in FUNCTIONAL_DOMAINS:
                setattr(assessment, f"impact_{domain}", score)


COLLECTION_FIELDS = frozenset(
    {
        "locations",
        "anatomical_sites",
        "quality_codes",
        "symptom_codes",
        "factor_codes",
        "confounder_codes",
        "medications",
        "functional_impact",
        "answers",
        "measurement",
        "self_report",
    }
)


@router.post("", response_model=schemas.AssessmentDetail, status_code=status.HTTP_201_CREATED)
def create_assessment(
    payload: schemas.AssessmentCreate, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.AssessmentDetail:
    patient = get_patient(db, payload.patient_id)
    if patient.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This patient record is archived")

    scalar_fields = payload.model_dump(exclude=COLLECTION_FIELDS | {"patient_id"})
    today = datetime.now(timezone.utc).date()
    # Age in whole years cannot separate a newborn from a toddler, and the profiles that
    # differ most live inside that first year, so the month count is recorded too.
    if scalar_fields.get("profile_code") is None:
        scalar_fields["profile_code"] = patient.profile_code
    assessment = PainAssessment(
        patient_id=patient.id,
        doctor_id=user.id,
        is_synthetic=patient.is_synthetic,
        patient_age_years=patient.age_on(today),
        patient_age_months=patient.age_months_on(today),
        **scalar_fields,
    )
    _set_duration(assessment)
    db.add(assessment)
    db.flush()

    _apply_collections(
        db,
        assessment,
        {
            "locations": payload.locations,
            "anatomical_sites": payload.anatomical_sites,
            "quality_codes": payload.quality_codes,
            "symptom_codes": payload.symptom_codes,
            "factor_codes": payload.factor_codes,
            "confounder_codes": payload.confounder_codes,
            "medications": [entry.model_dump() for entry in payload.medications],
            "functional_impact": payload.functional_impact.model_dump(),
            "answers": payload.answers,
        },
    )
    if payload.measurement is not None:
        _set_measurement(db, assessment, payload.measurement)
    if payload.self_report is not None:
        _set_self_report(db, assessment, payload.self_report)
    db.commit()
    db.refresh(assessment)

    audit.record(
        db,
        event_type=audit.ASSESSMENT_CREATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"patient": patient.code},
        ledger_payload=_ledger_payload(assessment),
    )
    return serializers.assessment_detail(db, assessment)


def _ledger_payload(assessment: PainAssessment) -> dict:
    return {
        "assessment_id": str(assessment.id),
        "patient_code": assessment.patient.code,
        "age": assessment.patient_age_years,
        "status": assessment.status.value,
        "locations": sorted(row.location_code for row in assessment.locations),
        "anatomical_sites": [
            {
                "structure": row.structure_code,
                "side": row.side,
                "role": row.role.value,
                "radiation_from": row.radiation_from_code,
                "qualities": sorted(row.quality_codes or []),
                "intensity": row.intensity,
            }
            for row in sorted(
                assessment.anatomical_sites, key=lambda row: (row.structure_code, row.side)
            )
        ],
        "medications": sorted(
            (row.class_code, row.dose_category, row.hours_since_last_dose)
            for row in assessment.medications
        ),
        "functional_impact": {
            domain: getattr(assessment, f"impact_{domain}") for domain in FUNCTIONAL_DOMAINS
        },
        "review": (
            {
                "agreement": assessment.review_agreement.value,
                "comment": assessment.review_comment,
            }
            if assessment.review_agreement
            else None
        ),
        "qualities": sorted(row.quality_code for row in assessment.qualities),
        "symptoms": sorted(row.symptom_code for row in assessment.symptoms),
        "factors": sorted(row.factor_code for row in assessment.factors),
        "confounders": sorted(row.confounder_code for row in assessment.confounders),
        "answers": {row.question_code: row.value for row in assessment.answers},
        "onset": assessment.onset.value,
        "pattern": assessment.pattern.value,
        "course": assessment.course.value,
        "duration": serializers.duration_label(
            assessment.duration_value, assessment.duration_unit
        ),
        "radiates": assessment.radiates,
        "measurement": (
            {
                "hr": assessment.measurement.hr,
                "resp_rate": assessment.measurement.resp_rate,
                "sbp": assessment.measurement.sbp,
                "dbp": assessment.measurement.dbp,
                "spo2": assessment.measurement.spo2,
                "temperature_c": assessment.measurement.temperature_c,
                "glucose_mmol": assessment.measurement.glucose_mmol,
            }
            if assessment.measurement
            else None
        ),
        "self_report": assessment.self_report.nrs if assessment.self_report else None,
    }


@router.get("", response_model=schemas.AssessmentPage)
def list_assessments(
    db: DbSession,
    user: ViewerUser,
    patient_id: uuid.UUID | None = None,
    status_filter: Annotated[AssessmentStatus | None, Query(alias="status")] = None,
    mine_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AssessmentPage:
    filters = []
    if user.role is Role.PATIENT:
        # A patient account lists its own record whatever the query says.
        patient_id = user.patient_id
        if patient_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No patient record is linked")
    if patient_id is not None:
        filters.append(PainAssessment.patient_id == patient_id)
    if status_filter is not None:
        filters.append(PainAssessment.status == status_filter)
    if mine_only:
        filters.append(PainAssessment.doctor_id == user.id)

    total = db.scalar(select(func.count()).select_from(PainAssessment).where(*filters)) or 0
    rows = db.scalars(
        select(PainAssessment)
        .where(*filters)
        .order_by(PainAssessment.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return schemas.AssessmentPage(
        items=[serializers.assessment_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _coverage(db: Session) -> float | None:
    row = model.active_row(db)
    if row is None:
        return None
    try:
        return model.load(row.version).observed_coverage
    except model.ModelUnavailable:
        return None


@router.get("/{assessment_id}", response_model=schemas.AssessmentDetail)
def read_assessment(
    assessment_id: uuid.UUID, db: DbSession, user: ViewerUser
) -> schemas.AssessmentDetail:
    assessment = get_assessment(db, assessment_id)
    require_view(user, assessment.patient_id)
    return serializers.assessment_detail(db, assessment, _coverage(db))


@router.delete("/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assessment(
    assessment_id: uuid.UUID, request: Request, db: DbSession, user: ClinicalUser
) -> None:
    assessment = require_owner(get_assessment(db, assessment_id), user)
    if user.role is Role.NURSE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="A nurse cannot delete an assessment"
        )
    patient_code = assessment.patient.code
    # Documents and camera observations belong to the patient and are kept; they are
    # simply no longer filed under this assessment. Everything else cascades.
    db.delete(assessment)
    db.commit()
    audit.record(
        db,
        event_type=audit.ASSESSMENT_DELETED,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(assessment_id),
        client_ip=client_ip(request),
        meta={"patient": patient_code},
        ledger_payload={"assessment_id": str(assessment_id), "patient_code": patient_code},
    )


@router.patch("/{assessment_id}", response_model=schemas.AssessmentDetail)
def update_assessment(
    assessment_id: uuid.UUID,
    payload: schemas.AssessmentUpdate,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.AssessmentDetail:
    assessment = require_open(require_owner(get_assessment(db, assessment_id), user))

    changes = payload.model_dump(exclude_unset=True)
    _apply_collections(
        db,
        assessment,
        {
            **changes,
            "locations": payload.locations,
            "anatomical_sites": payload.anatomical_sites,
        },
    )
    if payload.measurement is not None:
        _set_measurement(db, assessment, payload.measurement)
    if payload.self_report is not None:
        _set_self_report(db, assessment, payload.self_report)

    for field, value in changes.items():
        if field not in COLLECTION_FIELDS:
            setattr(assessment, field, value)
    if "duration_value" in changes or "duration_unit" in changes:
        _set_duration(assessment)
    db.commit()
    db.refresh(assessment)

    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"fields": sorted(changes)},
        ledger_payload=_ledger_payload(assessment),
    )
    return serializers.assessment_detail(db, assessment, _coverage(db))


@router.post("/{assessment_id}/predict", response_model=schemas.AssessmentDetail)
def run_estimate(
    assessment_id: uuid.UUID, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.AssessmentDetail:
    assessment = require_open(require_owner(get_assessment(db, assessment_id), user))
    ctx = inputs.context_for(assessment)
    result = estimator.estimate(db, ctx, estimator.earlier_assessments(assessment))
    estimator.store(db, assessment, result)

    if not result.refused and assessment.status is AssessmentStatus.DRAFT:
        assessment.status = AssessmentStatus.ESTIMATED
        db.commit()

    db.refresh(assessment)
    audit.record(
        db,
        event_type=audit.PREDICTION_GENERATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="prediction",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={
            "refused": result.refused,
            "estimated_pain": result.interval.point if result.interval else None,
            "priority_score": result.priority.score,
            "model_version": result.model_version,
            "data_quality": result.quality.level.value,
            "inference_ms": result.inference_ms,
        },
        ledger_payload={
            "assessment_id": str(assessment.id),
            "model_name": result.model_name,
            "model_version": result.model_version,
            "dataset_version": result.dataset_version,
            "feature_schema_version": result.feature_schema_version,
            "estimated_pain": result.interval.point if result.interval else None,
            "interval": (
                [result.interval.low, result.interval.high] if result.interval else None
            ),
            "priority_score": result.priority.score,
            "refused": result.refused,
            "features": result.feature_values,
        },
    )
    return serializers.assessment_detail(db, assessment, _coverage(db))


@router.post("/{assessment_id}/validate", response_model=schemas.AssessmentDetail)
def validate_assessment(
    assessment_id: uuid.UUID,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
    payload: schemas.ReviewIn | None = None,
) -> schemas.AssessmentDetail:
    require_doctor(user)
    assessment = require_open(require_owner(get_assessment(db, assessment_id), user))
    if assessment.prediction is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Run the estimate before validating the assessment",
        )
    review = payload or schemas.ReviewIn()
    assessment.review_agreement = review.agreement
    assessment.review_comment = review.comment
    assessment.status = AssessmentStatus.VALIDATED
    assessment.validated_at = datetime.now(timezone.utc)
    assessment.validated_by = user.id
    db.commit()
    db.refresh(assessment)

    audit.record(
        db,
        event_type=audit.ASSESSMENT_VALIDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"agreement": review.agreement.value},
        ledger_payload=_ledger_payload(assessment),
    )
    return serializers.assessment_detail(db, assessment, _coverage(db))


@router.post(
    "/{assessment_id}/notes",
    response_model=schemas.NoteOut,
    status_code=status.HTTP_201_CREATED,
)
def add_note(
    assessment_id: uuid.UUID,
    payload: schemas.NoteIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.NoteOut:
    assessment = get_assessment(db, assessment_id)
    note = ClinicalNote(assessment_id=assessment.id, author_id=user.id, body=payload.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"note_added": True},
        ledger_payload=_ledger_payload(assessment),
    )
    return schemas.NoteOut.model_validate(note)


def _comparison_value(assessment: PainAssessment, field: str) -> float | None:
    prediction = assessment.prediction
    measurement = assessment.measurement
    if field == "estimated_pain":
        return prediction.estimated_pain if prediction else None
    if field == "priority_score":
        return prediction.priority_score if prediction else None
    if field == "self_report":
        return assessment.self_report.nrs if assessment.self_report else None
    return getattr(measurement, field, None) if measurement else None


def _site_labels(assessment: PainAssessment) -> dict[tuple[str, str], str]:
    out = {}
    for row in assessment.anatomical_sites:
        structure = anatomy.BY_CODE.get(row.structure_code)
        label = structure.label if structure else row.structure_code
        if row.side not in ("MIDLINE", "NOT_APPLICABLE"):
            label = f"{label} ({row.side.lower()})"
        out[(row.structure_code, row.side)] = label
    for row in assessment.locations:
        if any(code == row.location_code for code, _ in _projected_pairs(assessment)):
            continue
        entry = anatomy.locations.BY_CODE.get(row.location_code)
        out[("LOC:" + row.location_code, row.side)] = (
            entry.label if entry else row.location_code
        )
    return out


def _projected_pairs(assessment: PainAssessment) -> list[tuple[str, str]]:
    pairs = []
    for row in assessment.anatomical_sites:
        pairs.extend(anatomy.projected_locations(row.structure_code, row.side))
    return pairs


@router.get("/{assessment_id}/compare/{other_id}", response_model=schemas.ComparisonOut)
def compare(
    assessment_id: uuid.UUID, other_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.ComparisonOut:
    current = get_assessment(db, assessment_id)
    previous = get_assessment(db, other_id)
    if current.patient_id != previous.patient_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assessments belong to different patients",
        )
    if previous.created_at > current.created_at:
        previous, current = current, previous

    fields = []
    for field, label in COMPARISON_FIELDS:
        before = _comparison_value(previous, field)
        after = _comparison_value(current, field)
        change = round(after - before, 1) if before is not None and after is not None else None
        fields.append(
            schemas.ComparisonField(
                field=field, label=label, previous=before, current=after, change=change
            )
        )

    before_symptoms = {row.symptom_code for row in previous.symptoms}
    after_symptoms = {row.symptom_code for row in current.symptoms}

    def labels(codes: set[str]) -> list[str]:
        return sorted(
            symptoms_kb.BY_CODE[code].label if code in symptoms_kb.BY_CODE else code
            for code in codes
        )

    before_sites = _site_labels(previous)
    after_sites = _site_labels(current)
    added = sorted(after_sites[key] for key in after_sites.keys() - before_sites.keys())
    resolved = sorted(before_sites[key] for key in before_sites.keys() - after_sites.keys())
    unchanged = sorted(after_sites[key] for key in after_sites.keys() & before_sites.keys())

    return schemas.ComparisonOut(
        previous_id=previous.id,
        current_id=current.id,
        previous_at=previous.created_at,
        current_at=current.created_at,
        fields=fields,
        symptoms_added=labels(after_symptoms - before_symptoms),
        symptoms_resolved=labels(before_symptoms - after_symptoms),
        sites_added=added,
        sites_resolved=resolved,
        sites_unchanged=unchanged,
        distribution_changed=bool(added or resolved),
    )
