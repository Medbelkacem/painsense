import time
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from backend.ai import (
    confounders,
    explainability,
    features,
    model,
    population,
    quality,
    trajectory,
    uncertainty,
)
from backend.ai.confounders import ContextAnalysis
from backend.ai.explainability import Contribution
from backend.ai.population import PopulationReading
from backend.ai.quality import QualityReport
from backend.ai.trajectory import BaselineComparison, EarlierAssessment
from backend.ai.uncertainty import Interval
from database.models import (
    DataQuality,
    PainAssessment,
    PainPrediction,
    PredictionAlert,
    PredictionCategory,
    PredictionContribution,
)
from knowledge import causes, rules
from knowledge.context import ClinicalContext

MODEL_UNAVAILABLE = (
    "Model unavailable. A model has to be trained before an estimate can be produced."
)
STALE_MODEL = (
    "The active model was fitted on a different set of features from the one the platform "
    "now assembles. Train a model on the current feature set before asking for an estimate."
)
INSUFFICIENT = "Prediction cannot be responsibly generated from the available information."


@dataclass
class Estimate:
    quality: QualityReport
    alerts: list[rules.Alert]
    priority: rules.Priority
    categories: list[causes.Match]
    context_analysis: ContextAnalysis
    baseline: BaselineComparison
    population: PopulationReading
    refused: bool = False
    refusal_reason: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    dataset_version: str | None = None
    feature_schema_version: str | None = None
    inference_ms: float | None = None
    interval: Interval | None = None
    band_code: str | None = None
    band_label: str | None = None
    contributions: list[Contribution] = field(default_factory=list)
    feature_values: dict[str, float] = field(default_factory=dict)


def earlier_assessments(assessment: PainAssessment) -> list[EarlierAssessment]:
    earlier = []
    for other in assessment.patient.assessments:
        if other.id == assessment.id or other.created_at >= assessment.created_at:
            continue
        vitals = {}
        if other.measurement is not None:
            for name in trajectory.BASELINE_TOLERANCE:
                value = getattr(other.measurement, name)
                if value is not None:
                    vitals[name] = float(value)
        earlier.append(
            EarlierAssessment(
                created_at=other.created_at,
                estimated_pain=(
                    other.prediction.estimated_pain if other.prediction is not None else None
                ),
                vitals=vitals,
            )
        )
    return earlier


def _refusal(
    reason: str,
    report: QualityReport,
    alerts: list[rules.Alert],
    ctx: ClinicalContext,
    earlier: list[EarlierAssessment],
) -> Estimate:
    return Estimate(
        quality=report,
        alerts=alerts,
        priority=rules.priority(
            ctx,
            None,
            alerts,
            contradictions=len(report.issues),
            completeness=report.completeness,
        ),
        categories=causes.candidates(ctx),
        context_analysis=confounders.analyse(ctx),
        baseline=trajectory.compare(earlier, None, ctx.vitals, baseline=ctx.baseline_vitals),
        population=population.read(ctx),
        refused=True,
        refusal_reason=reason,
    )


def estimate(
    db: Session, ctx: ClinicalContext, earlier: list[EarlierAssessment] | None = None
) -> Estimate:
    earlier = earlier or []
    report = quality.assess(ctx)
    alerts = rules.evaluate(ctx)

    if not report.sufficient:
        return _refusal(
            f"{INSUFFICIENT} " + " ".join(report.blocking), report, alerts, ctx, earlier
        )

    try:
        bundle, _ = model.active(db)
    except model.ModelUnavailable as exc:
        return _refusal(f"{MODEL_UNAVAILABLE} ({exc})", report, alerts, ctx, earlier)

    if (
        tuple(bundle.feature_names) != features.NAMES
        or bundle.feature_schema_version != features.FEATURE_SCHEMA_VERSION
    ):
        return _refusal(STALE_MODEL, report, alerts, ctx, earlier)

    started = time.perf_counter()
    x = features.vector(ctx)
    row = x.reshape(1, -1)
    point = float(bundle.point.predict(row)[0])
    low = float(bundle.lower.predict(row)[0])
    high = float(bundle.upper.predict(row)[0])
    contributions = explainability.contributions(bundle, x)
    inference_ms = round((time.perf_counter() - started) * 1000, 2)

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
        priority=rules.priority(
            ctx,
            interval.point,
            alerts,
            contradictions=len(report.issues),
            completeness=report.completeness,
        ),
        categories=causes.candidates(ctx),
        context_analysis=analysis,
        baseline=trajectory.compare(
            earlier, interval.point, ctx.vitals, baseline=ctx.baseline_vitals
        ),
        population=population.read(ctx),
        model_name=bundle.model_name,
        model_version=bundle.version,
        dataset_version=bundle.dataset_version,
        feature_schema_version=bundle.feature_schema_version,
        inference_ms=inference_ms,
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
    if assessment.prediction is not None:
        db.delete(assessment.prediction)
        db.flush()

    prediction = PainPrediction(
        assessment_id=assessment.id,
        patient_id=assessment.patient_id,
        model_name=result.model_name,
        model_version=result.model_version,
        dataset_version=result.dataset_version,
        feature_schema_version=result.feature_schema_version,
        inference_ms=result.inference_ms,
        estimated_pain=result.interval.point if result.interval else None,
        interval_low=result.interval.low if result.interval else None,
        interval_high=result.interval.high if result.interval else None,
        band=result.band_code,
        priority_score=result.priority.score,
        priority_level=result.priority.level,
        priority_factors=[
            {"code": factor.code, "label": factor.label, "points": factor.points}
            for factor in result.priority.factors
        ],
        trajectory=result.baseline.trajectory,
        baseline=result.baseline.to_dict(),
        profile_code=result.population.primary,
        profile_modifiers=list(result.population.modifiers),
        reference_scale=result.population.reference_scale,
        can_self_report=result.population.can_self_report,
        profile_penalty=result.context_analysis.profile_widening,
        data_quality=DataQuality(result.quality.level),
        data_quality_score=result.quality.score,
        quality_issues=list(result.quality.issues) + list(result.quality.outliers),
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
                "source": note.source,
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
