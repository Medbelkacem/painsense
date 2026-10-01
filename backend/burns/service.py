"""Assembling a burn assessment: regions in, surface area and review flags out.

The module's one job is to keep the three kinds of statement apart — what the patient
said, what a model suggested, what a clinician confirmed — while still producing a single
usable estimate. Three rules do that work:

*A model suggestion never becomes the assessment.* `suggest_depth` writes to
`suggested_depth` and leaves `depth` alone. Only `confirm_depth`, which takes a clinician,
moves a value across, and it stamps who did it.

*Recalculation is explicit and keeps its history.* Changing a region does not silently
rewrite the surface area. A new `TbsaCalculation` row is written each time, so the figure
a decision was taken on is still there afterwards.

*Alerts are derived, never stored stale.* They are recomputed whenever the assessment
changes and reconciled against what is on the row, so a flag cannot outlive the finding
that raised it — but an acknowledged flag keeps its acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.burns import alerts as alert_rules
from backend.burns import tbsa
from database.models import (
    Attribution,
    BurnAlert,
    BurnAssessment,
    BurnDepth,
    BurnIncident,
    BurnRegion,
    Patient,
    ReviewState,
    TbsaCalculation,
    TbsaMethod,
)
from knowledge import burns


class NotEditable(RuntimeError):
    """The assessment has been confirmed and will not take silent changes."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def age_at(patient: Patient, when: datetime | date | None = None) -> float | None:
    """The patient's age in years at a moment, or None where the birth date is absent.

    Taken from the patient's whole months rather than whole years, because the first
    Lund-Browder band ends at the first birthday: an eleven-month-old and a two-year-old
    have very differently proportioned heads, and whole years cannot tell them apart.
    """
    if patient.birth_date is None:
        return None
    moment = when.date() if isinstance(when, datetime) else (when or now().date())
    months = patient.age_months_on(moment)
    return round(months / 12, 2) if months is not None and months >= 0 else None


def require_editable(assessment: BurnAssessment) -> BurnAssessment:
    if assessment.state is ReviewState.CONFIRMED:
        raise NotEditable(
            "this assessment has been confirmed by a clinician. Amend it to record a "
            "change, so the confirmed version stays on file"
        )
    return assessment


def set_region(
    db: Session,
    assessment: BurnAssessment,
    *,
    region_code: str,
    fraction: float = 1.0,
    depth: BurnDepth = BurnDepth.UNCERTAIN,
    attribution: Attribution = Attribution.CLINICIAN,
    circumferential: bool = False,
    marks: list | None = None,
    note: str | None = None,
    actor_id=None,
) -> BurnRegion:
    """Add or update one burned region. Selecting the same region twice updates it."""
    require_editable(assessment)
    if region_code not in burns.REGION_BY_CODE:
        raise ValueError(f"unknown body region {region_code!r}")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("the involved fraction of a region must be between 0 and 1")

    row = db.scalar(
        select(BurnRegion).where(
            BurnRegion.assessment_id == assessment.id,
            BurnRegion.region_code == region_code,
        )
    )
    if row is None:
        row = BurnRegion(assessment_id=assessment.id, region_code=region_code)
        db.add(row)
    row.fraction = fraction
    row.depth = depth
    row.depth_attribution = attribution
    row.circumferential = circumferential
    if marks is not None:
        row.marks = marks
    if note is not None:
        row.note = note
    # Confirmation is about the depth, not about the region having been drawn. A
    # clinician who marks an area but leaves its depth undecided has confirmed nothing,
    # and stamping them here would make an open assessment look reviewed.
    if attribution is Attribution.CLINICIAN and depth is not BurnDepth.UNCERTAIN:
        row.confirmed_by = actor_id
        row.confirmed_at = now()
    else:
        row.confirmed_by = None
        row.confirmed_at = None
    db.flush()
    return row


def suggest_depth(
    db: Session,
    region: BurnRegion,
    *,
    depth: BurnDepth,
    confidence: float | None,
) -> BurnRegion:
    """Record what a model proposed, without changing what the assessment holds."""
    region.suggested_depth = depth
    region.suggested_confidence = confidence
    db.flush()
    return region


def confirm_depth(
    db: Session, region: BurnRegion, *, depth: BurnDepth, actor_id
) -> BurnRegion:
    """A clinician decides the depth. The only path from a suggestion to the assessment."""
    require_editable(region.assessment)
    region.depth = depth
    region.depth_attribution = Attribution.CLINICIAN
    region.confirmed_by = actor_id
    region.confirmed_at = now()
    db.flush()
    return region


def involvements(assessment: BurnAssessment) -> list[tbsa.Involvement]:
    return [
        tbsa.Involvement(
            region_code=row.region_code, depth=row.depth.value, fraction=row.fraction
        )
        for row in assessment.regions
    ]


def calculate(
    db: Session,
    assessment: BurnAssessment,
    *,
    method: TbsaMethod = TbsaMethod.LUND_BROWDER,
    palms: float | None = None,
    actor_id=None,
) -> TbsaCalculation:
    """Compute and store a surface area estimate, keeping every earlier one."""
    age = assessment.age_years
    if method is TbsaMethod.PALM:
        if palms is None:
            raise ValueError("the palm method needs a palm count")
        estimate = tbsa.estimate_by_palms(palms, age_years=age)
    else:
        estimate = tbsa.estimate(involvements(assessment), method=method.value, age_years=age)

    row = TbsaCalculation(
        assessment_id=assessment.id,
        method=method,
        total_percent=estimate.total_percent,
        excluded_superficial_percent=estimate.excluded_percent,
        age_years=age,
        age_band=estimate.age_band,
        palms=estimate.palms,
        provisional=estimate.provisional,
        breakdown=[item.as_dict() for item in estimate.contributions],
        assumptions=estimate.assumptions,
        warnings=estimate.warnings,
        formula=tbsa.FORMULAE[estimate.method],
        attribution=Attribution.CLINICIAN if actor_id else Attribution.PATIENT,
        calculated_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def latest_calculation(db: Session, assessment: BurnAssessment) -> TbsaCalculation | None:
    return db.scalar(
        select(TbsaCalculation)
        .where(TbsaCalculation.assessment_id == assessment.id)
        .order_by(TbsaCalculation.calculated_at.desc(), TbsaCalculation.id)
        .limit(1)
    )


def override_total(
    db: Session, calculation: TbsaCalculation, *, percent: float, note: str, actor_id
) -> TbsaCalculation:
    """A clinician's own figure, recorded beside the computed one rather than over it."""
    if not 0.0 <= percent <= 100.0:
        raise ValueError("a surface area percentage must be between 0 and 100")
    calculation.clinician_percent = percent
    calculation.clinician_note = note
    calculation.attribution = Attribution.CLINICIAN
    calculation.calculated_by = actor_id
    db.flush()
    return calculation


@dataclass
class Reconciled:
    raised: list[BurnAlert]
    cleared: list[str]


def refresh_alerts(db: Session, assessment: BurnAssessment) -> Reconciled:
    """Recompute the review flags and reconcile them against what is stored.

    A flag whose finding has gone is removed, unless a clinician acknowledged it — an
    acknowledgement is a record that someone looked, and deleting it would erase that.
    """
    incident = assessment.incident
    calculation = latest_calculation(db, assessment)
    current = alert_rules.evaluate(
        regions=[
            {
                "region_code": row.region_code,
                "depth": row.depth.value,
                "circumferential": row.circumferential,
            }
            for row in assessment.regions
        ],
        total_percent=calculation.effective_percent if calculation else None,
        age_years=assessment.age_years,
        cause=incident.cause,
        enclosed_space=incident.enclosed_space,
        airway_symptoms=list(incident.airway_symptoms or []),
        provisional=calculation.provisional if calculation else False,
    )
    wanted = {alert.code: alert for alert in current}
    existing = {row.code: row for row in assessment.alerts}

    raised = []
    for code, alert in wanted.items():
        row = existing.get(code)
        if row is None:
            row = BurnAlert(
                assessment_id=assessment.id,
                code=code,
                severity=alert.severity,
                message=alert.message,
                detail=alert.detail,
            )
            db.add(row)
            raised.append(row)
        else:
            row.severity = alert.severity
            row.message = alert.message
            row.detail = alert.detail

    cleared = []
    for code, row in existing.items():
        if code not in wanted and row.acknowledged_at is None:
            db.delete(row)
            cleared.append(code)
    db.flush()
    return Reconciled(raised=raised, cleared=cleared)


def recalculate(
    db: Session,
    assessment: BurnAssessment,
    *,
    method: TbsaMethod = TbsaMethod.LUND_BROWDER,
    actor_id=None,
) -> tuple[TbsaCalculation, Reconciled]:
    """The usual sequence after a region changes: cost it, then re-derive the flags."""
    calculation = calculate(db, assessment, method=method, actor_id=actor_id)
    return calculation, refresh_alerts(db, assessment)


def open_assessment(
    db: Session,
    incident: BurnIncident,
    *,
    patient: Patient,
    actor_id=None,
    assessed_at: datetime | None = None,
) -> BurnAssessment:
    moment = assessed_at or now()
    assessment = BurnAssessment(
        incident_id=incident.id,
        patient_id=patient.id,
        assessed_at=moment,
        assessed_by=actor_id,
        age_years=age_at(patient, moment),
        state=ReviewState.DRAFT,
    )
    db.add(assessment)
    db.flush()
    return assessment


def submit_for_review(db: Session, assessment: BurnAssessment) -> BurnAssessment:
    require_editable(assessment)
    if not assessment.regions:
        raise ValueError("an assessment with no burned region has nothing to review")
    assessment.state = ReviewState.AWAITING_REVIEW
    db.flush()
    return assessment


def confirm(
    db: Session, assessment: BurnAssessment, *, actor_id, note: str | None = None
) -> BurnAssessment:
    undecided = [
        row.region_code for row in assessment.regions if row.depth is BurnDepth.UNCERTAIN
    ]
    if undecided:
        raise ValueError(
            "every burned area needs a decided depth before the assessment is confirmed; "
            "still undecided: " + ", ".join(sorted(undecided))
        )
    assessment.state = ReviewState.CONFIRMED
    assessment.reviewed_by = actor_id
    assessment.reviewed_at = now()
    assessment.review_note = note
    db.flush()
    return assessment


def amend(db: Session, assessment: BurnAssessment, *, actor_id, note: str) -> BurnAssessment:
    """Reopen a confirmed assessment, recording that it was reopened and by whom."""
    assessment.state = ReviewState.AMENDED
    assessment.reviewed_by = actor_id
    assessment.reviewed_at = now()
    assessment.review_note = note
    db.flush()
    return assessment
