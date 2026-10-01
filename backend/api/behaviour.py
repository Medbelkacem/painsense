"""The behavioural observation API.

Four calls. `/reference` says what will be measured and what the platform can and cannot
report, before a camera is opened. A post of a clip measures it. A get reads one back. A
delete removes a retained clip while keeping the measures.

`/reference` existing at all is a deliberate choice carried over from the signals API: a
page should not offer the patient a recording and then discover afterwards that no model
was available or that the format was refused. Everything the interface needs to set
expectations is answerable before anybody is asked to sit in front of a lens.

The clip is read into memory rather than streamed to disk in chunks. At the size limit this
module enforces that is a few tens of megabytes for the moment it takes to measure, and
holding it means the digest, the measurement and the retention decision all see the same
bytes.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.api import schemas
from backend.behaviour import inference, schema, service
from backend.behaviour import video as video_module
from backend.dependencies import ClinicalUser, CurrentUser, DbSession
from database.models import (
    BehaviourObservation,
    PainAssessment,
    Patient,
    PatientConsent,
)
from security import audit

router = APIRouter(prefix="/api/behaviour", tags=["camera and microphone"])


def _patient(db: DbSession, patient_id: uuid.UUID) -> Patient:
    row = db.scalar(
        select(Patient)
        .where(Patient.id == patient_id)
        .options(selectinload(Patient.baseline))
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return row


def _observation(db: DbSession, observation_id: uuid.UUID) -> BehaviourObservation:
    row = db.get(BehaviourObservation, observation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Observation not found")
    return row


def _detail(row: BehaviourObservation) -> schemas.BehaviourObservationOut:
    out = schemas.BehaviourObservationOut.model_validate(row)
    out.modalities = [
        schemas.BehaviourModalityOut(**entry)
        for entry in (row.quality or {}).get("modalities", [])
    ]
    out.voice_estimate = schemas.BehaviourVoiceEstimateOut(
        available=row.estimate_available,
        message=(
            "Experimental level from a research model trained on elicited pain in healthy "
            "volunteers. Not a clinical measurement."
            if row.estimate_available
            else (row.unavailable_reason or inference.UNAVAILABLE_MESSAGE)
        ),
        model_version=row.model_version,
        level=row.voice_pain_level,
        label=row.voice_pain_label,
        level_error=row.voice_confidence,
        scale=list(inference.LEVELS),
        limitations=list(inference.LIMITATIONS),
    )
    return out


@router.get("/reference", response_model=schemas.BehaviourReferenceOut)
def reference(db: DbSession, user: CurrentUser) -> schemas.BehaviourReferenceOut:
    model = inference.find_model(db)
    return schemas.BehaviourReferenceOut(
        measures=[
            schemas.BehaviourMeasureOut(
                code=measure.code,
                label=measure.label,
                modality=measure.modality,
                unit=measure.unit,
                note=measure.note,
                plausible=list(measure.plausible) if measure.plausible else None,
                baseline_relative=measure.baseline_relative,
            )
            for measure in schema.MEASURES
        ],
        modalities=list(schema.MODALITIES),
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
        minimum_seconds=schema.MINIMUM_SECONDS,
        minimum_frame_rate=schema.MINIMUM_FRAME_RATE,
        iris_diameter_mm=schema.IRIS_DIAMETER_MM,
        accepted_media=sorted(service.ACCEPTED_MEDIA),
        max_clip_bytes=service.MAX_CLIP_BYTES,
        consent_scope=service.CONSENT_SCOPE,
        instruction=service.INSTRUCTION,
        notice=service.NOTICE,
        voice_model_available=model is not None,
        voice_model_message=(
            f"Voice model {model.version} is registered and active, trained on "
            f"{model.dataset_version} with {model.mae:.2f} levels of cross-validated error."
            if model
            else inference.UNAVAILABLE_MESSAGE
        ),
        voice_levels=list(inference.LEVELS),
    )


@router.get("/patients/{patient_id}/consent", response_model=schemas.ConsentOut | None)
def read_consent(
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.ConsentOut | None:
    """The camera-and-microphone consent for this patient, or null where none is on record."""
    _patient(db, patient_id)
    row = db.scalar(
        select(PatientConsent).where(
            PatientConsent.patient_id == patient_id,
            PatientConsent.scope == service.CONSENT_SCOPE,
        )
    )
    return schemas.ConsentOut.model_validate(row) if row is not None else None


@router.put("/patients/{patient_id}/consent", response_model=schemas.ConsentOut)
def record_consent(
    patient_id: uuid.UUID,
    payload: schemas.BehaviourConsentIn,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.ConsentOut:
    """Grant or withdraw consent to record this patient's camera and microphone.

    One scope, fixed by this module rather than taken from the request. A page that can
    name the scope it is granting can name the wrong one, and a consent to a recording of
    a patient's face is not a thing to get wrong by a typo.

    Withdrawal keeps the row and stamps the time, so it stays answerable whether a clip
    held at a given moment was held with consent. It does not reach back and delete clips
    already retained — that is a separate, deliberate act on each observation.
    """
    _patient(db, patient_id)
    row = db.scalar(
        select(PatientConsent).where(
            PatientConsent.patient_id == patient_id,
            PatientConsent.scope == service.CONSENT_SCOPE,
        )
    )
    if row is None:
        row = PatientConsent(patient_id=patient_id, scope=service.CONSENT_SCOPE)
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
    db.refresh(row)
    audit.record(
        db,
        event_type=audit.SECURITY_EVENT,
        actor_id=user.id,
        actor_label=user.email,
        resource="patient_consent",
        resource_id=str(row.id),
        meta={
            "patient_id": str(patient_id),
            "scope": service.CONSENT_SCOPE,
            "granted": payload.granted,
        },
    )
    return schemas.ConsentOut.model_validate(row)


@router.post(
    "/patients/{patient_id}/observations",
    response_model=schemas.BehaviourObservationOut,
    status_code=status.HTTP_201_CREATED,
)
async def observe(
    patient_id: uuid.UUID,
    db: DbSession,
    user: ClinicalUser,
    clip: Annotated[UploadFile, File(description="The recorded camera and microphone clip")],
    assessment_id: Annotated[uuid.UUID | None, Form()] = None,
    at_rest: Annotated[bool, Form()] = False,
    retain_media: Annotated[bool, Form()] = False,
) -> schemas.BehaviourObservationOut:
    """Measure one clip of a patient.

    `at_rest` marks a recording taken with the patient settled, which becomes the reference
    their later observations are read against rather than a reading in its own right.
    `retain_media` keeps the clip, encrypted; without it the clip is deleted as soon as the
    measures are out of it.
    """
    patient = _patient(db, patient_id)
    if assessment_id is not None:
        assessment = db.scalar(
            select(PainAssessment).where(
                PainAssessment.id == assessment_id,
                PainAssessment.patient_id == patient_id,
            )
        )
        if assessment is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="That assessment does not belong to this patient",
            )

    data = await clip.read()
    try:
        observation = service.analyse(
            db,
            patient,
            data=data,
            media_type=clip.content_type,
            at_rest=at_rest,
            assessment_id=assessment_id,
            retain_media=retain_media,
            actor_id=user.id,
        )
    except service.ConsentMissing as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except service.ClipRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except video_module.VideoUnreadable as exc:
        # Only reaches here when the clip held no decodable track at all; a video failure
        # alongside usable audio is a note on the observation, not an error.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _detail(observation)


@router.get(
    "/patients/{patient_id}/observations",
    response_model=list[schemas.BehaviourObservationSummary],
)
def history(
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[schemas.BehaviourObservationSummary]:
    _patient(db, patient_id)
    rows = db.scalars(
        select(BehaviourObservation)
        .where(BehaviourObservation.patient_id == patient_id)
        .order_by(BehaviourObservation.recorded_at.desc())
    ).all()
    return [schemas.BehaviourObservationSummary.model_validate(row) for row in rows]


@router.get(
    "/patients/{patient_id}/resting", response_model=schemas.RestingBehaviourOut
)
def resting(
    patient_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.RestingBehaviourOut:
    """This patient's resting behaviour, which their later observations are read against."""
    patient = _patient(db, patient_id)
    baseline = patient.baseline
    if baseline is None:
        return schemas.RestingBehaviourOut()
    return schemas.RestingBehaviourOut(
        recorded_at=baseline.behaviour_recorded_at, measures=baseline.behaviour
    )


@router.get("/observations/{observation_id}", response_model=schemas.BehaviourObservationOut)
def read(
    observation_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> schemas.BehaviourObservationOut:
    return _detail(_observation(db, observation_id))


@router.delete(
    "/observations/{observation_id}/media",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def discard(observation_id: uuid.UUID, db: DbSession, user: ClinicalUser) -> Response:
    """Delete a retained clip, keeping the measures taken from it.

    What withdrawing consent means for an observation already made: the recording goes,
    the numbers and the record that it happened stay. Deleting a clip that is already gone
    is not an error, so that withdrawing twice behaves the same as withdrawing once.
    """
    service.discard_media(db, _observation(db, observation_id), actor_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
