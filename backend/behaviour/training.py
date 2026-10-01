"""Fitting the voice model, on real recordings of real people.

This is the one model in the platform trained on human pain data rather than on synthetic
cases. The corpus is PainSpeech-4: 779 utterances from 194 speakers, each labelled on a
four-level scale by the experiment that elicited it. The platform's dataset pipeline has
already pulled it, normalised its columns and recorded its licence; this module reads that
output and fits a model to it.

Four decisions, each of which changes what the resulting number is worth.

**Grouped by speaker, always.** Every speaker contributes four utterances, one per level.
A random split puts some of a speaker's utterances in training and the rest in test, and
the model then scores well by recognising the voice rather than the pain. Every figure
here comes from speakers the model never heard, which is also why the scores are modest.

**Thirteen features, not a hundred and twenty.** The corpus ships cepstral means, standard
deviations, minima, maxima and two orders of deltas. Only the thirteen means are used,
because they are the only columns whose meaning is unambiguous — the file's own `_std`
columns contain negative values, so whatever they hold is not a standard deviation, and
training on a column whose definition is unknown would make the model impossible to feed
correctly at the bedside. The means our extractor computes are the same quantity.

**It predicts the level, not a score out of ten.** The corpus labels four ordinal classes
and publishes no mapping onto a 0-10 scale. The target is therefore the class index, 1 to
4, regressed rather than classified so that a prediction can fall between two levels.

**It is compared against predicting the mean.** A model that cannot beat that has learned
nothing, and the comparison is stored with it so nobody has to take the error on trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import model as model_store
from backend.behaviour import inference, schema
from config import get_settings
from database.models import ModelVersion
from security import audit

#: The corpus this model is trained on, as the dataset pipeline names it.
CORPUS_ID = "kaggle_messaoudmezati_painspeech_4"

#: Where to look for the pipeline's output for that corpus. The first is the workspace the
#: pipeline writes to in a checkout; the second is where an acquired copy lands in a
#: deployment.
def corpus_directories() -> tuple[Path, ...]:
    return (
        Path(__file__).resolve().parents[2].parent / "dataset" / "sources" / CORPUS_ID,
        get_settings().external_dataset_path / CORPUS_ID,
    )


#: The columns the model is fitted on, in a fixed order, under the names this platform's
#: own extractor produces. The order is the feature vector: it is stored on the model and
#: re-read at inference, so changing it here without retraining would silently permute the
#: input.
FEATURES = tuple(f"mfcc_{index}_mean" for index in range(1, schema.MFCC_COUNT + 1))

#: What those are called in the pipeline's normalised output.
SOURCE_PREFIX = "src_"

TARGET = "original_pain_score"
SUBJECT = "patient_id"

#: Folds for the speaker-grouped cross-validation. Five over 194 speakers leaves about 39
#: unseen speakers per fold.
FOLDS = 5


class NoCorpus(RuntimeError):
    """The corpus is not where it was looked for."""


@dataclass
class Result:
    candidate: str
    algorithm: str
    n_utterances: int = 0
    n_speakers: int = 0
    #: Mean absolute error in levels, over speakers the model never heard.
    mae: float = 0.0
    rmse: float = 0.0
    r2: float = 0.0
    #: Correlation between the predicted level and the labelled one.
    pearson: float = 0.0
    #: Spread of the per-fold error, which says whether the mean above is stable or an
    #: average of one good fold and one bad one.
    fold_mae_sd: float = 0.0
    #: The error of predicting the training mean for everything. The floor to beat.
    baseline_mae: float = 0.0
    #: Share of utterances whose predicted level rounds to the labelled one.
    exact_level: float = 0.0
    #: Share within one level, which is the tolerance the four-point scale deserves.
    within_one_level: float = 0.0
    #: Mean absolute error per labelled level, so a model that only works at the extremes
    #: is visible as one.
    by_level: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "candidate": self.candidate,
            "algorithm": self.algorithm,
            "n_utterances": self.n_utterances,
            "n_speakers": self.n_speakers,
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "pearson": self.pearson,
            "fold_mae_sd": self.fold_mae_sd,
            "baseline_mae": self.baseline_mae,
            "beats_mean": self.mae < self.baseline_mae,
            "exact_level": self.exact_level,
            "within_one_level": self.within_one_level,
            "by_level": self.by_level,
        }


def find_corpus(directory: Path | None = None) -> Path:
    for candidate in (directory,) if directory else corpus_directories():
        if candidate is not None and (candidate / "records.parquet").exists():
            return candidate
    looked = directory or corpus_directories()
    raise NoCorpus(
        f"{CORPUS_ID} was not found in "
        + " or ".join(str(path) for path in ([looked] if directory else looked))
        + ". Run the dataset pipeline to acquire it: python -m dataset.pipeline acquire "
        f"{CORPUS_ID}"
    )


def load(directory: Path | None = None) -> pd.DataFrame:
    """The corpus as one frame: speaker, level, and the thirteen cepstral means.

    Renamed on the way in, so that from here on the columns are called what the bedside
    extractor calls them. Getting that mapping wrong is the one mistake that would not
    show up as an error anywhere — the model would fit, score and serve, on permuted
    inputs — so it happens once, here.
    """
    found = find_corpus(directory)
    records = pd.read_parquet(found / "records.parquet")
    features = pd.read_parquet(found / "source_features.parquet")

    wanted = {f"{SOURCE_PREFIX}{name}": name for name in FEATURES}
    missing = [column for column in wanted if column not in features.columns]
    if missing:
        raise NoCorpus(
            f"{found} is missing {len(missing)} of the cepstral means this model is "
            f"fitted on: {', '.join(missing[:4])}"
        )

    merged = records[["assessment_id", SUBJECT, TARGET]].merge(
        features[["assessment_id", *wanted]], on="assessment_id", how="inner"
    )
    merged = merged.rename(columns=wanted)
    merged = merged.dropna(subset=[SUBJECT, TARGET, *FEATURES])
    if merged.empty:
        raise NoCorpus(f"{found} holds no utterance with both a level and a full feature row")
    return merged


def candidates(seed: int):
    """The three worth trying on 779 rows and 13 columns.

    Deliberately small. With this many rows a deeper model memorises speakers, which the
    grouped cross-validation would catch but only after wasting the time.
    """
    return (
        (
            "hgb",
            "HistGradientBoostingRegressor",
            HistGradientBoostingRegressor(
                max_iter=250,
                learning_rate=0.05,
                max_leaf_nodes=15,
                min_samples_leaf=15,
                l2_regularization=1.0,
                random_state=seed,
            ),
        ),
        (
            "random_forest",
            "RandomForestRegressor",
            RandomForestRegressor(
                n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=seed
            ),
        ),
        (
            "ridge",
            "RidgeCV (linear baseline)",
            Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("model", RidgeCV(alphas=np.logspace(-2, 3, 24))),
                ]
            ),
        ),
    )


def _score(
    code: str,
    algorithm: str,
    y: np.ndarray,
    predicted: np.ndarray,
    groups: np.ndarray,
    folds: np.ndarray,
) -> Result:
    levels = np.clip(np.rint(predicted), 1, len(inference.LEVELS))
    per_fold = [
        float(mean_absolute_error(y[folds == fold], predicted[folds == fold]))
        for fold in np.unique(folds)
    ]
    result = Result(
        candidate=code,
        algorithm=algorithm,
        n_utterances=len(y),
        n_speakers=len(np.unique(groups)),
        mae=round(float(mean_absolute_error(y, predicted)), 4),
        rmse=round(float(np.sqrt(np.mean((y - predicted) ** 2))), 4),
        r2=round(float(r2_score(y, predicted)), 4),
        pearson=round(float(np.corrcoef(y, predicted)[0, 1]), 4),
        fold_mae_sd=round(float(np.std(per_fold)), 4),
        baseline_mae=round(float(np.mean(np.abs(y - y.mean()))), 4),
        exact_level=round(float((levels == y).mean()), 4),
        within_one_level=round(float((np.abs(levels - y) <= 1).mean()), 4),
    )
    for level in sorted(set(y.tolist())):
        mask = y == level
        result.by_level[inference.LEVELS[int(level) - 1]] = round(
            float(mean_absolute_error(y[mask], predicted[mask])), 4
        )
    return result


def evaluate(frame: pd.DataFrame, *, seed: int = 0, folds: int = FOLDS) -> list[Result]:
    """Every candidate's error on speakers it never heard.

    `cross_val_predict` with a speaker-grouped splitter, so every row is predicted by a
    model fitted without that speaker. This is the only honest way to score 779 rows from
    194 people: holding out a single test split would leave forty speakers to judge three
    candidates on.
    """
    x = frame[list(FEATURES)].to_numpy(dtype=float)
    y = frame[TARGET].to_numpy(dtype=float)
    groups = frame[SUBJECT].to_numpy()
    splitter = GroupKFold(n_splits=min(folds, len(np.unique(groups))))
    # Which fold each row was predicted in, so the spread across folds can be reported
    # rather than only the pooled error.
    membership = np.zeros(len(y), dtype=int)
    for index, (_, held_out) in enumerate(splitter.split(x, y, groups)):
        membership[held_out] = index

    scored = []
    for code, algorithm, estimator in candidates(seed):
        predicted = cross_val_predict(
            clone(estimator), x, y, groups=groups, cv=splitter, n_jobs=None
        )
        scored.append(_score(code, algorithm, y, predicted, groups, membership))
    return scored


def train(
    db: Session,
    *,
    corpus: Path | None = None,
    seed: int = 0,
    folds: int = FOLDS,
    activate: bool = True,
    actor_id=None,
) -> ModelVersion:
    """Fit the voice model, register it, and make it the active one."""
    frame = load(corpus)
    scored = evaluate(frame, seed=seed, folds=folds)
    chosen = min(scored, key=lambda result: result.mae)
    if chosen.mae >= chosen.baseline_mae:
        # Registered anyway, inactive, because "this corpus carries no usable signal under
        # speaker-grouped validation" is a finding worth keeping rather than an error.
        activate = False

    estimator = next(
        estimator for code, _, estimator in candidates(seed) if code == chosen.candidate
    )
    x = frame[list(FEATURES)].to_numpy(dtype=float)
    y = frame[TARGET].to_numpy(dtype=float)
    estimator.fit(x, y)

    version = f"{inference.MODEL_NAME}-painspeech4-s{seed}"
    algorithm = f"{chosen.algorithm} on {len(FEATURES)} cepstral means"
    bundle = model_store.Bundle(
        version=version,
        algorithm=algorithm,
        point=estimator,
        # No interval models. A quantile pair fitted on 779 rows from 194 speakers would
        # be an interval with no coverage worth quoting; the cross-validated error is
        # reported instead and is what the interface shows.
        lower=None,
        upper=None,
        feature_names=FEATURES,
        observed_coverage=0.0,
        residual_sd=chosen.mae,
        dataset_version=CORPUS_ID,
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
        model_name=inference.MODEL_NAME,
        training_profile={
            "corpus": CORPUS_ID,
            "target": "four-level ordinal class, 1 to 4",
            "scale": list(inference.LEVELS),
            "validation": f"GroupKFold(speaker), {chosen.n_speakers} speakers",
            "candidates": [result.as_dict() for result in scored],
            "limitations": list(inference.LIMITATIONS),
        },
    )
    artifact = model_store.save(bundle)
    model_store.forget(version)

    row = db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if row is None:
        row = ModelVersion(version=version)
        db.add(row)
    row.model_name = inference.MODEL_NAME
    row.algorithm = algorithm[:80]
    row.dataset_version = CORPUS_ID
    row.feature_schema_version = schema.FEATURE_SCHEMA_VERSION
    row.n_train = chosen.n_utterances
    row.n_validation = 0
    row.n_test = 0
    row.mae = chosen.mae
    row.rmse = chosen.rmse
    row.r2 = chosen.r2
    row.pearson = chosen.pearson
    row.cv_folds = min(folds, chosen.n_speakers)
    # The cross-validated error is the only error this model has: every figure above
    # already comes from speakers it never heard, so there is no separate test split to
    # distinguish it from.
    row.cv_mae_mean = chosen.mae
    row.cv_mae_sd = chosen.fold_mae_sd
    row.residual_sd = chosen.rmse
    row.features = list(FEATURES)
    row.comparison = [result.as_dict() for result in scored]
    row.training_profile = bundle.training_profile
    row.artifact_name = artifact.name
    row.notes = (
        f"Trained on {chosen.n_utterances} utterances from {chosen.n_speakers} speakers in "
        f"{CORPUS_ID}, the one corpus of real pain-labelled human recordings this platform "
        f"can reach. Speaker-grouped cross-validation: {chosen.mae:.2f} levels of error "
        f"against {chosen.baseline_mae:.2f} for predicting the mean, "
        f"{chosen.within_one_level:.0%} within one level. Predicts that corpus's "
        "four-point scale and not a 0-10 score; no mapping between the two is published."
    )
    db.commit()

    if activate:
        model_store.activate(db, version)

    audit.record(
        db,
        event_type=audit.MODEL_TRAINED,
        actor_id=actor_id,
        resource="model",
        resource_id=version,
        meta={
            "model_name": inference.MODEL_NAME,
            "corpus": CORPUS_ID,
            "candidate": chosen.candidate,
            "mae": chosen.mae,
            "baseline_mae": chosen.baseline_mae,
            "speakers": chosen.n_speakers,
            "activated": activate,
        },
        ledger_payload={
            "version": version,
            "corpus": CORPUS_ID,
            "mae": chosen.mae,
            "features": list(FEATURES),
        },
    )
    return row


def main() -> None:
    import argparse

    from database.session import SessionLocal

    parser = argparse.ArgumentParser(description="Train the voice pain model.")
    parser.add_argument("--corpus", type=Path, default=None, help="corpus directory")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--folds", type=int, default=FOLDS)
    arguments = parser.parse_args()

    with SessionLocal() as db:
        row = train(
            db, corpus=arguments.corpus, seed=arguments.seed, folds=arguments.folds
        )
        print(f"model {row.version} trained on {row.dataset_version}")
        print(f"speaker-grouped cross-validation over {row.cv_folds} folds:")
        for entry in row.comparison:
            marker = "*" if entry["candidate"] == row.comparison[0]["candidate"] else " "
            print(
                f" {marker} {entry['candidate']:14} MAE {entry['mae']:.3f} levels  "
                f"R2 {entry['r2']:+.3f}  exact {entry['exact_level']:.1%}  "
                f"within one {entry['within_one_level']:.1%}  "
                f"(predicting the mean: {entry['baseline_mae']:.3f})"
            )
            for level, error in entry["by_level"].items():
                print(f"      {level:9} MAE {error:.3f}")
        print(f"  {row.notes}")


if __name__ == "__main__":
    main()
