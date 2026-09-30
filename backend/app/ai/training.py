"""Training and evaluation.

Three models are fitted on the same features: the point estimate and the 10th and 90th
conditional quantiles that form the reported interval. Fitting the quantiles is what lets
the platform show an interval without assuming a shape for the residuals.

The target is the patient's self-reported score. It is the reference the model is measured
against and it is never part of the feature matrix, which is why the training set is built
from ClinicalContext objects that have no field for it.

Reported metrics are measured, never assumed: MAE, RMSE, R-squared and Pearson correlation
on a held-out split, cross-validated MAE on the training portion, and the share of held-out
targets that actually fell inside their interval.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import explainability, features, model, uncertainty
from app.config import get_settings
from app.database.models import DatasetVersion, ModelVersion
from app.datasets import generate
from app.security import audit

ALGORITHM = "HistGradientBoostingRegressor (point estimate + 10th/90th quantiles)"
LOWER_QUANTILE = 0.1
UPPER_QUANTILE = 0.9

POINT_PARAMETERS = {
    "max_iter": 400,
    "learning_rate": 0.06,
    "min_samples_leaf": 20,
    "l2_regularization": 0.5,
    "early_stopping": True,
    "validation_fraction": 0.15,
    "n_iter_no_change": 25,
}


class NoDataset(Exception):
    """No dataset file is available to train on."""


@dataclass
class Metrics:
    n_train: int
    n_test: int
    mae: float
    rmse: float
    r2: float
    pearson: float
    cv_folds: int
    cv_mae_mean: float
    cv_mae_sd: float
    residual_sd: float
    interval_coverage: float


def latest_dataset(db: Session | None = None) -> Path:
    if db is not None:
        row = db.scalar(select(DatasetVersion).order_by(DatasetVersion.generated_at.desc()))
        if row is not None and Path(row.path).exists():
            return Path(row.path)
    candidates = sorted(get_settings().dataset_path.glob("*.jsonl"))
    if not candidates:
        raise NoDataset(
            "no dataset found; run python -m app.datasets.generate --rows 10000 --seed 42"
        )
    return candidates[-1]


def _fit_quantile(x_train, y_train, quantile: float):
    estimator = HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, random_state=0, **POINT_PARAMETERS
    )
    return estimator.fit(x_train, y_train)


def train(
    db: Session,
    *,
    dataset_path: Path | None = None,
    test_size: float = 0.2,
    seed: int = 0,
    cv_folds: int = 5,
    activate: bool = True,
    actor_id=None,
) -> ModelVersion:
    path = dataset_path or latest_dataset(db)
    contexts, targets, _ = generate.load(path)
    x = features.matrix(contexts)
    y = np.asarray(targets, dtype=float)

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=test_size, random_state=seed
    )

    point = HistGradientBoostingRegressor(random_state=seed, **POINT_PARAMETERS)
    point.fit(x_train, y_train)
    lower = _fit_quantile(x_train, y_train, LOWER_QUANTILE)
    upper = _fit_quantile(x_train, y_train, UPPER_QUANTILE)

    predicted = point.predict(x_test)
    residuals = y_test - predicted
    cv_scores = -cross_val_score(
        HistGradientBoostingRegressor(random_state=seed, **POINT_PARAMETERS),
        x_train,
        y_train,
        scoring="neg_mean_absolute_error",
        cv=KFold(n_splits=cv_folds, shuffle=True, random_state=seed),
    )

    metrics = Metrics(
        n_train=len(y_train),
        n_test=len(y_test),
        mae=round(float(mean_absolute_error(y_test, predicted)), 3),
        rmse=round(float(np.sqrt(mean_squared_error(y_test, predicted))), 3),
        r2=round(float(r2_score(y_test, predicted)), 3),
        pearson=round(float(pearsonr(y_test, predicted).statistic), 3),
        cv_folds=cv_folds,
        cv_mae_mean=round(float(cv_scores.mean()), 3),
        cv_mae_sd=round(float(cv_scores.std()), 3),
        residual_sd=round(float(residuals.std()), 3),
        interval_coverage=uncertainty.coverage(
            y_test, lower.predict(x_test), upper.predict(x_test)
        ),
    )

    dataset_version = path.stem
    version = f"pain-{dataset_version.replace('synthetic-', '')}-t{seed}"
    bundle = model.Bundle(
        version=version,
        algorithm=ALGORITHM,
        point=point,
        lower=lower,
        upper=upper,
        feature_names=features.NAMES,
        observed_coverage=metrics.interval_coverage,
        residual_sd=metrics.residual_sd,
        dataset_version=dataset_version,
    )
    artifact = model.save(bundle)
    model.forget(version)
    explainability.forget(version)

    row = db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if row is None:
        row = ModelVersion(version=version)
        db.add(row)
    row.algorithm = ALGORITHM
    row.dataset_version = dataset_version
    row.n_train = metrics.n_train
    row.n_test = metrics.n_test
    row.mae = metrics.mae
    row.rmse = metrics.rmse
    row.r2 = metrics.r2
    row.pearson = metrics.pearson
    row.cv_folds = metrics.cv_folds
    row.cv_mae_mean = metrics.cv_mae_mean
    row.cv_mae_sd = metrics.cv_mae_sd
    row.residual_sd = metrics.residual_sd
    row.features = list(features.NAMES)
    row.artifact_name = artifact.name
    row.notes = (
        f"Trained on synthetic data only. The 10-90 interval covered "
        f"{metrics.interval_coverage:.0%} of held-out self-reported scores."
    )
    db.commit()

    if activate:
        model.activate(db, version)

    audit.record(
        db,
        event_type=audit.MODEL_TRAINED,
        actor_id=actor_id,
        resource="model",
        resource_id=version,
        meta={
            "mae": metrics.mae,
            "rmse": metrics.rmse,
            "r2": metrics.r2,
            "dataset": dataset_version,
        },
        ledger_payload={
            "version": version,
            "dataset_version": dataset_version,
            "mae": metrics.mae,
            "rmse": metrics.rmse,
            "r2": metrics.r2,
            "features": list(features.NAMES),
        },
    )
    return row


def main() -> None:
    import argparse

    from app.database.database import SessionLocal

    parser = argparse.ArgumentParser(description="Train the pain estimation model.")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cv-folds", type=int, default=5)
    arguments = parser.parse_args()

    with SessionLocal() as db:
        row = train(
            db,
            dataset_path=arguments.dataset,
            test_size=arguments.test_size,
            seed=arguments.seed,
            cv_folds=arguments.cv_folds,
        )
        print(f"model {row.version} trained on {row.dataset_version}")
        print(f"  MAE  {row.mae}    RMSE {row.rmse}    R2 {row.r2}    Pearson r {row.pearson}")
        print(
            f"  cross-validated MAE {row.cv_mae_mean} (sd {row.cv_mae_sd}, {row.cv_folds} folds)"
        )
        print(f"  {row.notes}")


if __name__ == "__main__":
    main()
