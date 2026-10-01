import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai import explainability, features, model, uncertainty
from backend.ai import metrics as metrics_kb
from config import get_settings
from database.models import DatasetVersion, ModelVersion
from dataset.synthetic import generate
from knowledge import rules
from security import audit

LOWER_QUANTILE = 0.1
UPPER_QUANTILE = 0.9
CV_LABEL = "GroupKFold(patient)"
SHAP_SAMPLE = 2000

SHAP_SAMPLE_FOREST = 500

POINT_PARAMETERS = {
    "max_iter": 400,
    "learning_rate": 0.06,
    "min_samples_leaf": 20,
    "l2_regularization": 0.5,
    "early_stopping": True,
    "validation_fraction": 0.15,
    "n_iter_no_change": 25,
}
REGULARISED_PARAMETERS = {
    "max_iter": 600,
    "learning_rate": 0.04,
    "max_depth": 4,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 60,
    "l2_regularization": 2.0,
    "early_stopping": True,
    "validation_fraction": 0.15,
    "n_iter_no_change": 30,
}


class NoDataset(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    code: str
    algorithm: str

    explainable: bool
    build: object

    def estimator(self):
        return self.build()


def candidates(seed: int) -> tuple[Candidate, ...]:
    return (
        Candidate(
            "hgb",
            "HistGradientBoostingRegressor",
            True,
            lambda: HistGradientBoostingRegressor(random_state=seed, **POINT_PARAMETERS),
        ),
        Candidate(
            "hgb_regularised",
            "HistGradientBoostingRegressor (shallow, regularised)",
            True,
            lambda: HistGradientBoostingRegressor(random_state=seed, **REGULARISED_PARAMETERS),
        ),
        Candidate(
            "random_forest",
            "RandomForestRegressor with median imputation",
            True,
            lambda: Pipeline(
                [
                    # keep_empty_features: a column that is constant-NaN in the
                    # training split would otherwise be dropped, and the SHAP values
                    # would then line up against the wrong feature names.
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    (
                        "model",
                        RandomForestRegressor(
                            n_estimators=300,
                            min_samples_leaf=5,
                            n_jobs=-1,
                            random_state=seed,
                        ),
                    ),
                ]
            ),
        ),
        Candidate(
            "ridge",
            "Ridge regression (linear baseline)",
            False,
            lambda: Pipeline(
                [
                    # keep_empty_features: a column that is constant-NaN in the
                    # training split would otherwise be dropped, and the SHAP values
                    # would then line up against the wrong feature names.
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    ("scaler", StandardScaler()),
                    ("model", Ridge(alpha=1.0, random_state=seed)),
                ]
            ),
        ),
        Candidate(
            "mlp",
            "MLPRegressor (neural baseline)",
            False,
            lambda: Pipeline(
                [
                    # keep_empty_features: a column that is constant-NaN in the
                    # training split would otherwise be dropped, and the SHAP values
                    # would then line up against the wrong feature names.
                    ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        MLPRegressor(
                            hidden_layer_sizes=(64, 32),
                            early_stopping=True,
                            max_iter=300,
                            random_state=seed,
                        ),
                    ),
                ]
            ),
        ),
    )


@dataclass
class Metrics:
    n_train: int
    n_validation: int
    n_test: int
    mae: float
    rmse: float
    r2: float
    pearson: float
    f1_band: float
    inference_ms: float
    cv_folds: int
    cv_mae_mean: float
    cv_mae_sd: float
    residual_sd: float
    interval_coverage: float


def _bands(values) -> list[str]:
    return [rules.band(float(v))[0] for v in values]


def _scores(y_true, y_pred) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 3),
        "r2": round(float(r2_score(y_true, y_pred)), 3),
        "f1_band": round(float(f1_score(_bands(y_true), _bands(y_pred), average="macro")), 3),
    }


def _inference_ms_per_1000(estimator, x: np.ndarray) -> float:
    started = time.perf_counter()
    estimator.predict(x)
    elapsed = time.perf_counter() - started
    return round(elapsed * 1000 / max(len(x), 1) * 1000, 3)


def _compare(seed: int, x_train, y_train, x_validation, y_validation) -> list[dict]:
    rows = []
    for candidate in candidates(seed):
        estimator = candidate.estimator()
        started = time.perf_counter()
        estimator.fit(x_train, y_train)
        fit_seconds = round(time.perf_counter() - started, 2)
        predicted = estimator.predict(x_validation)
        rows.append(
            {
                "candidate": candidate.code,
                "algorithm": candidate.algorithm,
                "explainable": candidate.explainable,
                "selectable": candidate.explainable,
                "selected": False,
                "cv": CV_LABEL,
                "fit_seconds": fit_seconds,
                "inference_ms_per_1000": _inference_ms_per_1000(estimator, x_validation),
                "_estimator": estimator,
                **_scores(y_validation, predicted),
            }
        )
    return rows


def _profile(x_train: np.ndarray, predictions: np.ndarray) -> dict:
    profile = {"features": {}, "prediction": {}}
    for index, name in enumerate(features.NAMES):
        column = x_train[:, index]
        present = column[~np.isnan(column)]
        summary = {
            "missing_rate": round(1 - len(present) / len(column), 4) if len(column) else 1.0
        }
        if len(present):
            p05, p50, p95 = np.percentile(present, (5, 50, 95))
            summary.update(
                mean=round(float(present.mean()), 4),
                sd=round(float(present.std()), 4),
                p05=round(float(p05), 4),
                p50=round(float(p50), 4),
                p95=round(float(p95), 4),
            )
        else:
            summary.update(mean=None, sd=None, p05=None, p50=None, p95=None)
        profile["features"][name] = summary
    bands = _bands(predictions)
    total = len(bands) or 1
    profile["prediction"] = {
        "mean": round(float(predictions.mean()), 4) if len(predictions) else None,
        "sd": round(float(predictions.std()), 4) if len(predictions) else None,
        "histogram": {
            code: round(bands.count(code) / total, 4) for _, code, _ in rules.PAIN_BANDS
        },
    }
    return profile


def _subgroups(labels: list[str], y_true, y_pred) -> dict[str, dict]:
    out = {}
    for code in sorted(set(labels)):
        mask = np.array([label == code for label in labels])
        out[code] = {
            "n": int(mask.sum()),
            "mae": round(float(mean_absolute_error(y_true[mask], y_pred[mask])), 3),
        }
    return out


def _feature_importance(point, x_validation: np.ndarray, seed: int) -> list[dict]:
    size = SHAP_SAMPLE_FOREST if isinstance(point, Pipeline) else SHAP_SAMPLE
    rng = np.random.default_rng(seed)
    if len(x_validation) > size:
        sample = x_validation[rng.choice(len(x_validation), size=size, replace=False)]
    else:
        sample = x_validation
    importance = explainability.mean_absolute_shap(point, sample)
    ranked = sorted(zip(features.NAMES, importance), key=lambda pair: pair[1], reverse=True)
    return [
        {"feature": name, "label": features.LABELS[name], "importance": round(float(value), 5)}
        for name, value in ranked
    ]


def _fit_quantile(x_train, y_train, quantile: float, seed: int):
    estimator = HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, random_state=seed, **POINT_PARAMETERS
    )
    return estimator.fit(x_train, y_train)


def _manifest_time(directory: Path) -> float:
    manifest = directory / "provenance" / "manifest.json"
    if manifest.exists():
        try:
            stamp = json.loads(manifest.read_text(encoding="utf-8")).get("generated_at")
            if stamp:
                from datetime import datetime

                return datetime.fromisoformat(stamp).timestamp()
        except (ValueError, json.JSONDecodeError):
            pass
    return directory.stat().st_mtime


def latest_dataset(db: Session | None = None) -> Path:
    if db is not None:
        row = db.scalar(select(DatasetVersion).order_by(DatasetVersion.generated_at.desc()))
        if row is not None and Path(row.path).exists():
            return Path(row.path)
    root = get_settings().dataset_path
    candidates_found = [
        (_manifest_time(entry), entry)
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "integrated").is_dir()
    ] + [(entry.stat().st_mtime, entry) for entry in root.glob("*.jsonl")]
    if not candidates_found:
        raise NoDataset(
            "no dataset found; run python scripts/generate_dataset.py --patients 5000 "
            "--assessments 100000 --seed 42"
        )
    return max(candidates_found, key=lambda pair: pair[0])[1]


def train(
    db: Session,
    *,
    dataset_path: Path | None = None,
    test_size: float | None = None,
    seed: int = 0,
    cv_folds: int = 5,
    activate: bool = True,
    actor_id=None,
) -> ModelVersion:
    path = dataset_path or latest_dataset(db)
    dataset = generate.load(path)
    if not dataset.targets:
        raise NoDataset(f"{path} holds no assessments")
    x = features.matrix(dataset.contexts)
    y = np.asarray(dataset.targets, dtype=float)
    split = np.asarray(dataset.splits)
    groups = np.asarray(dataset.patient_ids)
    train_mask, validation_mask, test_mask = (split == s for s in generate.SPLITS)
    if not (train_mask.any() and validation_mask.any() and test_mask.any()):
        raise NoDataset(f"{path} does not carry all three splits")
    x_train, y_train = x[train_mask], y[train_mask]
    x_validation, y_validation = x[validation_mask], y[validation_mask]
    x_test, y_test = x[test_mask], y[test_mask]

    comparison = _compare(seed, x_train, y_train, x_validation, y_validation)
    selectable = [row for row in comparison if row["selectable"]]
    chosen = min(selectable, key=lambda row: row["mae"])
    chosen["selected"] = True
    point = chosen.pop("_estimator")
    for row in comparison:
        row.pop("_estimator", None)
    candidate = next(c for c in candidates(seed) if c.code == chosen["candidate"])

    folds = min(cv_folds, len(np.unique(groups[train_mask])))
    cv_scores = -cross_val_score(
        clone(point),
        x_train,
        y_train,
        groups=groups[train_mask],
        scoring="neg_mean_absolute_error",
        cv=GroupKFold(n_splits=folds),
    )

    lower = _fit_quantile(x_train, y_train, LOWER_QUANTILE, seed)
    upper = _fit_quantile(x_train, y_train, UPPER_QUANTILE, seed)

    predicted = point.predict(x_test)
    residuals = y_test - predicted
    test_scores = _scores(y_test, predicted)
    metrics = Metrics(
        n_train=int(train_mask.sum()),
        n_validation=int(validation_mask.sum()),
        n_test=int(test_mask.sum()),
        mae=test_scores["mae"],
        rmse=test_scores["rmse"],
        r2=test_scores["r2"],
        pearson=round(float(pearsonr(y_test, predicted).statistic), 3),
        f1_band=test_scores["f1_band"],
        inference_ms=_inference_ms_per_1000(point, x_test) / 1000,
        cv_folds=folds,
        cv_mae_mean=round(float(cv_scores.mean()), 3),
        cv_mae_sd=round(float(cv_scores.std()), 3),
        residual_sd=round(float(residuals.std()), 3),
        interval_coverage=uncertainty.coverage(
            y_test, lower.predict(x_test), upper.predict(x_test)
        ),
    )
    test_scenarios = [s for s, keep in zip(dataset.scenarios, test_mask) if keep]
    test_archetypes = [a for a, keep in zip(dataset.archetypes, test_mask) if keep]
    test_profiles = [p for p, keep in zip(dataset.profiles, test_mask) if keep]
    test_scales = [s for s, keep in zip(dataset.reference_scales, test_mask) if keep]
    classification = metrics_kb.evaluate(
        y_test,
        predicted,
        profiles=test_profiles,
        reference_scales=test_scales,
        scenarios=test_scenarios,
    ).to_dict()
    profile = _profile(x_train, point.predict(x_train))
    profile["subgroups"] = {
        "scenario": _subgroups(test_scenarios, y_test, predicted),
        "archetype": _subgroups(test_archetypes, y_test, predicted),
    }
    profile["interval_coverage"] = metrics.interval_coverage
    importance = _feature_importance(point, x_validation, seed)

    dataset_version = dataset.version
    version = f"{model.MODEL_NAME}-{dataset_version.removeprefix('synthetic-')}-t{seed}"
    algorithm = f"{candidate.algorithm} (point estimate + 10th/90th quantiles)"
    bundle = model.Bundle(
        version=version,
        algorithm=algorithm,
        point=point,
        lower=lower,
        upper=upper,
        feature_names=features.NAMES,
        observed_coverage=metrics.interval_coverage,
        residual_sd=metrics.residual_sd,
        dataset_version=dataset_version,
        feature_schema_version=features.FEATURE_SCHEMA_VERSION,
        model_name=model.MODEL_NAME,
        training_profile=profile,
    )
    artifact = model.save(bundle)
    model.forget(version)
    explainability.forget(version)

    row = db.scalar(select(ModelVersion).where(ModelVersion.version == version))
    if row is None:
        row = ModelVersion(version=version)
        db.add(row)
    row.model_name = model.MODEL_NAME
    row.algorithm = algorithm[:80]
    row.dataset_version = dataset_version
    row.feature_schema_version = features.FEATURE_SCHEMA_VERSION
    row.n_train = metrics.n_train
    row.n_validation = metrics.n_validation
    row.n_test = metrics.n_test
    row.mae = metrics.mae
    row.rmse = metrics.rmse
    row.r2 = metrics.r2
    row.pearson = metrics.pearson
    row.f1_band = metrics.f1_band
    row.inference_ms = metrics.inference_ms
    row.cv_folds = metrics.cv_folds
    row.cv_mae_mean = metrics.cv_mae_mean
    row.cv_mae_sd = metrics.cv_mae_sd
    row.residual_sd = metrics.residual_sd
    row.features = list(features.NAMES)
    row.feature_importance = importance
    row.comparison = comparison
    row.training_profile = profile
    row.classification = classification
    row.artifact_name = artifact.name
    moderate = next(
        (
            entry
            for entry in classification["under_estimation"]
            if entry["threshold"] == metrics_kb.UNDER_ESTIMATION_THRESHOLDS[0]
        ),
        None,
    )
    row.notes = (
        f"Trained on synthetic data only. Selected {candidate.code} by validation MAE "
        f"among the explainable candidates. The 10-90 interval covered "
        f"{metrics.interval_coverage:.0%} of test-split reference scores. "
        + (
            f"Of the test cases whose reference was {moderate['threshold']:.0f} or more, "
            f"{moderate['miss_rate']:.1%} were estimated below it."
            if moderate
            else ""
        )
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
            "f1_band": metrics.f1_band,
            "candidate": candidate.code,
            "dataset": dataset_version,
        },
        ledger_payload={
            "version": version,
            "dataset_version": dataset_version,
            "candidate": candidate.code,
            "mae": metrics.mae,
            "rmse": metrics.rmse,
            "r2": metrics.r2,
            "f1_band": metrics.f1_band,
            "features": list(features.NAMES),
        },
    )
    return row


def main() -> None:
    import argparse

    from database.session import SessionLocal

    parser = argparse.ArgumentParser(description="Train the pain estimation model.")
    parser.add_argument("--dataset", type=Path, default=None, help="dataset directory")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cv-folds", type=int, default=5)
    arguments = parser.parse_args()

    with SessionLocal() as db:
        row = train(
            db,
            dataset_path=arguments.dataset,
            seed=arguments.seed,
            cv_folds=arguments.cv_folds,
        )
        print(f"model {row.version} trained on {row.dataset_version}")
        print("candidates (validation split):")
        for entry in row.comparison:
            marker = "*" if entry["selected"] else " "
            print(
                f" {marker} {entry['candidate']:16} MAE {entry['mae']:.3f}  RMSE {entry['rmse']:.3f}  "
                f"R2 {entry['r2']:.3f}  F1 band {entry['f1_band']:.3f}  "
                f"fit {entry['fit_seconds']}s  {entry['inference_ms_per_1000']} ms/1000 rows"
            )
        print(
            f"test split: MAE {row.mae}  RMSE {row.rmse}  R2 {row.r2}  Pearson r {row.pearson}  "
            f"F1 band {row.f1_band}"
        )
        print(
            f"  cross-validated MAE {row.cv_mae_mean} (sd {row.cv_mae_sd}, {row.cv_folds} "
            f"patient-grouped folds)"
        )
        report = row.classification
        print(
            f"  bands: macro precision {report['macro_precision']}  recall "
            f"{report['macro_recall']}  F1 {report['macro_f1']}  exact "
            f"{report['band_accuracy']:.1%}  within one band {report['within_one_band']:.1%}"
        )
        for entry in report["under_estimation"]:
            print(
                f"  reference >= {entry['threshold']:.0f}: {entry['missed']} of "
                f"{entry['actual']} estimated below it ({entry['miss_rate']:.1%}), "
                f"mean shortfall {entry['mean_shortfall']}"
            )
        print("  worst profiles by MAE:")
        for entry in report["by_profile"][:4]:
            miss = entry["moderate_miss_rate"]
            print(
                f"    {entry['key']:24} n={entry['n']:6} MAE {entry['mae']:.3f}  bias "
                f"{entry['bias']:+.3f}  moderate missed "
                + ("n/a" if miss is None else f"{miss:.1%}")
            )
        print(f"  {row.notes}")


if __name__ == "__main__":
    main()
