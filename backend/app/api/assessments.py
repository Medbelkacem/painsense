"""Pain assessments: the record, the estimate, and the clinician's validation.

Codes coming in from a client are checked against the reference tables before anything is
stored, so an assessment can never point at a taxonomy entry that does not exist.

The estimate is produced on request rather than on save. A clinician fills the record in
stages, and running the model on every keystroke would present a number built from half a
record as though it were the assessment.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import estimator, inputs, model
from app.api import schemas, serializers
from app.api.patients import get_patient
from app.database.models import (
    AnatomicalStructure,
    AssessmentAnatomicalSite,
    AssessmentAnswer,
    AssessmentConfounder,
    AssessmentFactor,
    AssessmentLocation,
    AssessmentQuality,
    AssessmentStatus,
    AssessmentSymptom,
    ClinicalNote,
    ClinicalQuestion,
    Confounder,
    PainAssessment,
    PainFactor,
    PainLocation,
    PainQuality,
    PhysiologicalMeasurement,
    Role,
    SelfReport,
    Symptom,
    User,
)
from app.dependencies import CurrentUser, DbSession, client_ip
from app.knowledge import anatomy
from app.knowledge import symptoms as symptoms_kb
from app.security import audit

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
    if user.role is not Role.ADMIN and assessment.doctor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the clinician who recorded this assessment can change it",
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
    if assessment.self_report is None:
        assessment.self_report = SelfReport(
            assessment_id=assessment.id,
            patient_id=assessment.patient_id,
            nrs=payload.nrs,
            reported_at=reported_at,
            note=payload.note,
        )
        return
    assessment.self_report.nrs = payload.nrs
    assessment.self_report.reported_at = reported_at
    assessment.self_report.note = payload.note


def _recorded_locations(sites) -> dict[str, tuple[str, bool]]:
    """The pain locations a set of anatomical sites records, with the side of each.

    Two sites can land on the same location: a left and a right knee joint both record
    KNEE, and the side they leave behind is the combination of theirs.
    """
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
    assessment.anatomical_sites.clear()
    db.flush()
    seen = set()
    for entry in entries:
        key = (entry.structure_code, entry.side)
        if key in seen:
            continue
        seen.add(key)
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
        assessment.anatomical_sites.append(
            AssessmentAnatomicalSite(
                assessment_id=assessment.id,
                structure_code=entry.structure_code,
                side=entry.side,
                intensity=entry.intensity,
                is_primary=entry.is_primary,
                note=entry.note,
            )
        )


def _apply_sites(
    db: Session,
    assessment: PainAssessment,
    locations_in: list[schemas.LocationIn] | None,
    sites_in: list[schemas.AnatomicalSiteIn] | None,
) -> None:
    """Write the anatomical sites and keep the pain locations in step with them.

    A structure selected on the 3D model also records the pain location it projects onto,
    which is how the question engine, the rule engine, the cause knowledge base and the
    feature vector see it: none of them knows anything about anatomy. Locations ticked by
    hand on the flat diagram are kept alongside, and a location that existed only because
    of a structure goes when that structure does.

    Recovering the hand-picked set from what the previous sites recorded is what makes this
    work on a PATCH that sends one list and not the other.
    """
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


@router.post("", response_model=schemas.AssessmentDetail, status_code=status.HTTP_201_CREATED)
def create_assessment(
    payload: schemas.AssessmentCreate, request: Request, db: DbSession, user: CurrentUser
) -> schemas.AssessmentDetail:
    patient = get_patient(db, payload.patient_id)
    if patient.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This patient record is archived")

    scalar_fields = payload.model_dump(
        exclude={
            "patient_id",
            "locations",
            "anatomical_sites",
            "quality_codes",
            "symptom_codes",
            "factor_codes",
            "confounder_codes",
            "answers",
            "measurement",
            "self_report",
        }
    )
    assessment = PainAssessment(
        patient_id=patient.id,
        doctor_id=user.id,
        is_synthetic=patient.is_synthetic,
        patient_age_years=patient.age_on(datetime.now(timezone.utc).date()),
        **scalar_fields,
    )
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
    """What the ledger hashes for an assessment: its clinical shape, no identifiers."""
    return {
        "assessment_id": str(assessment.id),
        "patient_code": assessment.patient.code,
        "age": assessment.patient_age_years,
        "status": assessment.status.value,
        "locations": sorted(row.location_code for row in assessment.locations),
        "anatomical_sites": [
            {"structure": row.structure_code, "side": row.side, "intensity": row.intensity}
            for row in sorted(
                assessment.anatomical_sites, key=lambda row: (row.structure_code, row.side)
            )
        ],
        "qualities": sorted(row.quality_code for row in assessment.qualities),
        "symptoms": sorted(row.symptom_code for row in assessment.symptoms),
        "factors": sorted(row.factor_code for row in assessment.factors),
        "confounders": sorted(row.confounder_code for row in assessment.confounders),
        "answers": {row.question_code: row.value for row in assessment.answers},
        "onset": assessment.onset.value,
        "pattern": assessment.pattern.value,
        "course": assessment.course.value,
        "duration_hours": assessment.duration_hours,
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
    user: CurrentUser,
    patient_id: uuid.UUID | None = None,
    status_filter: Annotated[AssessmentStatus | None, Query(alias="status")] = None,
    mine_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AssessmentPage:
    filters = []
    if patient_id is not None:
        filters.append(PainAssessment.patient_id == patient_id)
    if status_filter is not None:
        filters.append(PainAssessment.status == status_filter)
    if mine_only:
        filters.append(PainAssessment.doctor_id == user.id)

    rows = list(
        db.scalars(
            select(PainAssessment).where(*filters).order_by(PainAssessment.created_at.desc())
        )
    )
    return schemas.AssessmentPage(
        items=[serializers.assessment_summary(row) for row in rows[offset : offset + limit]],
        total=len(rows),
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
    assessment_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.AssessmentDetail:
    assessment = get_assessment(db, assessment_id)
    return serializers.assessment_detail(db, assessment, _coverage(db))


@router.patch("/{assessment_id}", response_model=schemas.AssessmentDetail)
def update_assessment(
    assessment_id: uuid.UUID,
    payload: schemas.AssessmentUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> schemas.AssessmentDetail:
    assessment = require_owner(get_assessment(db, assessment_id), user)
    if assessment.status is AssessmentStatus.VALIDATED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This assessment has been validated. Record a new assessment instead.",
        )

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

    handled = {
        "locations",
        "anatomical_sites",
        "quality_codes",
        "symptom_codes",
        "factor_codes",
        "confounder_codes",
        "answers",
        "measurement",
        "self_report",
    }
    for field, value in changes.items():
        if field not in handled:
            setattr(assessment, field, value)
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
    assessment_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> schemas.AssessmentDetail:
    assessment = get_assessment(db, assessment_id)
    ctx = inputs.context_for(assessment)
    result = estimator.estimate(db, ctx)
    estimator.store(db, assessment, result)

    if not result.refused and assessment.status is AssessmentStatus.DRAFT:
        assessment.status = AssessmentStatus.ESTIMATED
        db.commit()

    db.refresh(assessment)
    audit.record(
        db,
        event_type=audit.PREDICTION_RUN,
        actor_id=user.id,
        actor_label=user.email,
        resource="prediction",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={
            "refused": result.refused,
            "estimated_pain": result.interval.point if result.interval else None,
            "model_version": result.model_version,
            "data_quality": result.quality.level.value,
        },
        ledger_payload={
            "assessment_id": str(assessment.id),
            "model_version": result.model_version,
            "dataset_version": result.dataset_version,
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
    assessment_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> schemas.AssessmentDetail:
    """Record that a clinician has reviewed the estimate and accepts the record as it stands."""
    assessment = require_owner(get_assessment(db, assessment_id), user)
    if assessment.prediction is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Run the estimate before validating the assessment",
        )
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
    user: CurrentUser,
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


@router.get("/{assessment_id}/compare/{other_id}", response_model=schemas.ComparisonOut)
def compare(
    assessment_id: uuid.UUID, other_id: uuid.UUID, db: DbSession, user: CurrentUser
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

    return schemas.ComparisonOut(
        previous_id=previous.id,
        current_id=current.id,
        previous_at=previous.created_at,
        current_at=current.created_at,
        fields=fields,
        symptoms_added=labels(after_symptoms - before_symptoms),
        symptoms_resolved=labels(before_symptoms - after_symptoms),
    )
