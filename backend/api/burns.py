"""The burn assessment API.

Three things shape the route layout.

*Reference data is served, not hard-coded in the client.* `/reference` returns the depth
categories, the body regions with their share of the surface in every age band, the
causes and the methods. An interface built against it picks up a corrected chart without
being rebuilt, and a chart correction is a thing that happens.

*Writes are clinical and go through the audit trail.* Recording an incident, confirming a
depth and approving a report are all audited, because each is a clinical act attributable
to a person.

*A model never writes a finding.* The only route that moves a suggested depth into the
assessment is `confirm-depth`, which takes a clinician and stamps them on the row.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.api import schemas
from backend.burns import service, tbsa
from database.models import (
    Attribution,
    BurnAlert,
    BurnAssessment,
    BurnIncident,
    BurnPainReport,
    BurnRegion,
    FollowUpVisit,
    Patient,
    PatientConsent,
    ReviewState,
    WoundCareEvent,
    WoundImage,
)
from backend.dependencies import AdminUser, ClinicalUser, CurrentUser, DbSession, client_ip
from knowledge import burns as reference
from security import audit

router = APIRouter(prefix="/api/burns", tags=["burns"])

NOTICE = (
    "Patient-reported, model-suggested and clinician-confirmed findings are stored and "
    "shown separately. A suggested burn depth is never counted as the assessment until a "
    "clinician confirms it. Surface area totals are estimates from a chart and the "
    "clinician's own figure, where recorded, is kept alongside rather than replacing them."
)


def _incident(db, incident_id: uuid.UUID) -> BurnIncident:
    row = db.get(BurnIncident, incident_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Burn incident not found")
    return row


def _assessment(db, assessment_id: uuid.UUID) -> BurnAssessment:
    row = db.scalar(
        select(BurnAssessment)
        .where(BurnAssessment.id == assessment_id)
        .options(
            selectinload(BurnAssessment.regions),
            selectinload(BurnAssessment.alerts),
            selectinload(BurnAssessment.incident),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return row


def _patient(db, patient_id: uuid.UUID) -> Patient:
    row = db.get(Patient, patient_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return row


def _detail(db, assessment: BurnAssessment) -> schemas.BurnAssessmentDetail:
    out = schemas.BurnAssessmentDetail.model_validate(assessment)
    out.regions = [schemas.BurnRegionOut.model_validate(row) for row in assessment.regions]
    out.alerts = [schemas.BurnAlertOut.model_validate(row) for row in assessment.alerts]
    out.calculations = [
        schemas.TbsaOut.model_validate(row) for row in assessment.calculations
    ]
    latest = service.latest_calculation(db, assessment)
    out.latest_tbsa = schemas.TbsaOut.model_validate(latest) if latest else None
    return out


def _editable(assessment: BurnAssessment) -> BurnAssessment:
    try:
        return service.require_editable(assessment)
    except service.NotEditable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- reference data -----------------------------------------------------------------


@router.get("/reference", response_model=schemas.BurnReferenceOut)
def burn_reference(user: CurrentUser) -> schemas.BurnReferenceOut:
    bands = [name for _low, _high, name in reference.AGE_BANDS]
    return schemas.BurnReferenceOut(
        depths=[
            schemas.BurnDepthOut(
                code=entry.code,
                label=entry.label,
                legacy_label=entry.legacy_label,
                counts_towards_tbsa=entry.counts_towards_tbsa,
                appearance=entry.appearance,
                sensation=entry.sensation,
                note=entry.note,
            )
            for entry in reference.DEPTHS
        ],
        regions=[
            schemas.BurnRegionRefOut(
                code=entry.code,
                label=entry.label,
                side=entry.side,
                high_risk=entry.high_risk,
                nines_group=entry.nines_group,
                nines_group_label=reference.NINES_LABELS[entry.nines_group],
                share_by_band={band: entry.share(band) for band in bands},
                note=entry.note,
            )
            for entry in reference.REGIONS
        ],
        causes=[{"code": code, "label": label} for code, label in reference.CAUSES],
        methods=[
            {"code": code, "formula": tbsa.FORMULAE[code]} for code in tbsa.METHODS
        ],
        age_bands=[
            {"name": name, "from_years": low, "to_years": None if high == float("inf") else high}
            for low, high, name in reference.AGE_BANDS
        ],
        palm_percent=reference.PALM_PERCENT,
        notice=NOTICE,
    )


# --- consent ---------------------------------------------------------------------------


@router.get("/patients/{patient_id}/consents", response_model=list[schemas.ConsentOut])
def list_consents(
    patient_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> list[schemas.ConsentOut]:
    _patient(db, patient_id)
    rows = db.scalars(
        select(PatientConsent).where(PatientConsent.patient_id == patient_id)
    )
    return [schemas.ConsentOut.model_validate(row) for row in rows]


@router.put("/patients/{patient_id}/consents", response_model=schemas.ConsentOut)
def record_consent(
    patient_id: uuid.UUID,
    payload: schemas.ConsentIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.ConsentOut:
    """Grant or withdraw a consent.

    Withdrawal keeps the row and stamps `withdrawn_at`, so it stays possible to say
    whether an image held at a given moment was held with consent.
    """
    _patient(db, patient_id)
    row = db.scalar(
        select(PatientConsent).where(
            PatientConsent.patient_id == patient_id, PatientConsent.scope == payload.scope
        )
    )
    if row is None:
        row = PatientConsent(patient_id=patient_id, scope=payload.scope)
        db.add(row)
    row.granted = payload.granted
    row.note = payload.note
    row.recorded_by = user.id
    if payload.granted:
        row.granted_at = service.now()
        row.withdrawn_at = None
    else:
        row.withdrawn_at = service.now()
    db.commit()
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient_consent",
        resource_id=str(patient_id),
        client_ip=client_ip(request),
        meta={"scope": payload.scope, "granted": payload.granted},
    )
    return schemas.ConsentOut.model_validate(row)


# --- incidents ----------------------------------------------------------------------------


@router.post("/incidents", response_model=schemas.BurnIncidentOut, status_code=201)
def create_incident(
    payload: schemas.BurnIncidentIn, request: Request, db: DbSession, user: ClinicalUser
) -> schemas.BurnIncidentOut:
    _patient(db, payload.patient_id)
    row = BurnIncident(**payload.model_dump(), recorded_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(
        db,
        event_type=audit.ASSESSMENT_CREATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="burn_incident",
        resource_id=str(row.id),
        client_ip=client_ip(request),
        meta={"cause": row.cause},
    )
    return schemas.BurnIncidentOut.model_validate(row)


@router.get("/incidents", response_model=list[schemas.BurnIncidentOut])
def list_incidents(
    db: DbSession,
    user: ClinicalUser,
    patient_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[schemas.BurnIncidentOut]:
    filters = [BurnIncident.patient_id == patient_id] if patient_id else []
    rows = db.scalars(
        select(BurnIncident)
        .where(*filters)
        .order_by(BurnIncident.occurred_at.desc())
        .limit(limit)
    )
    return [schemas.BurnIncidentOut.model_validate(row) for row in rows]


@router.get("/incidents/{incident_id}", response_model=schemas.BurnTimelineOut)
def incident_timeline(
    incident_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BurnTimelineOut:
    incident = _incident(db, incident_id)
    assessments = db.scalars(
        select(BurnAssessment)
        .where(BurnAssessment.incident_id == incident_id)
        .order_by(BurnAssessment.assessed_at)
        .options(
            selectinload(BurnAssessment.regions),
            selectinload(BurnAssessment.alerts),
            selectinload(BurnAssessment.calculations),
        )
    ).all()
    images = db.scalars(
        select(WoundImage)
        .where(WoundImage.incident_id == incident_id)
        .order_by(WoundImage.captured_at)
    ).all()
    return schemas.BurnTimelineOut(
        incident=schemas.BurnIncidentOut.model_validate(incident),
        assessments=[_detail(db, row) for row in assessments],
        pain_reports=[
            schemas.BurnPainOut.model_validate(row)
            for row in db.scalars(
                select(BurnPainReport)
                .where(BurnPainReport.incident_id == incident_id)
                .order_by(BurnPainReport.reported_at)
            )
        ],
        care_events=[
            schemas.WoundCareOut.model_validate(row)
            for row in db.scalars(
                select(WoundCareEvent)
                .where(WoundCareEvent.incident_id == incident_id)
                .order_by(WoundCareEvent.performed_at)
            )
        ],
        follow_ups=[
            schemas.FollowUpOut.model_validate(row)
            for row in db.scalars(
                select(FollowUpVisit)
                .where(FollowUpVisit.incident_id == incident_id)
                .order_by(FollowUpVisit.scheduled_for)
            )
        ],
        images=[
            {
                "id": str(row.id),
                "region_code": row.region_code,
                "captured_at": row.captured_at.isoformat(),
                "assessment_id": str(row.assessment_id) if row.assessment_id else None,
                "quality": row.quality,
            }
            for row in images
        ],
        notice=NOTICE,
    )


# --- assessments -----------------------------------------------------------------------------


@router.post(
    "/incidents/{incident_id}/assessments",
    response_model=schemas.BurnAssessmentDetail,
    status_code=201,
)
def open_assessment(
    incident_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BurnAssessmentDetail:
    incident = _incident(db, incident_id)
    patient = _patient(db, incident.patient_id)
    assessment = service.open_assessment(db, incident, patient=patient, actor_id=user.id)
    db.commit()
    db.refresh(assessment)
    return _detail(db, assessment)


@router.get("/assessments/{assessment_id}", response_model=schemas.BurnAssessmentDetail)
def read_assessment(
    assessment_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BurnAssessmentDetail:
    return _detail(db, _assessment(db, assessment_id))


@router.put(
    "/assessments/{assessment_id}/regions", response_model=schemas.BurnAssessmentDetail
)
def set_region(
    assessment_id: uuid.UUID,
    payload: schemas.BurnRegionIn,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.BurnAssessmentDetail:
    """Add or update one burned region, then re-cost and re-derive the flags."""
    assessment = _editable(_assessment(db, assessment_id))
    try:
        service.set_region(
            db,
            assessment,
            region_code=payload.region_code,
            fraction=payload.fraction,
            depth=payload.depth,
            attribution=Attribution.CLINICIAN,
            circumferential=payload.circumferential,
            marks=payload.marks,
            note=payload.note,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.refresh(assessment)
    service.recalculate(db, assessment, actor_id=user.id)
    db.commit()
    db.refresh(assessment)
    return _detail(db, assessment)


@router.delete(
    "/assessments/{assessment_id}/regions/{region_code}",
    response_model=schemas.BurnAssessmentDetail,
)
def remove_region(
    assessment_id: uuid.UUID, region_code: str, db: DbSession, user: ClinicalUser
) -> schemas.BurnAssessmentDetail:
    assessment = _editable(_assessment(db, assessment_id))
    row = db.scalar(
        select(BurnRegion).where(
            BurnRegion.assessment_id == assessment.id, BurnRegion.region_code == region_code
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Region not on this assessment")
    db.delete(row)
    db.flush()
    db.refresh(assessment)
    service.recalculate(db, assessment, actor_id=user.id)
    db.commit()
    db.refresh(assessment)
    return _detail(db, assessment)


@router.post(
    "/assessments/{assessment_id}/regions/{region_code}/confirm-depth",
    response_model=schemas.BurnAssessmentDetail,
)
def confirm_depth(
    assessment_id: uuid.UUID,
    region_code: str,
    payload: schemas.DepthConfirmIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.BurnAssessmentDetail:
    """A clinician decides a region's depth. The only route that can do so."""
    assessment = _editable(_assessment(db, assessment_id))
    row = db.scalar(
        select(BurnRegion).where(
            BurnRegion.assessment_id == assessment.id, BurnRegion.region_code == region_code
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Region not on this assessment")
    suggested = row.suggested_depth
    service.confirm_depth(db, row, depth=payload.depth, actor_id=user.id)
    db.refresh(assessment)
    service.recalculate(db, assessment, actor_id=user.id)
    db.commit()
    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="burn_region",
        resource_id=str(row.id),
        client_ip=client_ip(request),
        meta={
            "region": region_code,
            "confirmed_depth": payload.depth.value,
            "model_suggested": suggested.value if suggested else None,
            "agreed_with_model": bool(suggested and suggested is payload.depth),
        },
    )
    db.refresh(assessment)
    return _detail(db, assessment)


@router.post("/assessments/{assessment_id}/tbsa", response_model=schemas.TbsaOut)
def calculate_tbsa(
    assessment_id: uuid.UUID,
    payload: schemas.TbsaRequest,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.TbsaOut:
    assessment = _assessment(db, assessment_id)
    try:
        row = service.calculate(
            db, assessment, method=payload.method, palms=payload.palms, actor_id=user.id
        )
    except tbsa.WrongChart as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    service.refresh_alerts(db, assessment)
    db.commit()
    return schemas.TbsaOut.model_validate(row)


@router.get("/assessments/{assessment_id}/tbsa/compare", response_model=dict)
def compare_methods(
    assessment_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> dict:
    """Both charts side by side, with the reason where one does not apply."""
    assessment = _assessment(db, assessment_id)
    return tbsa.compare(service.involvements(assessment), age_years=assessment.age_years)


@router.post("/tbsa/{calculation_id}/override", response_model=schemas.TbsaOut)
def override_tbsa(
    calculation_id: uuid.UUID,
    payload: schemas.TbsaOverrideIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.TbsaOut:
    from database.models import TbsaCalculation

    row = db.get(TbsaCalculation, calculation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Calculation not found")
    service.override_total(db, row, percent=payload.percent, note=payload.note, actor_id=user.id)
    db.commit()
    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="tbsa_calculation",
        resource_id=str(row.id),
        client_ip=client_ip(request),
        meta={"computed": row.total_percent, "clinician": payload.percent},
    )
    return schemas.TbsaOut.model_validate(row)


@router.post("/assessments/{assessment_id}/submit", response_model=schemas.BurnAssessmentDetail)
def submit(
    assessment_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BurnAssessmentDetail:
    assessment = _editable(_assessment(db, assessment_id))
    try:
        service.submit_for_review(db, assessment)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    db.refresh(assessment)
    return _detail(db, assessment)


@router.post("/assessments/{assessment_id}/confirm", response_model=schemas.BurnAssessmentDetail)
def confirm_assessment(
    assessment_id: uuid.UUID,
    payload: schemas.BurnReviewIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.BurnAssessmentDetail:
    assessment = _assessment(db, assessment_id)
    if assessment.state is ReviewState.CONFIRMED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already confirmed")
    try:
        service.confirm(db, assessment, actor_id=user.id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.commit()
    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="burn_assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"action": "confirmed"},
    )
    db.refresh(assessment)
    return _detail(db, assessment)


@router.post("/assessments/{assessment_id}/amend", response_model=schemas.BurnAssessmentDetail)
def amend_assessment(
    assessment_id: uuid.UUID,
    payload: schemas.BurnAmendIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.BurnAssessmentDetail:
    assessment = _assessment(db, assessment_id)
    service.amend(db, assessment, actor_id=user.id, note=payload.note)
    db.commit()
    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="burn_assessment",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"action": "amended", "note": payload.note[:200]},
    )
    db.refresh(assessment)
    return _detail(db, assessment)


@router.post("/alerts/{alert_id}/acknowledge", response_model=schemas.BurnAlertOut)
def acknowledge(
    alert_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.BurnAlertOut:
    row = db.get(BurnAlert, alert_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alert not found")
    row.acknowledged_by = user.id
    row.acknowledged_at = service.now()
    db.commit()
    return schemas.BurnAlertOut.model_validate(row)


# --- pain, wound care and follow-up ------------------------------------------------------------


@router.post("/pain", response_model=schemas.BurnPainOut, status_code=201)
def record_pain(
    payload: schemas.BurnPainIn,
    patient_id: Annotated[uuid.UUID, Query()],
    db: DbSession,
    user: ClinicalUser,
) -> schemas.BurnPainOut:
    _patient(db, patient_id)
    if payload.incident_id is not None:
        _incident(db, payload.incident_id)
    row = BurnPainReport(
        patient_id=patient_id,
        attribution=Attribution.CLINICIAN if payload.observed else Attribution.PATIENT,
        recorded_by=user.id,
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.BurnPainOut.model_validate(row)


@router.get("/pain", response_model=list[schemas.BurnPainOut])
def list_pain(
    db: DbSession,
    user: ClinicalUser,
    patient_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[schemas.BurnPainOut]:
    filters = []
    if patient_id:
        filters.append(BurnPainReport.patient_id == patient_id)
    if incident_id:
        filters.append(BurnPainReport.incident_id == incident_id)
    rows = db.scalars(
        select(BurnPainReport)
        .where(*filters)
        .order_by(BurnPainReport.reported_at.desc())
        .limit(limit)
    )
    return [schemas.BurnPainOut.model_validate(row) for row in rows]


@router.post("/wound-care", response_model=schemas.WoundCareOut, status_code=201)
def record_wound_care(
    payload: schemas.WoundCareIn, db: DbSession, user: ClinicalUser
) -> schemas.WoundCareOut:
    incident = _incident(db, payload.incident_id)
    data = payload.model_dump()
    data["performed_at"] = data.get("performed_at") or service.now()
    row = WoundCareEvent(patient_id=incident.patient_id, performed_by=user.id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.WoundCareOut.model_validate(row)


@router.get("/wound-care", response_model=list[schemas.WoundCareOut])
def list_wound_care(
    db: DbSession,
    user: ClinicalUser,
    incident_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[schemas.WoundCareOut]:
    filters = [WoundCareEvent.incident_id == incident_id] if incident_id else []
    rows = db.scalars(
        select(WoundCareEvent)
        .where(*filters)
        .order_by(WoundCareEvent.performed_at.desc())
        .limit(limit)
    )
    return [schemas.WoundCareOut.model_validate(row) for row in rows]


@router.post("/follow-ups", response_model=schemas.FollowUpOut, status_code=201)
def record_follow_up(
    payload: schemas.FollowUpIn, db: DbSession, user: ClinicalUser
) -> schemas.FollowUpOut:
    incident = _incident(db, payload.incident_id)
    row = FollowUpVisit(
        patient_id=incident.patient_id, recorded_by=user.id, **payload.model_dump()
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.FollowUpOut.model_validate(row)


@router.get("/dashboard", response_model=dict)
def dashboard(db: DbSession, admin: AdminUser) -> dict:
    """Aggregate counts for the clinical overview. No patient-identifying content."""
    from sqlalchemy import func

    awaiting = db.scalar(
        select(func.count())
        .select_from(BurnAssessment)
        .where(BurnAssessment.state == ReviewState.AWAITING_REVIEW)
    )
    unacknowledged = db.scalar(
        select(func.count()).select_from(BurnAlert).where(BurnAlert.acknowledged_at.is_(None))
    )
    return {
        "incidents": db.scalar(select(func.count()).select_from(BurnIncident)) or 0,
        "assessments": db.scalar(select(func.count()).select_from(BurnAssessment)) or 0,
        "awaiting_review": awaiting or 0,
        "unacknowledged_alerts": unacknowledged or 0,
        "care_events": db.scalar(select(func.count()).select_from(WoundCareEvent)) or 0,
        "wound_images": db.scalar(select(func.count()).select_from(WoundImage)) or 0,
        "notice": NOTICE,
    }
