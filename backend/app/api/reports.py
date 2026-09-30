"""PDF report generation."""

import uuid

from fastapi import APIRouter, Request, Response

from app.api.assessments import get_assessment
from app.database.models import User
from app.dependencies import CurrentUser, DbSession, client_ip
from app.reports.pdf_generator import build_report
from app.security import audit

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("/{assessment_id}/generate")
def generate_report(
    assessment_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> Response:
    assessment = get_assessment(db, assessment_id)
    # The report names the clinician who recorded the assessment, which is not always the
    # one printing it.
    assessor = db.get(User, assessment.doctor_id) or user
    pdf = build_report(db, assessment, assessor)

    audit.record(
        db,
        event_type=audit.REPORT_GENERATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="report",
        resource_id=str(assessment.id),
        client_ip=client_ip(request),
        meta={"bytes": len(pdf)},
        ledger_payload={
            "assessment_id": str(assessment.id),
            "patient_code": assessment.patient.code,
            "generated_by": str(user.id),
            "size_bytes": len(pdf),
        },
    )
    filename = f"pain-assessment-{assessment.patient.code}-{assessment.created_at:%Y%m%d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
