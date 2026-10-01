"""Offering signal features to a pain model, and reporting honestly when there is none.

This module is the one place that decides whether a recording's features can be turned into
a number, and says why not when they cannot, rather than leaving each caller to invent an
answer to that.

The lookup is deliberately narrow: an *active* model, registered under this module's model
name, declaring this module's feature schema version. The platform's clinical estimator is
not acceptable here and this one is not acceptable there — that one takes a feature schema
built from a clinician's examination, pain sites and qualities and functional impact, and a
band power is not in it. A model trained against an older feature set would take the right
number of columns and mean something different by them, which is worse than having none.

What a model registered here is fitted on is up to whoever trains it;
`app.signals.training` fits the one this platform ships, on the PainMonit database. It does
not use every channel this module's schema defines, and it is not on a 0-10 scale. Both are
properties of the corpus rather than of this path, so neither is assumed here: the model
declares the scale its number is on and the features it needs, and an estimate that cannot
be made for want of a feature says which one was missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.signals import schema
from database.models import ModelVersion

#: The registry name a model must carry to be offered signal features.
MODEL_NAME = "eeg-emg-pain"
#: The scale an estimate is on when its model does not say otherwise. Every model
#: registered before the scale was recorded was fitted against this platform's own 0-10
#: target, so it is the right reading of a missing declaration rather than a guess.
NRS_SCALE = "numeric rating scale, 0-10"
NRS_RANGE = (0.0, 10.0)

#: The exact wording the interface shows when no such model exists. Specified by the brief,
#: and kept here so the API, the report and the interface cannot drift apart.
UNAVAILABLE_MESSAGE = (
    "AI model unavailable — signal recording and feature analysis completed, but pain "
    "estimation requires a trained model."
)


@dataclass
class Estimate:
    available: bool
    message: str
    model_version: str | None = None
    pain_score: float | None = None
    category: str | None = None
    #: What the score is a number on, in the words of whoever published the labels the
    #: model was trained against. Never absent from an available estimate: a pain figure
    #: with no scale named beside it is not readable.
    scale: str | None = None
    uncertainty: float | None = None
    interval: tuple[float, float] | None = None
    contributing: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "message": self.message,
            "model_version": self.model_version,
            "pain_score": self.pain_score,
            "category": self.category,
            "scale": self.scale,
            "uncertainty": self.uncertainty,
            "interval": list(self.interval) if self.interval else None,
            "contributing_features": self.contributing,
            "limitations": self.limitations,
        }


def find_model(db: Session) -> ModelVersion | None:
    """The active model registered for this feature schema, or None.

    The feature schema version is checked as well as the name. A model trained on an older
    feature set would accept the right number of columns and mean something different by
    them, which is worse than having no model at all.
    """
    candidates = db.scalars(
        select(ModelVersion)
        .where(
            ModelVersion.model_name == MODEL_NAME,
            ModelVersion.is_active.is_(True),
        )
        .order_by(ModelVersion.trained_at.desc())
    ).all()
    return next(
        (
            row
            for row in candidates
            if row.feature_schema_version == schema.FEATURE_SCHEMA_VERSION
        ),
        None,
    )


def unavailable(reason: str | None = None) -> Estimate:
    return Estimate(
        available=False,
        message=UNAVAILABLE_MESSAGE,
        limitations=[reason] if reason else [],
    )


def estimate(db: Session, features: dict[str, float], *, quality_verdict: str) -> Estimate:
    """Ask the registered model for an estimate, or report that there is none.

    Quality is checked before the model, not after. A model given features from an unusable
    trace returns a confident number about nothing, and the recording is still worth saving
    — which is why this returns an unavailable estimate rather than raising.
    """
    from backend.signals.quality import ADEQUATE, GOOD

    if not features:
        return unavailable(
            "no feature could be derived from this recording, so there was nothing to "
            "offer a model"
        )
    if quality_verdict not in (GOOD, ADEQUATE):
        return unavailable(
            f"signal quality was {quality_verdict.lower()}; features from an unusable trace "
            "are not offered to a model"
        )

    row = find_model(db)
    if row is None:
        return unavailable(
            f"no active model is registered under {MODEL_NAME!r} for feature schema "
            f"version {schema.FEATURE_SCHEMA_VERSION}. Recording, quality assessment and "
            "feature extraction are complete and stored; only the pain estimate is missing."
        )

    from backend.ai import model as model_store

    bundle = model_store.load(row.version)
    names = tuple(getattr(bundle, "feature_names", ()) or row.features or ())
    missing = [name for name in names if name not in features]
    if missing:
        return unavailable(
            f"model {row.version} expects {len(names)} feature(s) and "
            f"{len(missing)} were not derived from this recording: "
            + ", ".join(missing[:5])
        )

    vector = [[float(features[name]) for name in names]]
    point = float(bundle.point.predict(vector)[0])
    lower = upper = None
    if getattr(bundle, "lower", None) is not None and getattr(bundle, "upper", None) is not None:
        lower = float(bundle.lower.predict(vector)[0])
        upper = float(bundle.upper.predict(vector)[0])

    profile = row.training_profile if isinstance(row.training_profile, dict) else {}
    scale, (low, high) = _scale_of(profile)
    score = round(min(high, max(low, point)), 2)
    return Estimate(
        available=True,
        message="Experimental estimate from a research model. Not a clinical measurement.",
        model_version=row.version,
        pain_score=score,
        # A band only where the scale is the platform's own 0-10 one. The band boundaries
        # are defined on that scale, and applying them to a visual analogue rating would
        # read 30 out of 100 as severe pain.
        category=_band(score) if scale == NRS_SCALE else None,
        scale=scale,
        uncertainty=round(float(getattr(bundle, "residual_sd", 0.0) or 0.0), 3),
        interval=(
            (round(max(low, lower), 2), round(min(high, upper), 2))
            if lower is not None and upper is not None
            else None
        ),
        limitations=list(profile.get("limitations", [])),
    )


def _scale_of(profile: dict) -> tuple[str, tuple[float, float]]:
    """The scale a model's number is on, and the range to clamp it to.

    Clamped to the scale's own endpoints rather than to 0-10: a regressor asked to predict
    a 0-100 rating will sometimes answer 104, and clamping that to 10 would turn the
    highest pain in the corpus into a tenth of the range.
    """
    scale = profile.get("scale") or NRS_SCALE
    declared = profile.get("scale_range")
    if isinstance(declared, (list, tuple)) and len(declared) == 2:
        return scale, (float(declared[0]), float(declared[1]))
    return scale, NRS_RANGE


def _band(score: float) -> str:
    """The 0-10 band, using the platform's existing boundaries."""
    from knowledge.rules import PAIN_BANDS

    for upper, _code, label in PAIN_BANDS:
        if score <= upper:
            return label
    return PAIN_BANDS[-1][2]
