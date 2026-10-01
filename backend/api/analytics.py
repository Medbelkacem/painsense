from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from backend.api import schemas, serializers
from database.models import (
    AssessmentStatus,
    PainAssessment,
    PainPrediction,
    Patient,
    PredictionAlert,
    SelfReport,
)
from backend.dependencies import CurrentUser, DbSession
from knowledge import locations

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

HIGH_PAIN_THRESHOLD = 7.0
TREND_DAYS = 30
RECENT_LIMIT = 8


@router.get("", response_model=schemas.AnalyticsOut)
def analytics(db: DbSession, user: CurrentUser) -> schemas.AnalyticsOut:
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    patients_total = db.scalar(select(func.count()).select_from(Patient)) or 0
    patients_synthetic = (
        db.scalar(
            select(func.count()).select_from(Patient).where(Patient.is_synthetic.is_(True))
        )
        or 0
    )
    assessments = list(db.scalars(select(PainAssessment).order_by(PainAssessment.created_at)))
    predictions = list(db.scalars(select(PainPrediction)))
    reports = {row.assessment_id: row.nrs for row in db.scalars(select(SelfReport))}

    estimates = [row.estimated_pain for row in predictions if row.estimated_pain is not None]
    paired = [
        (row.estimated_pain, reports[row.assessment_id])
        for row in predictions
        if row.estimated_pain is not None and row.assessment_id in reports
    ]

    daily = defaultdict(list)
    cutoff = now - timedelta(days=TREND_DAYS)
    for assessment in assessments:
        prediction = assessment.prediction
        if prediction is None or prediction.estimated_pain is None:
            continue
        if assessment.created_at < cutoff:
            continue
        daily[assessment.created_at.date().isoformat()].append(prediction.estimated_pain)

    regions = Counter()
    for assessment in assessments:
        for row in assessment.locations:
            entry = locations.BY_CODE.get(row.location_code)
            if entry:
                regions[entry.region] += 1

    recent = sorted(assessments, key=lambda row: row.created_at, reverse=True)[:RECENT_LIMIT]

    return schemas.AnalyticsOut(
        patients_total=patients_total,
        patients_synthetic=patients_synthetic,
        assessments_total=len(assessments),
        assessments_today=sum(1 for row in assessments if row.created_at >= start_of_day),
        assessments_awaiting_validation=sum(
            1 for row in assessments if row.status is AssessmentStatus.ESTIMATED
        ),
        high_pain_count=sum(1 for value in estimates if value >= HIGH_PAIN_THRESHOLD),
        alerts_open=db.scalar(select(func.count()).select_from(PredictionAlert)) or 0,
        mean_estimated_pain=(round(sum(estimates) / len(estimates), 2) if estimates else None),
        mean_self_report=(round(sum(reports.values()) / len(reports), 2) if reports else None),
        estimate_vs_self_report_mae=(
            round(sum(abs(a - b) for a, b in paired) / len(paired), 2) if paired else None
        ),
        band_distribution=dict(
            Counter(row.band for row in predictions if row.band).most_common()
        ),
        region_distribution=dict(regions.most_common()),
        daily_mean_pain=[
            {
                "date": day,
                "mean_pain": round(sum(values) / len(values), 2),
                "count": len(values),
            }
            for day, values in sorted(daily.items())
        ],
        recent_assessments=[serializers.assessment_summary(row) for row in recent],
    )
