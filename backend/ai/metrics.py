"""Metrics for the estimate, including the ones a regression score cannot show.

A mean absolute error says how far the estimate sits from the reference on average. It
says nothing about which direction the misses go, and in pain assessment the two
directions are not equivalent: a patient whose real pain is severe and whose estimate
reads mild may be left untreated, which is the harm section 17 of the brief singles out.
So alongside the regression figures this module reports the band confusion matrix,
precision and recall per band, and an explicit under-estimation analysis at the thresholds
that would change what a clinician does.

Everything here is computed from held-out predictions. Nothing is modelled.
"""

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import (
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
)

from knowledge import rules

BAND_ORDER = tuple(code for _, code, _ in rules.PAIN_BANDS)
BAND_LABELS = {code: label for _, code, label in rules.PAIN_BANDS}

# The thresholds where a miss changes what a clinician would do. 4 is the bottom of the
# moderate band once rounded, 7 the bottom of severe.
UNDER_ESTIMATION_THRESHOLDS = (4.0, 7.0)

# A miss wider than this is reported separately: the estimate is not merely imprecise, it
# points at a different clinical picture.
SEVERE_MISS = 3.0


def bands(values) -> list[str]:
    return [rules.band(float(value))[0] for value in values]


@dataclass
class BandMetrics:
    code: str
    label: str
    support: int
    precision: float
    recall: float
    f1: float


@dataclass
class UnderEstimation:
    """How often real pain at or above a threshold was estimated below it."""

    threshold: float
    actual: int
    missed: int
    # Of the cases at or above the threshold, the share the estimate placed below it.
    miss_rate: float
    # The reverse error, for the trade-off: estimated at or above the threshold while the
    # reference was below it.
    false_alarms: int
    false_alarm_rate: float
    # How far below the threshold the missed cases were placed, on average.
    mean_shortfall: float
    worst_shortfall: float

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "actual": self.actual,
            "missed": self.missed,
            "miss_rate": self.miss_rate,
            "false_alarms": self.false_alarms,
            "false_alarm_rate": self.false_alarm_rate,
            "mean_shortfall": self.mean_shortfall,
            "worst_shortfall": self.worst_shortfall,
        }


@dataclass
class GroupMetrics:
    key: str
    n: int
    mae: float
    rmse: float
    # Signed mean error. Negative means the estimate runs below the reference for this
    # group, which is the direction that leaves pain untreated.
    bias: float
    # Share of cases at or above the moderate threshold placed below it.
    moderate_miss_rate: float | None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "n": self.n,
            "mae": self.mae,
            "rmse": self.rmse,
            "bias": self.bias,
            "moderate_miss_rate": self.moderate_miss_rate,
        }


@dataclass
class Report:
    n: int
    mae: float
    rmse: float
    r2: float
    bias: float
    band_order: tuple[str, ...]
    # Rows are the reference band, columns the estimated band, both in band_order.
    confusion: list[list[int]]
    per_band: list[BandMetrics] = field(default_factory=list)
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    macro_f1: float = 0.0
    weighted_f1: float = 0.0
    band_accuracy: float = 0.0
    # Share of cases placed in a band adjacent to the right one or the right one itself.
    within_one_band: float = 0.0
    severe_misses: int = 0
    severe_miss_rate: float = 0.0
    under_estimation: list[UnderEstimation] = field(default_factory=list)
    by_profile: list[GroupMetrics] = field(default_factory=list)
    by_reference_scale: list[GroupMetrics] = field(default_factory=list)
    by_scenario: list[GroupMetrics] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "mae": self.mae,
            "rmse": self.rmse,
            "r2": self.r2,
            "bias": self.bias,
            "band_order": list(self.band_order),
            "band_labels": [BAND_LABELS[code] for code in self.band_order],
            "confusion": self.confusion,
            "per_band": [
                {
                    "code": entry.code,
                    "label": entry.label,
                    "support": entry.support,
                    "precision": entry.precision,
                    "recall": entry.recall,
                    "f1": entry.f1,
                }
                for entry in self.per_band
            ],
            "macro_precision": self.macro_precision,
            "macro_recall": self.macro_recall,
            "macro_f1": self.macro_f1,
            "weighted_f1": self.weighted_f1,
            "band_accuracy": self.band_accuracy,
            "within_one_band": self.within_one_band,
            "severe_misses": self.severe_misses,
            "severe_miss_rate": self.severe_miss_rate,
            "under_estimation": [entry.to_dict() for entry in self.under_estimation],
            "by_profile": [entry.to_dict() for entry in self.by_profile],
            "by_reference_scale": [entry.to_dict() for entry in self.by_reference_scale],
            "by_scenario": [entry.to_dict() for entry in self.by_scenario],
        }


def _round(value) -> float:
    return round(float(value), 4)


def under_estimation(
    y_true: np.ndarray, y_pred: np.ndarray, threshold: float
) -> UnderEstimation:
    at_or_above = y_true >= threshold
    below = y_true < threshold
    missed_mask = at_or_above & (y_pred < threshold)
    shortfalls = threshold - y_pred[missed_mask]
    alarms = int((below & (y_pred >= threshold)).sum())

    return UnderEstimation(
        threshold=threshold,
        actual=int(at_or_above.sum()),
        missed=int(missed_mask.sum()),
        miss_rate=_round(missed_mask.sum() / at_or_above.sum()) if at_or_above.any() else 0.0,
        false_alarms=alarms,
        false_alarm_rate=_round(alarms / below.sum()) if below.any() else 0.0,
        mean_shortfall=_round(shortfalls.mean()) if shortfalls.size else 0.0,
        worst_shortfall=_round(shortfalls.max()) if shortfalls.size else 0.0,
    )


def _group(key: str, y_true: np.ndarray, y_pred: np.ndarray) -> GroupMetrics:
    moderate = UNDER_ESTIMATION_THRESHOLDS[0]
    at_or_above = y_true >= moderate
    miss_rate = (
        _round(((y_true >= moderate) & (y_pred < moderate)).sum() / at_or_above.sum())
        if at_or_above.any()
        else None
    )
    return GroupMetrics(
        # str(): a label coming from a numpy array is an np.str_, which survives JSON only
        # by accident of subclassing.
        key=str(key),
        n=len(y_true),
        mae=_round(mean_absolute_error(y_true, y_pred)),
        rmse=_round(np.sqrt(mean_squared_error(y_true, y_pred))),
        bias=_round((y_pred - y_true).mean()),
        moderate_miss_rate=miss_rate,
    )


def by_group(labels, y_true: np.ndarray, y_pred: np.ndarray) -> list[GroupMetrics]:
    """One row per distinct label, worst mean absolute error first, so the population the
    model serves least well is the one at the top."""
    if len(labels) != len(y_true):
        return []
    rows = []
    for key in sorted(set(labels)):
        mask = np.array([label == key for label in labels])
        if not mask.any():
            continue
        rows.append(_group(key, y_true[mask], y_pred[mask]))
    return sorted(rows, key=lambda row: row.mae, reverse=True)


def evaluate(
    y_true,
    y_pred,
    *,
    profiles=(),
    reference_scales=(),
    scenarios=(),
) -> Report:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    true_bands = bands(y_true)
    predicted_bands = bands(y_pred)
    matrix = confusion_matrix(true_bands, predicted_bands, labels=list(BAND_ORDER))

    precision, recall, f1, support = precision_recall_fscore_support(
        true_bands, predicted_bands, labels=list(BAND_ORDER), zero_division=0
    )
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        true_bands, predicted_bands, labels=list(BAND_ORDER), average="macro", zero_division=0
    )
    _, _, weighted_f1, _ = precision_recall_fscore_support(
        true_bands,
        predicted_bands,
        labels=list(BAND_ORDER),
        average="weighted",
        zero_division=0,
    )

    position = {code: index for index, code in enumerate(BAND_ORDER)}
    distances = np.array(
        [abs(position[a] - position[b]) for a, b in zip(true_bands, predicted_bands)]
    )
    severe = int((np.abs(y_pred - y_true) > SEVERE_MISS).sum())

    return Report(
        n=len(y_true),
        mae=_round(mean_absolute_error(y_true, y_pred)),
        rmse=_round(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2=_round(r2_score(y_true, y_pred)),
        bias=_round((y_pred - y_true).mean()),
        band_order=BAND_ORDER,
        confusion=[[int(value) for value in row] for row in matrix],
        per_band=[
            BandMetrics(
                code=code,
                label=BAND_LABELS[code],
                support=int(support[index]),
                precision=_round(precision[index]),
                recall=_round(recall[index]),
                f1=_round(f1[index]),
            )
            for index, code in enumerate(BAND_ORDER)
        ],
        macro_precision=_round(macro_p),
        macro_recall=_round(macro_r),
        macro_f1=_round(macro_f1),
        weighted_f1=_round(weighted_f1),
        band_accuracy=_round((distances == 0).mean()) if distances.size else 0.0,
        within_one_band=_round((distances <= 1).mean()) if distances.size else 0.0,
        severe_misses=severe,
        severe_miss_rate=_round(severe / len(y_true)) if len(y_true) else 0.0,
        under_estimation=[
            under_estimation(y_true, y_pred, threshold)
            for threshold in UNDER_ESTIMATION_THRESHOLDS
        ],
        by_profile=by_group(list(profiles), y_true, y_pred),
        by_reference_scale=by_group(list(reference_scales), y_true, y_pred),
        by_scenario=by_group(list(scenarios), y_true, y_pred),
    )
