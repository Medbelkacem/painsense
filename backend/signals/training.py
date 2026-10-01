"""Fitting the signal pain model on the PainMonit database.

`app.signals.inference` has always said there was no model behind the signal features and
named what one would have to be: registered under its model name, declaring its feature
schema version. This is that model.

Five decisions, each of which changes what the number it produces is worth.

**Grouped by person, always.** Every figure here comes from a cross-validated prediction
made by a model that never saw that person. It is the only validation worth running on this
corpus. The experimental half gives each volunteer forty-odd windows and the clinical half
gives each patient two sessions of them, and a model split at random across rows scores
well by recognising a person's skin rather than their pain — resting conductance differs
several-fold between people and barely at all within one.

**The feature set is chosen, not assumed.** The corpus offers skin conductance, pulse and
respiration. All three are measured, every combination is cross-validated, and the one with
the lowest held-out error is what gets fitted and registered. Which features a model
declares decides which recordings it can ever be offered, so adding a channel that earns
nothing is not free: it makes the model unusable whenever that channel is missing.

**It predicts the label its half publishes, on that label's own scale.** The experimental
half is a continuous visual analogue rating, 0 to 100. The clinical half is the patient's
spoken 0-10 number. A visual analogue scale is not a numeric rating scale and no conversion
between them is published, so none is made here — the scale travels with the model and
`app.signals.inference` reports it beside the number.

**It is compared against predicting the mean.** A model that cannot beat that has learned
nothing. The comparison is stored with it, and a model that loses it is registered inactive
rather than thrown away: "this half carries no usable signal under person-grouped
validation" is a finding worth keeping.

**No interval is fitted.** A quantile pair would have to be fitted on the same heavily
overlapping windows as the point estimate, and over a clinical session the windows twenty
seconds back from ratings seven seconds apart are very nearly the same twenty seconds. The
cross-validated error is reported instead, which is the one error figure this model has.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import model as model_store
from database.models import ModelVersion
from security import audit
from backend.signals import inference, painmonit, schema

#: Folds for the person-grouped cross-validation. Five over fifty-odd people leaves ten
#: unseen people per fold, which is enough for a fold error to mean something.
FOLDS = 5

#: The feature sets tried, by the channels they come from. Named by channel rather than
#: listed by feature because the features are whatever `app.signals.features` derives from
#: that channel, and that is the list the winner declares.
CHANNEL_SETS = {
    "gsr": ("GSR_PALMAR",),
    "gsr+ppg": ("GSR_PALMAR", "PPG_FINGER"),
    "gsr+ppg+resp": ("GSR_PALMAR", "PPG_FINGER", "RESPIRATION_BELT"),
}


def candidates(seed: int):
    """The three worth trying on a few thousand windows and a handful of columns.

    Deliberately small. The rows are not independent — consecutive windows over one session
    overlap — so the effective sample size is well under the row count, and a deeper model
    spends that on memorising people. Each handles a missing feature, because a pulse with
    no findable beats leaves one.
    """
    return (
        (
            "hgb",
            "HistGradientBoostingRegressor",
            HistGradientBoostingRegressor(
                max_iter=300,
                learning_rate=0.05,
                max_leaf_nodes=31,
                min_samples_leaf=20,
                l2_regularization=1.0,
                random_state=seed,
            ),
        ),
        (
            "random_forest",
            "RandomForestRegressor with median imputation",
            Pipeline(
                [
                    # keep_empty_features: a feature that is null for every row of a
                    # training fold would otherwise be dropped, and the columns after it
                    # would shift up into its place.
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    (
                        "model",
                        RandomForestRegressor(
                            n_estimators=400,
                            min_samples_leaf=3,
                            n_jobs=-1,
                            random_state=seed,
                        ),
                    ),
                ]
            ),
        ),
        (
            "ridge",
            "RidgeCV (linear baseline)",
            Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    ("scaler", StandardScaler()),
                    ("model", RidgeCV(alphas=np.logspace(-2, 3, 24))),
                ]
            ),
        ),
    )


@dataclass
class Result:
    candidate: str
    algorithm: str
    channels: str
    features: list[str] = field(default_factory=list)
    n_windows: int = 0
    n_subjects: int = 0
    #: Mean absolute error on the label's own scale, over people the model never saw.
    mae: float = 0.0
    rmse: float = 0.0
    r2: float = 0.0
    pearson: float = 0.0
    #: Spread of the per-fold error, which says whether the figure above is stable or an
    #: average of one good fold and one bad one.
    fold_mae_sd: float = 0.0
    #: The error of predicting the mean for everything. The floor to beat.
    baseline_mae: float = 0.0
    #: Experimental half only. How well the predicted rating tells a rest window from the
    #: hottest calibrated stimulus, and from any stimulus at all. The first is the
    #: discrimination this corpus is usually reported on; the second is the harder question
    #: and the honest one, since the lowest steps are near a volunteer's own threshold and
    #: were often rated at nothing.
    auc_rest_vs_highest: float | None = None
    auc_rest_vs_any: float | None = None
    #: Error per labelled step, so a model that only works at the extremes is visible.
    by_level: dict[str, float] = field(default_factory=dict)

    @property
    def beats_mean(self) -> bool:
        return self.mae < self.baseline_mae

    def as_dict(self) -> dict:
        out = {
            "candidate": self.candidate,
            "algorithm": self.algorithm,
            "channels": self.channels,
            "n_features": len(self.features),
            "n_windows": self.n_windows,
            "n_subjects": self.n_subjects,
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "pearson": self.pearson,
            "fold_mae_sd": self.fold_mae_sd,
            "baseline_mae": self.baseline_mae,
            "beats_mean": self.beats_mean,
        }
        if self.auc_rest_vs_highest is not None:
            out["auc_rest_vs_highest"] = self.auc_rest_vs_highest
            out["auc_rest_vs_any"] = self.auc_rest_vs_any
        if self.by_level:
            out["by_level"] = self.by_level
        return out


def features_for(frame: pd.DataFrame, channels: tuple[str, ...]) -> list[str]:
    """The feature columns belonging to those channels, in the frame's own order.

    The order is the feature vector. It is stored on the model and read back at inference
    to pull values out of a recording's feature dictionary by name, so a permutation here
    would be caught — but only by name, which is why the names are what is stored and not
    the positions.
    """
    return [
        column
        for column in frame.columns
        if "__" in column and column.split("__")[0] in channels
    ]


def _score(
    code: str,
    algorithm: str,
    channels: str,
    names: list[str],
    frame: pd.DataFrame,
    predicted: np.ndarray,
    membership: np.ndarray,
) -> Result:
    y = frame["target"].to_numpy(dtype=float)
    groups = frame["subject"].to_numpy()
    per_fold = [
        float(mean_absolute_error(y[membership == fold], predicted[membership == fold]))
        for fold in np.unique(membership)
    ]
    result = Result(
        candidate=code,
        algorithm=algorithm,
        channels=channels,
        features=names,
        n_windows=len(y),
        n_subjects=len(np.unique(groups)),
        mae=round(float(mean_absolute_error(y, predicted)), 4),
        rmse=round(float(np.sqrt(np.mean((y - predicted) ** 2))), 4),
        r2=round(float(r2_score(y, predicted)), 4),
        pearson=round(float(np.corrcoef(y, predicted)[0, 1]), 4),
        fold_mae_sd=round(float(np.std(per_fold)), 4),
        baseline_mae=round(float(np.mean(np.abs(y - y.mean()))), 4),
    )

    levels = frame["level"].to_numpy(dtype=float)
    if np.isfinite(levels).all():
        rest = levels == 0
        highest = levels == levels.max()
        pair = rest | highest
        if rest.any() and highest.any():
            result.auc_rest_vs_highest = round(
                float(roc_auc_score(highest[pair].astype(int), predicted[pair])), 4
            )
            result.auc_rest_vs_any = round(
                float(roc_auc_score((levels > 0).astype(int), predicted)), 4
            )
        for level in sorted(set(levels.tolist())):
            mask = levels == level
            result.by_level[f"level_{int(level)}"] = round(
                float(mean_absolute_error(y[mask], predicted[mask])), 4
            )
    return result


def evaluate(frame: pd.DataFrame, *, seed: int = 0, folds: int = FOLDS) -> list[Result]:
    """Every candidate on every feature set, scored on people it never saw.

    `cross_val_predict` with a person-grouped splitter, so every window is predicted by a
    model fitted without that person. One pooled error over all of them rather than a
    single held-out split: fifty-two people split 80/20 leaves ten to judge nine
    combinations on, which would pick a winner out of noise.
    """
    groups = frame["subject"].to_numpy()
    y = frame["target"].to_numpy(dtype=float)
    splitter = GroupKFold(n_splits=min(folds, len(np.unique(groups))))
    # Which fold each window was predicted in, so the spread across folds can be reported
    # and not only the pooled figure.
    membership = np.zeros(len(frame), dtype=int)
    for index, (_, held_out) in enumerate(splitter.split(frame, y, groups)):
        membership[held_out] = index

    scored = []
    for channels, codes in CHANNEL_SETS.items():
        names = features_for(frame, codes)
        if not names:
            continue
        x = frame[names].to_numpy(dtype=float)
        for code, algorithm, estimator in candidates(seed):
            predicted = cross_val_predict(
                clone(estimator), x, y, groups=groups, cv=splitter
            )
            scored.append(
                _score(code, algorithm, channels, names, frame, predicted, membership)
            )
    return scored


def _activate(db: Session, version: str) -> None:
    """Make this the active signal model, leaving every other model family alone.

    Not `app.ai.model.activate`, which clears the flag across the whole registry: the
    registry is shared with the clinical estimator and the voice model, and activating a
    signal model must not deactivate either of those.
    """
    for row in db.scalars(
        select(ModelVersion).where(ModelVersion.model_name == inference.MODEL_NAME)
    ):
        row.is_active = row.version == version
    db.commit()


def _limitations(half: str, chosen: Result) -> list[str]:
    out = [
        (
            f"The number is on the {painmonit.SCALES[half]} of the corpus the model was "
            "trained on. No mapping onto another pain scale is published and none is "
            "invented here."
        ),
        (
            f"Error is {chosen.mae:.2f} on that scale, measured over "
            f"{chosen.n_subjects} people the model never saw, against "
            f"{chosen.baseline_mae:.2f} for predicting the mean."
        ),
        (
            f"The features are autonomic — {chosen.channels.replace('+', ', ')} — and they "
            "move with arousal, attention, movement and room temperature as well as with "
            "pain. The model cannot tell which of those it is reading."
        ),
        (
            "The corpus samples at 250 Hz, so its surface EMG and ECG are below the rate "
            "this platform's EMG channels need and no muscle or cardiac-waveform feature "
            "is part of this model."
        ),
    ]
    if half == painmonit.EXPERIMENTAL:
        out.append(
            "Trained on contact heat applied to healthy volunteers at temperatures "
            "calibrated to each person between their own threshold and tolerance. Whether "
            "the autonomic change that produces is the change a patient in pain on a ward "
            "produces is not something this corpus can answer."
        )
    else:
        out.append(
            "Trained during physiotherapy, where the patient is being moved. Ratings are "
            "spoken every few seconds, so consecutive windows overlap and the model sees "
            "far fewer independent moments than it has rows."
        )
    return out


def train(
    db: Session,
    *,
    dataset: Path,
    half: str = painmonit.EXPERIMENTAL,
    seed: int = 0,
    folds: int = FOLDS,
    limit_subjects: int | None = None,
    activate: bool = True,
    actor_id=None,
) -> tuple[ModelVersion, list[Result]]:
    """Read the corpus, fit the best candidate, register it, and activate it if it earned it."""
    frame = painmonit.table(painmonit.read(dataset, half, limit_subjects=limit_subjects))
    scored = evaluate(frame, seed=seed, folds=folds)
    if not scored:
        raise painmonit.NoCorpus(
            f"no feature survived quality assessment in the {half} half of {dataset}"
        )
    chosen = min(scored, key=lambda result: result.mae)
    if not chosen.beats_mean:
        activate = False

    estimator = next(
        estimator for code, _, estimator in candidates(seed) if code == chosen.candidate
    )
    x = frame[chosen.features].to_numpy(dtype=float)
    y = frame["target"].to_numpy(dtype=float)
    estimator.fit(x, y)

    low, high = (0.0, 100.0) if half == painmonit.EXPERIMENTAL else (0.0, 10.0)
    version = f"{inference.MODEL_NAME}-{painmonit.CORPUS_ID}-{half}-s{seed}"
    algorithm = f"{chosen.algorithm} on {len(chosen.features)} {chosen.channels} features"
    profile = {
        "corpus": painmonit.CORPUS_ID,
        "half": half,
        "citation": painmonit.CITATION,
        "licence": painmonit.LICENCE,
        "scale": painmonit.SCALES[half],
        "scale_range": [low, high],
        "window_seconds": (
            painmonit.STIMULUS_WINDOW_SECONDS
            if half == painmonit.EXPERIMENTAL
            else painmonit.CLINICAL_WINDOW_SECONDS
        ),
        "validation": f"GroupKFold(person), {chosen.n_subjects} people, {folds} folds",
        "candidates": [result.as_dict() for result in scored],
        "quality_verdicts": frame["verdict"].value_counts().to_dict(),
        "limitations": _limitations(half, chosen),
    }
    bundle = model_store.Bundle(
        version=version,
        algorithm=algorithm,
        point=estimator,
        lower=None,
        upper=None,
        feature_names=tuple(chosen.features),
        observed_coverage=0.0,
        residual_sd=chosen.mae,
        dataset_version=f"{painmonit.CORPUS_ID}:{half}",
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
        model_name=inference.MODEL_NAME,
        training_profile=profile,
    )
    artifact = model_store.save(bundle)
    model_store.forget(version)

    row = db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if row is None:
        row = ModelVersion(version=version)
        db.add(row)
    row.model_name = inference.MODEL_NAME
    row.algorithm = algorithm[:80]
    row.dataset_version = bundle.dataset_version
    row.feature_schema_version = schema.FEATURE_SCHEMA_VERSION
    row.n_train = chosen.n_windows
    row.n_validation = 0
    row.n_test = 0
    row.mae = chosen.mae
    row.rmse = chosen.rmse
    row.r2 = chosen.r2
    row.pearson = chosen.pearson
    row.cv_folds = min(folds, chosen.n_subjects)
    # Every figure stored already comes from people the model never saw, so there is no
    # separate test split for the cross-validated error to be distinguished from.
    row.cv_mae_mean = chosen.mae
    row.cv_mae_sd = chosen.fold_mae_sd
    row.residual_sd = chosen.rmse
    row.features = list(chosen.features)
    row.comparison = [result.as_dict() for result in scored]
    row.training_profile = profile
    row.artifact_name = artifact.name
    row.notes = _notes(half, chosen, activate)
    db.commit()

    if activate:
        _activate(db, version)
    else:
        row.is_active = False
        db.commit()

    audit.record(
        db,
        event_type=audit.MODEL_TRAINED,
        actor_id=actor_id,
        resource="model",
        resource_id=version,
        meta={
            "model_name": inference.MODEL_NAME,
            "corpus": painmonit.CORPUS_ID,
            "half": half,
            "candidate": chosen.candidate,
            "channels": chosen.channels,
            "mae": chosen.mae,
            "baseline_mae": chosen.baseline_mae,
            "subjects": chosen.n_subjects,
            "activated": activate,
        },
        ledger_payload={
            "version": version,
            "corpus": f"{painmonit.CORPUS_ID}:{half}",
            "mae": chosen.mae,
            "features": list(chosen.features),
        },
    )
    return row, scored


def _notes(half: str, chosen: Result, activated: bool) -> str:
    out = (
        f"Trained on {chosen.n_windows} windows from {chosen.n_subjects} people in the "
        f"{half} half of the PainMonit database. Person-grouped cross-validation: "
        f"{chosen.mae:.2f} error on the {painmonit.SCALES[half]} against "
        f"{chosen.baseline_mae:.2f} for predicting the mean, r={chosen.pearson:.2f}."
    )
    if chosen.auc_rest_vs_highest is not None:
        out += (
            f" Separates a rest window from the hottest calibrated stimulus at "
            f"AUC {chosen.auc_rest_vs_highest:.2f}, and from any stimulus at "
            f"AUC {chosen.auc_rest_vs_any:.2f}."
        )
    if not activated:
        out += (
            " Registered inactive: it does not beat predicting the mean, which is a "
            "finding about this half of the corpus and not a reason to discard the record."
        )
    out += f" Used under the {painmonit.LICENCE} Cite: {painmonit.CITATION}"
    return out
