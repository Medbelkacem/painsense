"""Baseline models for the simulated signal dataset.

This is not `app.ai.training`. That module trains the estimator the platform uses at the
bedside, on features derived from a clinician's examination. This one fits ordinary
classifiers and regressors to the session-level feature table written by
`app.datasets.signals`, and exists to answer three questions before anyone builds anything
on top of it:

1. Is the scenario recoverable at all, or did the generator produce five indistinguishable
   clouds? A model that cannot beat the majority class means the simulation has no
   structure worth learning.
2. Is it recoverable *too* easily? A five-class accuracy near 1.0 means the confounders are
   not confounding anything, and a model tuned against it will fall over on real data.
3. Which channels carry it? If the whole result rests on the facial score, the system does
   not work on a sedated, intubated or turned-away patient — which is most of the patients
   who cannot tell you they are in pain.

Question 3 is why this module runs ablations rather than reporting one number. Splitting is
by patient throughout, taken from the `split` column the generator already assigned, and
model selection uses grouped cross-validation over the training patients only, so the test
patients are scored once by a model that was never chosen with reference to them.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

BASELINE_VERSION = "1"

WARNING = (
    "Fitted on SIMULATED data. Every figure below describes a numerical model of "
    "physiology, not a population. None of it is evidence that anything works on a patient."
)

SEED = 42
FOLDS = 5
TREES = 400

CLASSIFICATION = "classification"
REGRESSION = "regression"

# Columns that identify a row or state its answer. None may ever be a feature: `scenario`
# and `superimposed_state` are labels for one task and would be the answer to another, and
# `split` is an artefact of how the data was dealt out.
NON_FEATURES = (
    "patient_id",
    "session_id",
    "scenario",
    "pain_level",
    # Derived from pain_level in `prepare`, so it has to be excluded by name as well:
    # left in, it is the answer to one task and most of the answer to the other three.
    "pain_present",
    "superimposed_state",
    "split",
    "synthetic",
)

# Feature groups, by column prefix. The ablations below are built from these, so the
# question "what happens without the face" is answered by deleting a group rather than by
# naming thirty columns.
GROUPS = {
    "face": ("pspi_", "face_available"),
    "voice": ("voice_",),
    "movement": ("accel_",),
    "cardiac": ("hr_", "rmssd_"),
    "electrodermal": ("eda_",),
    "respiratory": ("resp_",),
    "thermal": ("temp_",),
    "baseline": ("baseline_",),
    "quality": ("missing_share", "session_seconds"),
}

# What a model is allowed to see. Each is a deployment that really happens.
ABLATIONS = {
    "all": None,
    # The wearable case: a wrist sensor and no camera. This is the ICU at night, the
    # patient facing away, the mask, the dressing over half the face.
    "no_face": ("face",),
    # Wrist only: no camera, no microphone, no accelerometer channel worth the name.
    "autonomic_only": ("face", "voice", "movement"),
    # What a naive model reaches for first. If this scores as well as the rest, the
    # confounders are not doing their job.
    "arousal_only": ("face", "voice", "movement", "respiratory", "thermal"),
}


class BoundedRegressor(BaseEstimator, RegressorMixin):
    """A regressor held to the range its target actually has.

    An unconstrained regressor fitted on a 0-10 scale will predict -0.6 for a comfortable
    patient and 10.9 for an agonised one, because nothing in a squared loss knows the scale
    is bounded. Those are not conservative errors to be tidied up downstream: they are
    values no instrument can produce, and anything reading the output has to special-case
    them. Clipping belongs in the model, where it is fitted, saved and scored with
    everything else, rather than in whatever happens to call it.
    """

    def __init__(self, estimator=None, low: float = 0.0, high: float = 10.0):
        self.estimator = estimator
        self.low = low
        self.high = high

    def fit(self, x, y):
        self.estimator_ = clone(self.estimator).fit(x, y)
        return self

    def predict(self, x):
        return np.clip(self.estimator_.predict(x), self.low, self.high)


@dataclass(frozen=True)
class Task:
    code: str
    kind: str
    target: str
    # A filter on the session table, where the task only applies to some sessions.
    subset: str | None
    primary: str
    note: str
    bounds: tuple[float, float] | None = None


TASKS = (
    Task(
        code="scenario",
        kind=CLASSIFICATION,
        target="scenario",
        subset=None,
        primary="macro_f1",
        note="Which of the five states this session was. The confounder question directly.",
    ),
    Task(
        code="pain_present",
        kind=CLASSIFICATION,
        target="pain_present",
        subset=None,
        primary="macro_f1",
        note=(
            "Whether there was any pain at all, including pain hiding inside a fever or an "
            "exertion session. The screening question a ward would actually ask."
        ),
    ),
    Task(
        code="pain_level",
        kind=REGRESSION,
        target="pain_level",
        subset=None,
        primary="mae",
        bounds=(0.0, 10.0),
        note="Pain 0-10 over every session, scoring zero where there was none.",
    ),
    Task(
        code="pain_level_given_pain",
        kind=REGRESSION,
        target="pain_level",
        subset="pain",
        primary="mae",
        bounds=(1.0, 10.0),
        note=(
            "Pain 1-10 among sessions that had some. Harder than the above, because the "
            "easy half of the problem - telling pain from no pain - has been removed."
        ),
    ),
)


def _encoder() -> list:
    """Median imputation with a missing indicator, then z-scoring.

    The same encoding `dataset/pipeline/encode.py` documents, and fitted inside the
    cross-validation fold rather than over the whole table, so the median and the standard
    deviation never carry information from the rows being scored.

    The indicator matters more than the imputation here. A missing facial score is not a
    neutral value to be filled in; it means the camera lost the patient, and whether that
    correlates with anything is a question the model should be allowed to ask.
    """
    return [
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
    ]


def candidates(
    kind: str, seed: int, bounds: tuple[float, float] | None = None
) -> dict[str, Pipeline]:
    """One trivial model, one linear, two nonlinear.

    The trivial model is not padding. A score reported without it is uninterpretable: an
    MAE of 1.8 on a 0-10 scale sounds respectable until you learn that predicting the
    training mean gets 2.6.
    """
    if kind == CLASSIFICATION:
        return {
            "majority": Pipeline([*_encoder(), ("model", DummyClassifier(strategy="prior"))]),
            "logistic": Pipeline(
                [
                    *_encoder(),
                    ("model", LogisticRegression(max_iter=2000, C=1.0, random_state=seed)),
                ]
            ),
            "forest": Pipeline(
                [
                    *_encoder(),
                    (
                        "model",
                        RandomForestClassifier(
                            n_estimators=TREES,
                            min_samples_leaf=2,
                            random_state=seed,
                            n_jobs=-1,
                        ),
                    ),
                ]
            ),
            "boosting": Pipeline(
                [
                    *_encoder(),
                    (
                        "model",
                        HistGradientBoostingClassifier(
                            max_iter=300,
                            learning_rate=0.06,
                            min_samples_leaf=10,
                            l2_regularization=1.0,
                            random_state=seed,
                        ),
                    ),
                ]
            ),
        }
    def bounded(estimator):
        if bounds is None:
            return estimator
        return BoundedRegressor(estimator=estimator, low=bounds[0], high=bounds[1])

    return {
        "mean": Pipeline([*_encoder(), ("model", bounded(DummyRegressor(strategy="mean")))]),
        "ridge": Pipeline([*_encoder(), ("model", bounded(Ridge(alpha=2.0)))]),
        "forest": Pipeline(
            [
                *_encoder(),
                (
                    "model",
                    bounded(
                        RandomForestRegressor(
                            n_estimators=TREES,
                            min_samples_leaf=2,
                            random_state=seed,
                            n_jobs=-1,
                        )
                    ),
                ),
            ]
        ),
        "boosting": Pipeline(
            [
                *_encoder(),
                (
                    "model",
                    bounded(
                        HistGradientBoostingRegressor(
                            max_iter=300,
                            learning_rate=0.06,
                            min_samples_leaf=10,
                            l2_regularization=1.0,
                            random_state=seed,
                        )
                    ),
                ),
            ]
        ),
    }


def feature_columns(frame: pd.DataFrame, drop_groups: tuple[str, ...] | None) -> list[str]:
    """Numeric columns a model may see, minus whichever groups the ablation removes."""
    dropped = tuple(
        prefix for group in (drop_groups or ()) for prefix in GROUPS[group]
    )
    columns = []
    for name in frame.columns:
        if name in NON_FEATURES or not pd.api.types.is_numeric_dtype(frame[name]):
            continue
        if any(name.startswith(prefix) for prefix in dropped):
            continue
        columns.append(name)
    return columns


def _constant(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    """Columns with one distinct value carry nothing and muddle the coefficients."""
    return [name for name in columns if frame[name].nunique(dropna=True) <= 1]


def prepare(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["pain_present"] = (frame["pain_level"] > 0).astype(int)
    if "face_available" in frame.columns:
        frame["face_available"] = frame["face_available"].astype(float)

    train = set(frame.loc[frame["split"] == "train", "patient_id"])
    test = set(frame.loc[frame["split"] == "test", "patient_id"])
    both = sorted(train & test)
    if both:
        raise AssertionError(f"patients in both splits: {both}")
    return frame


def _classification_scores(actual, predicted, probabilities, labels) -> dict:
    scores = {
        "accuracy": round(float(accuracy_score(actual, predicted)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(actual, predicted)), 4),
        "macro_f1": round(float(f1_score(actual, predicted, average="macro")), 4),
    }
    if len(labels) == 2 and probabilities is not None:
        scores["roc_auc"] = round(float(roc_auc_score(actual, probabilities[:, 1])), 4)
    return scores


def _regression_scores(actual, predicted) -> dict:
    residuals = np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float)
    scores = {
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "rmse": round(float(np.sqrt(np.mean(residuals**2))), 4),
        "r2": round(float(r2_score(actual, predicted)), 4) if len(actual) > 1 else 0.0,
    }
    varies = np.unique(actual).size > 1 and np.unique(np.round(predicted, 10)).size > 1
    if len(actual) > 2 and varies:
        scores["spearman"] = round(float(spearmanr(actual, predicted).statistic), 4)
    else:
        scores["spearman"] = float("nan")
    return scores


def cross_validate(pipeline: Pipeline, x, y, groups, kind: str, primary: str) -> dict:
    """Grouped cross-validation over the training patients.

    Reported as a mean and a spread, because with a few dozen patients the spread is the
    more honest figure: a fold mean of 0.80 that ranges from 0.62 to 0.94 is not a model
    anyone should quote to three decimal places.
    """
    folds = min(FOLDS, len(set(groups)))
    if folds < 2:
        return {}
    scores = []
    for train_index, test_index in GroupKFold(n_splits=folds).split(x, y, groups):
        fitted = pipeline.fit(x[train_index], y[train_index])
        predicted = fitted.predict(x[test_index])
        if kind == CLASSIFICATION:
            scores.append(
                _classification_scores(y[test_index], predicted, None, sorted(set(y)))[primary]
            )
        else:
            scores.append(_regression_scores(y[test_index], predicted)[primary])
    return {
        "folds": folds,
        "metric": primary,
        "mean": round(float(np.mean(scores)), 4),
        "sd": round(float(np.std(scores)), 4),
        "min": round(float(np.min(scores)), 4),
        "max": round(float(np.max(scores)), 4),
    }


def importances(
    pipeline: Pipeline,
    x,
    y,
    names: list[str],
    kind: str,
    seed: int,
    limit: int = 12,
) -> list[dict]:
    """What the fitted model actually used, by permutation on the test split.

    Permutation rather than impurity or coefficients, because the four candidate models do
    not all offer the same native measure - a boosted ensemble offers none - and a number
    that changes meaning between tasks is worse than no number. This one has one meaning
    everywhere: how much worse the model scores when that column is shuffled.

    The caveat is correlation. `hr_delta_mean` and `hr_delta_less_fever` carry much of the
    same information, so shuffling either alone costs little and both look unimportant.
    Read the groups, not the individual rows.
    """
    scoring = "f1_macro" if kind == CLASSIFICATION else "neg_mean_absolute_error"
    result = permutation_importance(
        pipeline, x, y, scoring=scoring, n_repeats=15, random_state=seed, n_jobs=-1
    )
    ranked = sorted(
        zip(names, result.importances_mean, result.importances_std, strict=True),
        key=lambda triple: -triple[1],
    )
    return [
        {"feature": name, "drop": round(float(mean), 5), "sd": round(float(sd), 5)}
        for name, mean, sd in ranked[:limit]
        if mean > 0
    ]


@dataclass
class TaskResult:
    task: str
    kind: str
    note: str
    n_train: int
    n_test: int
    patients_train: int
    patients_test: int
    class_balance: dict = field(default_factory=dict)
    selection: list[dict] = field(default_factory=list)
    chosen: str = ""
    trivial: dict = field(default_factory=dict)
    ablations: dict = field(default_factory=dict)
    confusion: dict = field(default_factory=dict)
    importances: list[dict] = field(default_factory=list)
    per_patient: dict = field(default_factory=dict)
    # Exactly the columns the saved pipeline was fitted on, in order. Not the same as the
    # full feature list: a column that is constant within this task's rows is dropped, and
    # a model handed the full list back would be handed a column it has never seen.
    columns: list[str] = field(default_factory=list)


def run_task(
    frame: pd.DataFrame, task: Task, seed: int, truth: pd.DataFrame | None = None
) -> tuple[TaskResult, Pipeline | None]:
    rows = frame if task.subset != "pain" else frame[frame["pain_level"] > 0]
    train_rows = rows[rows["split"] == "train"]
    test_rows = rows[rows["split"] == "test"]

    result = TaskResult(
        task=task.code,
        kind=task.kind,
        note=task.note,
        n_train=len(train_rows),
        n_test=len(test_rows),
        patients_train=train_rows["patient_id"].nunique(),
        patients_test=test_rows["patient_id"].nunique(),
    )
    if task.kind == CLASSIFICATION:
        result.class_balance = {
            str(key): int(value) for key, value in rows[task.target].value_counts().items()
        }
    else:
        result.class_balance = {
            "mean": round(float(rows[task.target].mean()), 3),
            "sd": round(float(rows[task.target].std()), 3),
        }

    chosen_pipeline = None
    for ablation, dropped in ABLATIONS.items():
        columns = feature_columns(rows, dropped)
        columns = [name for name in columns if name not in _constant(train_rows, columns)]
        if not columns:
            continue

        x_train = train_rows[columns].to_numpy(dtype=float)
        y_train = train_rows[task.target].to_numpy()
        x_test = test_rows[columns].to_numpy(dtype=float)
        y_test = test_rows[task.target].to_numpy()
        groups = train_rows["patient_id"].to_numpy()

        if ablation == "all":
            # Choose the model on cross-validated training folds. Choosing it on the test
            # split would make the test figure a best-of-four, which is not a held-out
            # score however it is labelled.
            for name, pipeline in candidates(task.kind, seed, task.bounds).items():
                cv = cross_validate(pipeline, x_train, y_train, groups, task.kind, task.primary)
                result.selection.append({"model": name, "cv": cv})
            trivial = "majority" if task.kind == CLASSIFICATION else "mean"
            better = max if task.kind == CLASSIFICATION else min
            real = [entry for entry in result.selection if entry["model"] != trivial]
            result.chosen = better(real, key=lambda entry: entry["cv"]["mean"])["model"]

            baseline = candidates(task.kind, seed, task.bounds)[trivial].fit(x_train, y_train)
            result.trivial = _score(baseline, x_test, y_test, task.kind)
            result.trivial["model"] = trivial

        pipeline = candidates(task.kind, seed, task.bounds)[result.chosen]
        # The model family is held fixed across ablations and chosen once, on the full
        # feature set, so that a difference between two rows is a difference in what the
        # model could see and not in how it was tuned.
        scores = {
            "cv": cross_validate(
                candidates(task.kind, seed, task.bounds)[result.chosen],
                x_train,
                y_train,
                groups,
                task.kind,
                task.primary,
            )
        }
        pipeline.fit(x_train, y_train)
        scores.update(_score(pipeline, x_test, y_test, task.kind))
        scores["features"] = len(columns)
        scores["dropped_groups"] = list(dropped or ())
        result.ablations[ablation] = scores

        if ablation == "all":
            chosen_pipeline = pipeline
            result.columns = list(columns)
            result.importances = importances(
                pipeline, x_test, y_test, columns, task.kind, seed
            )
            if task.kind == REGRESSION and len(test_rows):
                result.per_patient = per_patient_error(
                    test_rows["patient_id"].to_numpy(), y_test, pipeline.predict(x_test), truth
                )
            if task.kind == CLASSIFICATION:
                labels = sorted(set(y_train) | set(y_test))
                matrix = confusion_matrix(y_test, pipeline.predict(x_test), labels=labels)
                result.confusion = {
                    "labels": [str(label) for label in labels],
                    "rows_are_actual": matrix.tolist(),
                }

    return result, chosen_pipeline


def per_patient_error(
    patients: np.ndarray, actual: np.ndarray, predicted: np.ndarray, truth: pd.DataFrame | None
) -> dict:
    """How the test error is distributed over people, and why.

    A mean absolute error pooled over sessions hides the thing that matters clinically: the
    error is not spread evenly, it is concentrated in particular patients, every one of
    whose sessions is wrong in the same direction. On this dataset the cause is knowable,
    because the generator recorded it - each patient carries a standing self-report bias,
    and the correlation below says how much of the per-patient residual it accounts for.
    On real data the same pattern would be visible and the cause would not be, which is the
    argument for calibrating to a patient rather than to a population.
    """
    frame = pd.DataFrame(
        {
            "patient_id": patients,
            "residual": np.asarray(actual, float) - np.asarray(predicted, float),
        }
    )
    grouped = frame.groupby("patient_id")["residual"]
    summary = pd.DataFrame(
        {
            "sessions": grouped.size(),
            "mae": grouped.apply(lambda values: float(values.abs().mean())),
            "mean_residual": grouped.mean(),
        }
    ).reset_index()

    report = {
        "worst": [
            {
                "patient_id": str(row.patient_id),
                "sessions": int(row.sessions),
                "mae": round(float(row.mae), 3),
                "mean_residual": round(float(row.mean_residual), 3),
            }
            for row in summary.sort_values("mae", ascending=False).head(3).itertuples()
        ],
        "best_patient_mae": round(float(summary["mae"].min()), 3),
        "worst_patient_mae": round(float(summary["mae"].max()), 3),
    }
    if truth is not None and "report_bias" in truth.columns:
        joined = summary.merge(
            truth[["patient_id", "report_bias"]], on="patient_id", how="inner"
        )
        if len(joined) > 2 and joined["mean_residual"].std() > 0:
            correlation = float(joined["mean_residual"].corr(joined["report_bias"]))
            report["residual_vs_report_bias_r"] = round(correlation, 3)
    return report


def _score(pipeline: Pipeline, x, y, kind: str) -> dict:
    predicted = pipeline.predict(x)
    if kind == CLASSIFICATION:
        probabilities = (
            pipeline.predict_proba(x) if hasattr(pipeline, "predict_proba") else None
        )
        return _classification_scores(y, predicted, probabilities, sorted(set(y)))
    return _regression_scores(y, predicted)


REPORT_HEAD = """# Baseline models on the simulated signal dataset

{warning}

Dataset `{dataset}` &middot; fitted {stamp} &middot; seed {seed} &middot; split by patient,
{patients_train} train / {patients_test} test.

Every test figure comes from patients no model in this report was fitted on or selected
with. The model for each task was chosen by {folds}-fold grouped cross-validation over the
training patients; the test split was scored once, afterwards.
"""


def write_report(path: Path, results: list[TaskResult], meta: dict) -> None:
    lines = [
        REPORT_HEAD.format(
            warning=WARNING,
            dataset=meta["dataset"],
            stamp=meta["fitted_at"][:19].replace("T", " "),
            seed=meta["seed"],
            patients_train=results[0].patients_train,
            patients_test=results[0].patients_test,
            folds=FOLDS,
        )
    ]

    for result in results:
        lines.append(f"\n## {result.task}\n")
        lines.append(f"{result.note}\n")
        lines.append(
            f"{result.n_train} training sessions from {result.patients_train} patients, "
            f"{result.n_test} test sessions from {result.patients_test}. "
            f"Chosen model: `{result.chosen}`.\n"
        )

        lines.append("\n### Model selection, grouped CV on the training patients\n")
        lines.append("| model | " + result.selection[0]["cv"]["metric"] + " | spread |")
        lines.append("| --- | --- | --- |")
        for entry in result.selection:
            cv = entry["cv"]
            mark = " &larr;" if entry["model"] == result.chosen else ""
            lines.append(
                f"| `{entry['model']}`{mark} | {cv['mean']:.3f} &plusmn; {cv['sd']:.3f} | "
                f"{cv['min']:.3f} to {cv['max']:.3f} |"
            )

        lines.append("\n### Held-out test split, by what the model was allowed to see\n")
        skip = ("features", "dropped_groups", "cv")
        metrics = sorted(
            {key for scores in result.ablations.values() for key in scores if key not in skip}
        )
        header = ["features", "n", f"CV {result.selection[0]['cv']['metric']}", *metrics]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + " --- |" * len(header))
        trivial = " | ".join(
            f"{result.trivial.get(metric, float('nan')):.3f}" for metric in metrics
        )
        lines.append(
            f"| `{result.trivial['model']}` (trivial) | &mdash; | &mdash; | {trivial} |"
        )
        for ablation, scores in result.ablations.items():
            cv = scores["cv"]
            values = " | ".join(f"{scores.get(metric, float('nan')):.3f}" for metric in metrics)
            lines.append(
                f"| `{ablation}` | {scores['features']} | "
                f"{cv['mean']:.3f} &plusmn; {cv['sd']:.3f} | {values} |"
            )
        lines.append(
            "\nThe CV column is the fold mean over the training patients and is the more "
            "stable of the two; the test columns come from a single split of "
            f"{result.patients_test} patients, where a difference smaller than the fold "
            "spread means nothing.\n"
        )

        if result.confusion:
            labels = result.confusion["labels"]
            lines.append("\n### Confusion on the test split, rows actual\n")
            lines.append("| actual \\ predicted | " + " | ".join(labels) + " |")
            lines.append("| --- |" + " --- |" * len(labels))
            for label, row in zip(labels, result.confusion["rows_are_actual"], strict=True):
                cells = " | ".join(str(value) for value in row)
                lines.append(f"| **{label}** | {cells} |")

        if result.per_patient:
            spread = result.per_patient
            lines.append("\n### Where the test error sits\n")
            worst = ", ".join(
                f"`{entry['patient_id']}` MAE {entry['mae']:.2f} over {entry['sessions']} "
                f"sessions (mean residual {entry['mean_residual']:+.2f})"
                for entry in spread["worst"]
            )
            lines.append(
                f"Per-patient MAE runs from {spread['best_patient_mae']:.2f} to "
                f"{spread['worst_patient_mae']:.2f}. Worst three: {worst}."
            )
            if "residual_vs_report_bias_r" in spread:
                lines.append(
                    f"\nA patient's mean residual correlates r = "
                    f"{spread['residual_vs_report_bias_r']:.2f} with the standing self-report "
                    "bias the generator gave them. The model is not failing on those patients; "
                    "it is predicting their physiology correctly and being scored against a "
                    "number they shifted.\n"
                )

        if result.importances:
            lines.append("\n### What the model leaned on\n")
            lines.append(
                "Permutation importance on the test split: the drop in "
                + ("macro F1" if result.kind == CLASSIFICATION else "MAE")
                + " when that column alone is shuffled.\n"
            )
            top = ", ".join(
                f"`{entry['feature']}` {entry['drop']:.3f}" for entry in result.importances
            )
            lines.append(top + "\n")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def train(directory: Path, seed: int = SEED) -> dict:
    frame = prepare(directory / "features.csv")
    # Only present because the data is simulated: the per-patient traits the generator drew.
    # Used for a diagnostic, never as a feature.
    patients = directory / "patients.csv"
    truth = pd.read_csv(patients) if patients.exists() else None
    destination = directory / "baseline"
    destination.mkdir(parents=True, exist_ok=True)

    results = []
    for task in TASKS:
        result, pipeline = run_task(frame, task, seed, truth)
        results.append(result)
        if pipeline is not None:
            joblib.dump(
                {
                    "task": task.code,
                    "kind": task.kind,
                    "target": task.target,
                    "model": result.chosen,
                    "features": result.columns,
                    "applies_to": task.subset or "every session",
                    "pipeline": pipeline,
                    "dataset": directory.name,
                    "synthetic": True,
                    "warning": WARNING,
                },
                destination / f"{task.code}.joblib",
            )

    metrics = {
        "baseline_version": BASELINE_VERSION,
        "dataset": directory.name,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "synthetic": True,
        "warning": WARNING,
        "cv": f"GroupKFold({FOLDS}) by patient over the training split",
        "encoding": (
            "median imputation with a missing indicator, then z-score standardisation, "
            "fitted inside each fold"
        ),
        "feature_groups": {name: list(prefixes) for name, prefixes in GROUPS.items()},
        "ablations": {name: list(dropped or ()) for name, dropped in ABLATIONS.items()},
        "tasks": [
            {
                "task": result.task,
                "kind": result.kind,
                "note": result.note,
                "n_train": result.n_train,
                "n_test": result.n_test,
                "patients_train": result.patients_train,
                "patients_test": result.patients_test,
                "class_balance": result.class_balance,
                "selection": result.selection,
                "chosen": result.chosen,
                "trivial": result.trivial,
                "ablations": result.ablations,
                "confusion": result.confusion,
                "importances": result.importances,
                "per_patient": result.per_patient,
            }
            for result in results
        ],
    }
    (destination / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )
    write_report(destination / "report.md", results, metrics)
    return metrics


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fit baseline models to a simulated signal dataset."
    )
    parser.add_argument(
        "dataset",
        type=Path,
        nargs="?",
        help="the versioned dataset directory; the newest under ./backend/datasets if omitted",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    arguments = parser.parse_args(argv)

    directory = arguments.dataset
    if directory is None:
        found = sorted(Path("backend/datasets").glob("signals-v*"))
        if not found:
            parser.error("no dataset directory given and none found under backend/datasets")
        directory = found[-1]
    if not (directory / "features.csv").exists():
        parser.error(f"{directory} holds no features.csv")

    metrics = train(directory, arguments.seed)

    print(WARNING)
    print(f"dataset {metrics['dataset']}  seed {metrics['seed']}  {metrics['cv']}")
    for task in metrics["tasks"]:
        head = (
            f"\n{task['task']}  ({task['kind']}, chosen: {task['chosen']})  "
            f"{task['n_train']} train / {task['n_test']} test sessions"
        )
        print(head)
        trivial = task["trivial"]
        primary = "macro_f1" if task["kind"] == CLASSIFICATION else "mae"
        print(
            f"  {trivial['model']:<16} {primary} {trivial[primary]:.3f}"
            "   (trivial reference)"
        )
        for name, scores in task["ablations"].items():
            cv = scores["cv"]
            extra = (
                f"acc {scores['accuracy']:.3f}"
                if task["kind"] == CLASSIFICATION
                else f"rmse {scores['rmse']:.2f}  rho {scores['spearman']:.2f}"
            )
            print(
                f"  {name:<16} {primary} {scores[primary]:.3f}   "
                f"cv {cv['mean']:.3f} +/- {cv['sd']:.3f}   {extra}"
            )
    print(f"\nwritten to {metrics['dataset']}/baseline/ (report.md, metrics.json, *.joblib)")


if __name__ == "__main__":
    main()
