"""Fitting a baseline model to an acquired external dataset.

This is not `app.ai.training`. That module trains the estimator the platform uses at the
bedside, on a feature schema derived from a clinician's examination. This one fits a
regressor to whatever numeric columns an external publisher happened to ship, predicting
that publisher's own rating column. The two share no features and the results are not
comparable; the model recorded here is `is_active=False` and is never offered for a
clinical estimate.

What it is good for is answering a question a dashboard cannot otherwise answer: is there
any signal in this dataset at all? A dataset whose cross-validated error is no better
than predicting the mean is one nobody should spend more time on, and that is worth
knowing before someone builds a mapping for it.

Splitting is grouped by subject throughout. A random split over rows from the same person
leaks: physiological rows from one participant are near-duplicates of each other, and a
model that has seen some of them scores well on the rest without having learned anything
transferable. Every figure here comes from subjects the model never saw.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

ALGORITHM = "RandomForestRegressor"
MODEL_NAME_PREFIX = "external-baseline"
TEST_SHARE = 0.25
DEFAULT_FOLDS = 5
#: More trees change the third decimal place and multiply the runtime of a job that runs
#: unattended; this is a baseline, not a tuned model.
TREES = 200
MAX_FEATURES = 120


class NotTrainable(RuntimeError):
    """The dataset did not hold what the suitability gate said it would."""


@dataclass
class Result:
    algorithm: str = ALGORITHM
    features: list[str] = field(default_factory=list)
    target: str = ""
    subject_column: str = ""
    n_subjects: int = 0
    n_train: int = 0
    n_test: int = 0
    mae: float = 0.0
    rmse: float = 0.0
    r2: float = 0.0
    pearson: float = 0.0
    cv_folds: int = 0
    cv_mae_mean: float = 0.0
    cv_mae_sd: float = 0.0
    residual_sd: float = 0.0
    baseline_mae: float = 0.0
    feature_importance: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "target": self.target,
            "subject_column": self.subject_column,
            "n_subjects": self.n_subjects,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "pearson": self.pearson,
            "cv_folds": self.cv_folds,
            "cv_mae_mean": self.cv_mae_mean,
            "cv_mae_sd": self.cv_mae_sd,
            "residual_sd": self.residual_sd,
            "mean_baseline_mae": self.baseline_mae,
            "beats_mean_baseline": self.mae < self.baseline_mae,
            "features": self.features,
            "feature_importance": self.feature_importance,
        }


def _matrix(
    frame: pd.DataFrame, target: str, subject: str
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, list[str]]:
    columns = [
        str(column)
        for column in frame.columns
        if column not in (target, subject) and pd.api.types.is_numeric_dtype(frame[column])
    ][:MAX_FEATURES]
    if not columns:
        raise NotTrainable("no numeric feature column remained after removing target and subject")

    usable = frame[[*columns, target, subject]].copy()
    usable[target] = pd.to_numeric(usable[target], errors="coerce")
    usable = usable.dropna(subset=[target, subject])
    if usable.empty:
        raise NotTrainable("every row was missing either the rating or the subject identifier")

    # A column left entirely blank after the row filter carries nothing; the rest are
    # filled with the column median so a single missing cell does not discard a row.
    features = usable[columns]
    features = features.loc[:, features.notna().any()]
    if features.empty:
        raise NotTrainable("every feature column was blank")
    features = features.fillna(features.median(numeric_only=True)).fillna(0.0)

    return (
        features,
        usable[target].to_numpy(dtype=float),
        usable[subject].astype(str).to_numpy(),
        list(features.columns),
    )


def train(frame: pd.DataFrame, *, target: str, subject: str, seed: int = 0) -> tuple[Result, RandomForestRegressor]:
    features, y, groups, names = _matrix(frame, target, subject)
    distinct = len(set(groups))
    if distinct < 2:
        raise NotTrainable(f"the dataset covers {distinct} subject(s); a grouped split needs at least 2")

    x = features.to_numpy(dtype=float)
    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SHARE, random_state=seed)
    train_index, test_index = next(splitter.split(x, y, groups))
    if not len(train_index) or not len(test_index):
        raise NotTrainable("the grouped split left one side empty")

    model = RandomForestRegressor(
        n_estimators=TREES, random_state=seed, n_jobs=-1, min_samples_leaf=2
    )
    model.fit(x[train_index], y[train_index])
    predicted = model.predict(x[test_index])
    actual = y[test_index]

    residuals = actual - predicted
    result = Result(
        features=names,
        target=target,
        subject_column=subject,
        n_subjects=distinct,
        n_train=len(train_index),
        n_test=len(test_index),
        mae=round(float(mean_absolute_error(actual, predicted)), 4),
        rmse=round(float(np.sqrt(np.mean(residuals**2))), 4),
        r2=round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else 0.0,
        pearson=_pearson(actual, predicted),
        residual_sd=round(float(np.std(residuals)), 4),
        # Predicting the training mean for every row. A model that cannot beat this has
        # found nothing, and the comparison belongs next to the score rather than in a
        # reader's head.
        baseline_mae=round(
            float(mean_absolute_error(actual, np.full_like(actual, y[train_index].mean()))), 4
        ),
        feature_importance=[
            {"feature": name, "importance": round(float(weight), 5)}
            for name, weight in sorted(
                zip(names, model.feature_importances_), key=lambda pair: -pair[1]
            )[:25]
        ],
    )
    _cross_validate(result, x, y, groups, seed)
    return result, model


def _pearson(actual: np.ndarray, predicted: np.ndarray) -> float:
    if len(actual) < 2 or np.std(actual) == 0 or np.std(predicted) == 0:
        return 0.0
    return round(float(np.corrcoef(actual, predicted)[0, 1]), 4)


def _cross_validate(result: Result, x, y, groups, seed: int) -> None:
    folds = min(DEFAULT_FOLDS, len(set(groups)))
    if folds < 2:
        return
    errors = []
    for train_index, test_index in GroupKFold(n_splits=folds).split(x, y, groups):
        model = RandomForestRegressor(
            n_estimators=TREES, random_state=seed, n_jobs=-1, min_samples_leaf=2
        )
        model.fit(x[train_index], y[train_index])
        errors.append(float(mean_absolute_error(y[test_index], model.predict(x[test_index]))))
    result.cv_folds = folds
    result.cv_mae_mean = round(float(np.mean(errors)), 4)
    result.cv_mae_sd = round(float(np.std(errors)), 4)


def persist(model: RandomForestRegressor, destination: Path) -> Path:
    import joblib

    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, destination)
    return destination


def version_label(external_id: str, acquired_version: str) -> str:
    from backend.sync.storage import slug

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{MODEL_NAME_PREFIX}-{slug(external_id, limit=40)}-{slug(acquired_version, limit=20)}-{stamp}-{uuid.uuid4().hex[:6]}"
