"""The estimation pipeline.

    clinical inputs
      -> validation and data quality
      -> feature assembly
      -> point estimate and quantile interval
      -> context and confounder analysis
      -> explanation
      -> candidate categories, red flags, priority indicator

Two things happen even when no estimate is produced. The red-flag rules still run, because a
record that is too thin for a model is not too thin for "oxygen saturation is 88 per cent".
And the reason for withholding the estimate is returned as a result, not raised as an error,
so the clinician is told why rather than shown a blank panel.
"""

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.ai import confounders, explainability, features, model, quality, uncertainty
from app.ai.confounders import ContextAnalysis
from app.ai.explainability import Contribution
from app.ai.quality import QualityReport
from app.ai.uncertainty import Interval
from app.database.models import (
    DataQuality,
    PainAssessment,
    PainPrediction,
    PredictionAlert,
    PredictionCategory,
    PredictionContribution,
)
from app.knowledge import causes, rules
from app.knowledge.context import ClinicalContext

MODEL_UNAVAILABLE = (
    "Model unavailable. A model has to be trained before an estimate can be produced."
)
STALE_MODEL = (
    "The active model was fitted on a different set of features from the one the platform "
    "now assembles. Train a model on the current feature set before asking for an estimate."
)


@dataclass
class Estimate:
    quality: QualityReport
    alerts: list[rules.Alert]
    priority: rules.Priority
    categories: list[causes.Match]
    context_analysis: ContextAnalysis
    refused: bool = False
    refusal_reason: str | None = None
    model_version: str | None = None
    dataset_version: str | None = None
    interval: Interval | None = None
    band_code: str | None = None
    band_label: str | None = None
    contributions: list[Contribution] = field(default_factory=list)
    feature_values: dict[str, float] = field(default_factory=dict)


def _refusal(
    reason: str,
    report: QualityReport,
    alerts: list[rules.Alert],
    ctx: ClinicalContext,
) -> Estimate:
    return Estimate(
        quality=report,
        alerts=alerts,
        priority=rules.priority(ctx, None, alerts),
        categories=causes.candidates(ctx),
        context_analysis=confounders.analyse(ctx),
        refused=True,
        refusal_reason=reason,
    )


def estimate(db: Session, ctx: ClinicalContext) -> Estimate:
    report = quality.assess(ctx)
    alerts = rules.evaluate(ctx)

    if not report.sufficient:
        return _refusal(
            "The available information is not sufficient for a reliable estimate. "
            + " ".join(report.blocking),
            report,
            alerts,
            ctx,
        )

    try:
        bundle, _ = model.active(db)
    except model.ModelUnavailable as exc:
        return _refusal(f"{MODEL_UNAVAILABLE} ({exc})", report, alerts, ctx)

    # An artifact from before a change to the feature list would be asked to predict from a
    # vector it was never fitted on. Saying so is a result; letting the estimator line the
    # columns up by position would not be.
    if tuple(bundle.feature_names) != features.NAMES:
        return _refusal(STALE_MODEL, report, alerts, ctx)

    x = features.vector(ctx)
    row = x.reshape(1, -1)
    point = float(bundle.point.predict(row)[0])
    low = float(bundle.lower.predict(row)[0])
    high = float(bundle.upper.predict(row)[0])

    contributions = explainability.contributions(bundle, x)
    analysis = confounders.analyse(ctx, [item.feature for item in contributions])
    interval = uncertainty.build(
        point,
        low,
        high,
        observed_coverage=bundle.observed_coverage,
        widening=analysis.widening,
    )
    band_code, band_label = rules.band(interval.point)

    return Estimate(
        quality=report,
        alerts=alerts,
        priority=rules.priority(ctx, interval.point, alerts),
        categories=causes.candidates(ctx),
        context_analysis=analysis,
        model_version=bundle.version,
        dataset_version=bundle.dataset_version,
        interval=interval,
        band_code=band_code,
        band_label=band_label,
        contributions=contributions,
        feature_values={
            name: (None if np.isnan(value) else round(float(value), 3))
            for name, value in zip(features.NAMES, x)
        },
    )


def store(db: Session, assessment: PainAssessment, result: Estimate) -> PainPrediction:
    """Replace any previous estimate for this assessment with the current one."""
    if assessment.prediction is not None:
        db.delete(assessment.prediction)
        db.flush()

    prediction = PainPrediction(
        assessment_id=assessment.id,
        patient_id=assessment.patient_id,
        model_version=result.model_version,
        dataset_version=result.dataset_version,
        estimated_pain=result.interval.point if result.interval else None,
        interval_low=result.interval.low if result.interval else None,
        interval_high=result.interval.high if result.interval else None,
        band=result.band_code,
        priority_score=result.priority.score,
        priority_factors=[
            {"label": factor.label, "points": factor.points}
            for factor in result.priority.factors
        ],
        data_quality=DataQuality(result.quality.level),
        quality_issues=list(result.quality.issues),
        missing_fields=list(result.quality.missing),
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        features=result.feature_values,
        confounder_notes=[
            {
                "code": note.code,
                "label": note.label,
                "explanation": note.explanation,
                "affected_vitals": note.affected_vitals,
                "vitals_deranged": note.vitals_deranged,
            }
            for note in result.context_analysis.notes
        ],
    )
    db.add(prediction)
    db.flush()

    for rank, item in enumerate(result.contributions, start=1):
        db.add(
            PredictionContribution(
                prediction_id=prediction.id,
                feature=item.feature,
                label=item.label,
                contribution=item.value,
                rank=rank,
            )
        )
    for match in result.categories:
        db.add(
            PredictionCategory(
                prediction_id=prediction.id,
                cause_code=match.cause.code,
                score=match.score,
                matched=list(match.matched),
                missing=list(match.missing),
            )
        )
    for alert in result.alerts:
        db.add(
            PredictionAlert(
                prediction_id=prediction.id,
                rule_code=alert.code,
                severity=alert.severity,
                label=alert.label,
                advice=alert.advice,
                context_notes=list(alert.context_notes),
            )
        )
    db.commit()
    db.refresh(prediction)
    return prediction
