"""Fitting a burned-surface estimator to the MassHumanBurns dataset.

Why this model is worth having: a burn photographed or rendered from the front shows a
two-dimensional projection, and the fraction of that projection which is burned is not the
fraction of the body surface which is burned. A limb seen edge-on contributes few pixels
and a torso seen flat contributes many. The dataset's published label is the true surface
fraction, so a model can learn the correction from the projection to the real figure, and
the error of the naive pixel ratio is the thing it has to beat.

What this is not: it is trained on *synthetic* renders of body meshes, which the dataset
card states plainly. It carries no information about real burns, real skin or real
photographs, and it is recorded as a research model that is never used for a clinical
estimate. `app.burns` does not call it; a clinician's chart is what the module uses.

Splitting is by subject. Each subject appears in 64 rows — eight burn extents, four camera
variants, two views — and a random split over rows would put the same body in train and
test and report an error that means nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: The published label file is one row per subject, one column per burn extent.
LABELS_NAME = "labels.npy"
GENDER_NAME = "gender.json"

#: Masks are downsampled to this before features are taken. Large enough to keep where on
#: the body the burn is, small enough that 40,000 pairs fit in memory.
GRID = 24

#: One camera variant is used rather than all four. The four are the same body and the
#: same burn from slightly different angles, so including all of them quadruples the work
#: and adds near-duplicate rows that a grouped split would not separate anyway.
VARIANT = 0

FILENAME = re.compile(r"^(\d+)_(\d+)_(\d+)\.png$")


class DatasetUnavailable(RuntimeError):
    """The extracted dataset is not where it was expected, or is incomplete."""


@dataclass
class Sample:
    subject: int
    level: int
    front: np.ndarray
    back: np.ndarray | None
    tbsa: float


@dataclass
class Result:
    algorithm: str
    n_subjects: int
    n_train: int
    n_test: int
    mae: float
    rmse: float
    r2: float
    #: The error of predicting the training mean for every row. A model that cannot beat
    #: this has learned nothing, and the comparison belongs beside the score.
    mean_baseline_mae: float
    #: The error of taking the burned share of the front projection as the answer. This is
    #: the naive geometric estimate the model exists to improve on.
    pixel_ratio_mae: float
    pixel_ratio_calibrated_mae: float
    pearson: float = 0.0
    cv_folds: int = 0
    cv_mae_mean: float = 0.0
    cv_mae_sd: float = 0.0
    residual_sd: float = 0.0
    features: list[str] = field(default_factory=list)
    feature_importance: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def beats_mean(self) -> bool:
        return self.mae < self.mean_baseline_mae

    @property
    def beats_pixel_ratio(self) -> bool:
        return self.mae < self.pixel_ratio_calibrated_mae

    def as_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
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
            "mean_baseline_mae": self.mean_baseline_mae,
            "pixel_ratio_mae": self.pixel_ratio_mae,
            "pixel_ratio_calibrated_mae": self.pixel_ratio_calibrated_mae,
            "beats_mean_baseline": self.beats_mean,
            "beats_naive_pixel_ratio": self.beats_pixel_ratio,
            "features": self.features,
            "feature_importance": self.feature_importance,
            "notes": self.notes,
        }


def _load_mask(path: Path) -> np.ndarray:
    """A mask as a float array in [0, 1], downsampled to GRID by block mean.

    Block mean rather than nearest-neighbour: a thin burn on a limb can be one pixel wide
    in the render, and nearest-neighbour sampling drops it entirely, which would make the
    feature silently wrong for exactly the small burns that matter.
    """
    from PIL import Image

    with Image.open(path) as handle:
        frame = handle.convert("L")
        # Pillow's reducing resample is an area average, which is the block mean.
        small = frame.resize((GRID, GRID), Image.Resampling.BOX)
        return np.asarray(small, dtype=np.float32) / 255.0


def discover(root: Path) -> tuple[Path, Path, Path | None]:
    """Locate the label file and the mask directories under an extracted dataset."""
    labels = next(root.rglob(LABELS_NAME), None)
    if labels is None:
        raise DatasetUnavailable(
            f"{LABELS_NAME} was not found under {root}. The MassHumanBurns label file is "
            "needed; it is 320 KB and published in the repository root."
        )
    burn = next((p for p in root.rglob("burn_masks") if p.is_dir()), None)
    if burn is None:
        raise DatasetUnavailable(
            f"no burn_masks directory under {root}. Extract burn_masks.7z before training."
        )
    body = next((p for p in root.rglob("full_masks") if p.is_dir()), None)
    return labels, burn, body


def load(root: Path, *, limit_subjects: int | None = None) -> tuple[list[Sample], dict]:
    """Read the masks and pair each with its published surface fraction."""
    labels_path, burn_dir, body_dir = discover(root)
    labels = np.load(labels_path, allow_pickle=False)
    if labels.ndim != 2:
        raise DatasetUnavailable(
            f"{labels_path.name} has shape {labels.shape}; one row per subject and one "
            "column per burn extent was expected"
        )

    front_dir = burn_dir / "front"
    back_dir = burn_dir / "back"
    if not front_dir.is_dir():
        raise DatasetUnavailable(f"no front view directory under {burn_dir}")

    available: dict[tuple[int, int], Path] = {}
    for path in front_dir.iterdir():
        match = FILENAME.match(path.name)
        if match is None:
            continue
        subject, level, variant = (int(part) for part in match.groups())
        if variant != VARIANT:
            continue
        if subject < labels.shape[0] and level < labels.shape[1]:
            available[(subject, level)] = path

    subjects = sorted({subject for subject, _level in available})
    if limit_subjects is not None:
        subjects = subjects[:limit_subjects]
    wanted = set(subjects)

    samples: list[Sample] = []
    for (subject, level), path in sorted(available.items()):
        if subject not in wanted:
            continue
        back_path = back_dir / path.name
        samples.append(
            Sample(
                subject=subject,
                level=level,
                front=_load_mask(path),
                back=_load_mask(back_path) if back_path.exists() else None,
                tbsa=float(labels[subject, level]),
            )
        )

    meta = {
        "labels_file": str(labels_path),
        "labels_shape": list(labels.shape),
        "subjects_available": len({s for s, _ in available}),
        "subjects_used": len(subjects),
        "samples": len(samples),
        "has_back_view": any(sample.back is not None for sample in samples),
        "has_full_body_masks": body_dir is not None,
        "camera_variant": VARIANT,
        "grid": GRID,
    }
    gender = next(root.rglob(GENDER_NAME), None)
    if gender is not None:
        try:
            payload = json.loads(gender.read_text(encoding="utf-8"))
            meta["gender_groups"] = {key: len(value) for key, value in payload.items()}
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
    if not samples:
        raise DatasetUnavailable("no mask matched a published label")
    return samples, meta


def features(samples: list[Sample]) -> tuple[np.ndarray, list[str]]:
    """Per-sample features: the downsampled masks plus a few summary geometries.

    The grid cells carry where on the body the burn is, which is what lets the model
    learn that a given projected area means different things on a torso and on a forearm.
    The summaries are there so the model does not have to rediscover total area from 1,152
    cells.
    """
    names = [f"front_{index}" for index in range(GRID * GRID)]
    has_back = any(sample.back is not None for sample in samples)
    if has_back:
        names += [f"back_{index}" for index in range(GRID * GRID)]
    names += [
        "front_area",
        "back_area",
        "total_area",
        "front_rows_covered",
        "front_cols_covered",
        "front_centroid_row",
        "front_centroid_col",
        "front_spread",
    ]

    rows = []
    for sample in samples:
        front = sample.front
        back = sample.back if sample.back is not None else np.zeros_like(front)
        parts = [front.ravel()]
        if has_back:
            parts.append(back.ravel())

        front_area = float(front.mean())
        back_area = float(back.mean())
        occupied = front > 0.05
        if occupied.any():
            indices = np.argwhere(occupied)
            centroid_row = float(indices[:, 0].mean() / GRID)
            centroid_col = float(indices[:, 1].mean() / GRID)
            spread = float(indices.std() / GRID)
            rows_covered = float(len(np.unique(indices[:, 0])) / GRID)
            cols_covered = float(len(np.unique(indices[:, 1])) / GRID)
        else:
            centroid_row = centroid_col = spread = rows_covered = cols_covered = 0.0
        parts.append(
            np.array(
                [
                    front_area,
                    back_area,
                    front_area + back_area,
                    rows_covered,
                    cols_covered,
                    centroid_row,
                    centroid_col,
                    spread,
                ],
                dtype=np.float32,
            )
        )
        rows.append(np.concatenate(parts))
    return np.asarray(rows, dtype=np.float32), names


def train(
    samples: list[Sample],
    *,
    seed: int = 0,
    test_share: float = 0.25,
    cv_folds: int = 3,
) -> tuple[Result, object]:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import GroupShuffleSplit

    x, names = features(samples)
    y = np.array([sample.tbsa for sample in samples], dtype=float)
    groups = np.array([sample.subject for sample in samples])

    splitter = GroupShuffleSplit(n_splits=1, test_size=test_share, random_state=seed)
    train_index, test_index = next(splitter.split(x, y, groups))
    overlap = set(groups[train_index]) & set(groups[test_index])
    if overlap:
        raise RuntimeError(f"{len(overlap)} subject(s) landed on both sides of the split")

    model = HistGradientBoostingRegressor(random_state=seed, max_iter=300)
    model.fit(x[train_index], y[train_index])
    predicted = model.predict(x[test_index])
    actual = y[test_index]

    # The naive estimate: take the burned share of the projection as the answer directly.
    total_area_column = names.index("total_area")
    naive = x[:, total_area_column]
    # And the same ratio with a single scale factor fitted on the training rows, which is
    # the fairest version of the naive approach to compare against.
    calibration = LinearRegression().fit(
        naive[train_index].reshape(-1, 1), y[train_index]
    )
    calibrated = calibration.predict(naive[test_index].reshape(-1, 1))

    importance = _permutation_importance(model, x[test_index], actual, names, seed)
    residuals = actual - predicted
    result = Result(
        algorithm="HistGradientBoostingRegressor",
        n_subjects=len(set(groups)),
        n_train=len(train_index),
        n_test=len(test_index),
        mae=round(float(mean_absolute_error(actual, predicted)), 5),
        rmse=round(float(np.sqrt(np.mean((actual - predicted) ** 2))), 5),
        r2=round(float(r2_score(actual, predicted)), 5),
        mean_baseline_mae=round(
            float(mean_absolute_error(actual, np.full_like(actual, y[train_index].mean()))), 5
        ),
        pixel_ratio_mae=round(float(mean_absolute_error(actual, naive[test_index])), 5),
        pixel_ratio_calibrated_mae=round(float(mean_absolute_error(actual, calibrated)), 5),
        features=[names[0], "...", names[-1]],
        feature_importance=importance,
        notes=[
            (
                "Trained on synthetic renders of body meshes, not on photographs of real "
                "burns. It carries no information about real skin or real injuries."
            ),
            "Splits are grouped by subject; no body appears in both train and test.",
            "The target is the dataset's published surface fraction, 0 to 1.",
        ],
    )
    result.pearson = _pearson(actual, predicted)
    result.residual_sd = round(float(np.std(residuals)), 5)
    _cross_validate(result, x, y, groups, seed=seed, folds=cv_folds)
    return result, model


def _pearson(actual: np.ndarray, predicted: np.ndarray) -> float:
    if len(actual) < 2 or np.std(actual) == 0 or np.std(predicted) == 0:
        return 0.0
    return round(float(np.corrcoef(actual, predicted)[0, 1]), 5)


def _cross_validate(result: Result, x, y, groups, *, seed: int, folds: int) -> None:
    """Grouped cross-validation, so the spread of the error across folds is visible.

    A single held-out split gives one number and no sense of how much it would move with
    a different draw of subjects. Folds are grouped for the same reason the main split is.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import GroupKFold

    folds = min(folds, len(set(groups)))
    if folds < 2:
        return
    errors = []
    for train_index, test_index in GroupKFold(n_splits=folds).split(x, y, groups):
        fold = HistGradientBoostingRegressor(random_state=seed, max_iter=300)
        fold.fit(x[train_index], y[train_index])
        errors.append(
            float(mean_absolute_error(y[test_index], fold.predict(x[test_index])))
        )
    result.cv_folds = folds
    result.cv_mae_mean = round(float(np.mean(errors)), 5)
    result.cv_mae_sd = round(float(np.std(errors)), 5)


def _permutation_importance(model, x, y, names, seed) -> list[dict]:
    """Which features the test error actually depends on.

    Permutation rather than a built-in importance: this model has over a thousand
    correlated grid cells, and a split-count importance spreads credit across them in a
    way that says little. Only the summary features are permuted, because shuffling one
    grid cell of 1,152 moves nothing measurable.
    """
    from sklearn.metrics import mean_absolute_error

    summary = [
        name
        for name in names
        if not name.startswith(("front_", "back_"))
        or name
        in (
            "front_area",
            "back_area",
            "front_rows_covered",
            "front_cols_covered",
            "front_centroid_row",
            "front_centroid_col",
            "front_spread",
        )
    ]
    rng = np.random.default_rng(seed)
    base = mean_absolute_error(y, model.predict(x))
    scored = []
    for name in summary:
        column = names.index(name)
        shuffled = x.copy()
        rng.shuffle(shuffled[:, column])
        rise = mean_absolute_error(y, model.predict(shuffled)) - base
        scored.append({"feature": name, "mae_increase_when_shuffled": round(float(rise), 5)})
    return sorted(scored, key=lambda item: -item["mae_increase_when_shuffled"])


MODEL_NAME = "burn-tbsa-research"


def persist_and_register(db, result: Result, model, meta: dict, *, actor_id=None) -> str:
    """Save the fitted model and record it in the platform's model registry.

    `is_active` is false and stays false. The registry is shared with the clinical pain
    estimator, and a model trained on synthetic body renders must never be selectable for
    a clinical estimate. `app.burns` reads no model at all.
    """
    import uuid
    from datetime import datetime, timezone

    import joblib

    from config import get_settings
    from database.models import ModelVersion

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    version = f"{MODEL_NAME}-{stamp}-{uuid.uuid4().hex[:6]}"
    destination = get_settings().model_store_path / f"{version}.joblib"
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, destination)

    db.add(
        ModelVersion(
            version=version,
            model_name=MODEL_NAME,
            algorithm=result.algorithm,
            dataset_version=f"huggingface:HLSS/MassHumanBurns@{meta.get('labels_shape')}",
            n_train=result.n_train,
            n_validation=0,
            n_test=result.n_test,
            mae=result.mae,
            rmse=result.rmse,
            r2=result.r2,
            pearson=result.pearson,
            cv_folds=result.cv_folds,
            cv_mae_mean=result.cv_mae_mean,
            cv_mae_sd=result.cv_mae_sd,
            residual_sd=result.residual_sd,
            features=[f"{GRID}x{GRID} front and back mask grids plus 8 summary geometries"],
            feature_importance=result.feature_importance,
            training_profile={**result.as_dict(), "dataset": meta},
            artifact_name=destination.name,
            is_active=False,
            notes=(
                "Research model. Estimates the burned share of the body surface from 2D "
                "body-mask projections, trained on the synthetic MassHumanBurns dataset "
                "(Apache-2.0) with splits grouped by subject. It has seen no real burn, no "
                "real skin and no photograph, is not clinically validated, and is not used "
                "by the burn assessment module, which works from a clinician's chart. "
                + " ".join(result.notes)
            ),
        )
    )
    db.commit()
    return version
