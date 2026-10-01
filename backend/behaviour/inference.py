"""Offering acoustic features to a voice model, and saying plainly what it can answer.

There is a voice model in this platform and it is trained on real human recordings — 779
utterances from 194 speakers in the PainSpeech-4 Arabic corpus, which labels each one on a
four-level scale: no pain, low, middle, high. That is what it predicts, and the one thing
this module will not do is turn its answer into a number out of ten.

The reason is the platform's standing rule about labels, and it applies here as much as it
does to the dataset pipeline. The corpus documents four ordinal classes and publishes no
mapping from them onto a 0-10 numerical rating scale. Inventing one — calling "high" an 8,
say — would manufacture a precision the data does not have and would quietly make a 0-10
figure out of something that was never measured on that scale. So the level is reported as
a level, on its own scale, beside the clinical estimate rather than inside it.

Two honest limits come with it, and they are returned with every estimate rather than
buried here:

The corpus publishes cepstral coefficients, not audio. There is no way to confirm that the
coefficients this platform computes from a live microphone are identical to the ones it was
trained on; the extraction geometry is matched to the library defaults the corpus's column
naming points at, and that is an inference about how it was produced, not a fact it states.

The recordings are of elicited pain in volunteers speaking Arabic. Nothing establishes that
the acoustic change they carry is the same change a patient in a ward produces, and the
model has never been evaluated on one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.behaviour import schema
from database.models import ModelVersion

#: The registry name a model must carry to be offered acoustic features.
MODEL_NAME = "voice-pain"

#: The four levels the training corpus labels, in order. The index is what the model
#: regresses, so a prediction of 2.4 sits between low and middle, which is more informative
#: than rounding it to one of them.
LEVELS = ("no pain", "low", "middle", "high")

UNAVAILABLE_MESSAGE = (
    "Voice model unavailable — the recording was measured and its acoustic features "
    "stored, but estimating a pain level needs a trained model."
)

LIMITATIONS = (
    (
        "The level is on the four-point scale of the corpus the model was trained on, not "
        "a 0-10 score. No mapping between the two is published and none is invented here."
    ),
    (
        "The corpus publishes cepstral coefficients rather than audio, so it cannot be "
        "confirmed that the coefficients measured here are identical to the ones the "
        "model was trained on."
    ),
    (
        "The corpus is elicited pain in volunteers speaking Arabic. Whether the acoustic "
        "change it carries is the change a patient in a ward produces has not been "
        "established."
    ),
)


@dataclass
class Estimate:
    available: bool
    message: str
    model_version: str | None = None
    #: Position on the four-level scale, 1 to 4.
    level: float | None = None
    label: str | None = None
    #: The model's own cross-validated mean absolute error, in levels. The honest width
    #: around the figure above.
    level_error: float | None = None
    limitations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "message": self.message,
            "model_version": self.model_version,
            "level": self.level,
            "label": self.label,
            "level_error": self.level_error,
            "scale": list(LEVELS),
            "limitations": self.limitations,
        }


def label_for(level: float) -> str:
    """The nearest named level. Rounded for display only; the number is what is stored."""
    index = min(len(LEVELS) - 1, max(0, round(level) - 1))
    return LEVELS[index]


def find_model(db: Session) -> ModelVersion | None:
    """The active voice model for this feature schema, or None.

    The feature schema version is checked as well as the name. A model trained on an older
    set of coefficients would accept the right number of columns and mean something
    different by them, which is worse than having no model.
    """
    rows = db.scalars(
        select(ModelVersion)
        .where(ModelVersion.model_name == MODEL_NAME, ModelVersion.is_active.is_(True))
        .order_by(ModelVersion.trained_at.desc())
    ).all()
    return next(
        (row for row in rows if row.feature_schema_version == schema.FEATURE_SCHEMA_VERSION),
        None,
    )


def unavailable(reason: str | None = None) -> Estimate:
    return Estimate(
        available=False,
        message=UNAVAILABLE_MESSAGE,
        limitations=([reason] if reason else []) + list(LIMITATIONS),
    )


def estimate(db: Session, cepstral: dict[str, float], *, voice_usable: bool) -> Estimate:
    """Ask the registered voice model for a level, or report that there is none.

    Quality is checked before the model rather than after. A model handed coefficients
    from a recording of a corridor returns a confident level about the corridor.
    """
    if not voice_usable:
        return unavailable(
            "the voice quality was not good enough for its features to be offered to a "
            "model"
        )
    if not cepstral:
        return unavailable("no cepstral coefficient was derived from this recording")

    row = find_model(db)
    if row is None:
        return unavailable(
            f"no active model is registered under {MODEL_NAME!r} for feature schema "
            f"version {schema.FEATURE_SCHEMA_VERSION}. The measurement is complete and "
            "stored; only the voice level is missing."
        )

    from backend.ai import model as model_store

    bundle = model_store.load(row.version)
    names = tuple(getattr(bundle, "feature_names", ()) or row.features or ())
    missing = [name for name in names if name not in cepstral]
    if missing:
        return unavailable(
            f"model {row.version} expects {len(names)} coefficient(s) and {len(missing)} "
            "were not derived from this recording: " + ", ".join(missing[:5])
        )

    vector = [[float(cepstral[name]) for name in names]]
    level = float(bundle.point.predict(vector)[0])
    level = min(float(len(LEVELS)), max(1.0, level))
    return Estimate(
        available=True,
        message=(
            "Experimental level from a research model trained on elicited pain in healthy "
            "volunteers. Not a clinical measurement."
        ),
        model_version=row.version,
        level=round(level, 2),
        label=label_for(level),
        level_error=row.mae,
        limitations=list(LIMITATIONS),
    )
