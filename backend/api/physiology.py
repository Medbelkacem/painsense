import uuid

from fastapi import APIRouter, Request

from backend.ai.quality import IMPLAUSIBLE
from backend.api import schemas, serializers
from backend.api.assessments import (
    _ledger_payload,
    _set_measurement,
    get_assessment,
    require_open,
    require_owner,
)
from backend.dependencies import ClinicalUser, CurrentUser, DbSession, client_ip
from knowledge.rules import VITAL_NORMAL_RANGES
from security import audit

router = APIRouter(prefix="/api/physiology", tags=["physiology"])

UNITS = {
    "hr": "beats/min",
    "resp_rate": "breaths/min",
    "sbp": "mmHg",
    "dbp": "mmHg",
    "spo2": "%",
    "temperature_c": "degrees Celsius",
    "glucose_mmol": "mmol/L",
}
LABELS = {
    "hr": "Heart rate",
    "resp_rate": "Respiratory rate",
    "sbp": "Systolic blood pressure",
    "dbp": "Diastolic blood pressure",
    "spo2": "Oxygen saturation",
    "temperature_c": "Temperature",
    "glucose_mmol": "Blood glucose",
}


@router.get("/ranges", response_model=list[dict])
def ranges(user: CurrentUser) -> list[dict]:
    out = []
    for field, (low, high) in IMPLAUSIBLE.items():
        normal = VITAL_NORMAL_RANGES.get(field)
        out.append(
            {
                "field": field,
                "label": LABELS[field],
                "unit": UNITS[field],
                "accepted_min": low,
                "accepted_max": high,
                "reference_min": normal[0] if normal else None,
                "reference_max": normal[1] if normal else None,
            }
        )
    return out


@router.put("/{assessment_id}", response_model=schemas.AssessmentDetail)
def record_measurement(
    assessment_id: uuid.UUID,
    payload: schemas.MeasurementIn,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.AssessmentDetail:
    assessment = require_open(require_owner(get_assessment(db, assessment_id), user))
    _set_measurement(db, assessment, payload)
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
        meta={"measurement_recorded": True},
        ledger_payload=_ledger_payload(assessment),
    )
    return serializers.assessment_detail(db, assessment)
