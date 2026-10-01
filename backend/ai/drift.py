import math
from dataclasses import dataclass, field

from knowledge import rules

MINIMUM_RECENT = 20
SHIFT_WARNING_SD = 0.5
MISSINGNESS_WARNING = 0.2
PREDICTION_WATCH_SD = 0.5
PREDICTION_WARNING_SD = 1.0
WARNING_FEATURE_COUNT = 3

NONE = "NONE"
WATCH = "WATCH"
WARNING = "WARNING"

INSUFFICIENT_NOTE = "insufficient recent predictions"


@dataclass
class FeatureShift:
    feature: str
    train_mean: float | None
    recent_mean: float | None
    shift_sd: float | None
    train_missing_rate: float
    recent_missing_rate: float
    missingness_change: float


@dataclass
class DriftReport:
    level: str
    n_recent: int
    sufficient: bool
    features: dict[str, FeatureShift] = field(default_factory=dict)
    prediction_shift_sd: float | None = None
    band_histogram_train: dict[str, float] = field(default_factory=dict)
    band_histogram_recent: dict[str, float] = field(default_factory=dict)

    band_distance: float | None = None
    warnings: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "n_recent": self.n_recent,
            "sufficient": self.sufficient,
            "prediction_shift_sd": self.prediction_shift_sd,
            "band_histogram_train": self.band_histogram_train,
            "band_histogram_recent": self.band_histogram_recent,
            "band_distance": self.band_distance,
            "warnings": list(self.warnings),
            "note": self.note,
            "features": {
                name: {
                    "train_mean": shift.train_mean,
                    "recent_mean": shift.recent_mean,
                    "shift_sd": shift.shift_sd,
                    "train_missing_rate": shift.train_missing_rate,
                    "recent_missing_rate": shift.recent_missing_rate,
                    "missingness_change": shift.missingness_change,
                }
                for name, shift in self.features.items()
            },
        }


def _present(value) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def band_histogram(predictions: list[float]) -> dict[str, float]:
    counts = {code: 0 for _, code, _ in rules.PAIN_BANDS}
    for value in predictions:
        counts[rules.band(float(value))[0]] += 1
    total = len(predictions) or 1
    return {code: round(count / total, 4) for code, count in counts.items()}


def _feature_shift(name: str, summary: dict, values: list) -> FeatureShift:
    present = [float(v) for v in values if _present(v)]
    recent_missing = 1.0 - len(present) / len(values) if values else 1.0
    train_missing = float(summary.get("missing_rate") or 0.0)
    train_mean = summary.get("mean")
    train_sd = summary.get("sd")
    recent_mean = sum(present) / len(present) if present else None
    shift = None
    if recent_mean is not None and train_mean is not None and train_sd and train_sd > 0:
        shift = round((recent_mean - float(train_mean)) / float(train_sd), 4)
    return FeatureShift(
        feature=name,
        train_mean=None if train_mean is None else round(float(train_mean), 4),
        recent_mean=None if recent_mean is None else round(recent_mean, 4),
        shift_sd=shift,
        train_missing_rate=round(train_missing, 4),
        recent_missing_rate=round(recent_missing, 4),
        missingness_change=round(recent_missing - train_missing, 4),
    )


def assess(
    profile: dict,
    recent_feature_rows: list[dict[str, float | None]],
    recent_predictions: list[float],
) -> DriftReport:
    n_recent = len(recent_predictions)
    if n_recent < MINIMUM_RECENT or len(recent_feature_rows) < MINIMUM_RECENT:
        return DriftReport(
            level=NONE, n_recent=n_recent, sufficient=False, note=INSUFFICIENT_NOTE
        )

    feature_profile = profile.get("features") or {}
    report = DriftReport(level=NONE, n_recent=n_recent, sufficient=True)
    for name, summary in feature_profile.items():
        values = [row.get(name) for row in recent_feature_rows]
        shift = _feature_shift(name, summary, values)
        report.features[name] = shift
        if shift.shift_sd is not None and abs(shift.shift_sd) > SHIFT_WARNING_SD:
            report.warnings.append(
                f"{name}: mean moved {shift.shift_sd:+.2f} training standard deviations"
            )
        if shift.missingness_change > MISSINGNESS_WARNING:
            report.warnings.append(
                f"{name}: missing in {shift.recent_missing_rate:.0%} of recent records "
                f"against {shift.train_missing_rate:.0%} in training"
            )

    prediction_profile = profile.get("prediction") or {}
    report.band_histogram_train = dict(prediction_profile.get("histogram") or {})
    report.band_histogram_recent = band_histogram(recent_predictions)
    train_mean = prediction_profile.get("mean")
    train_sd = prediction_profile.get("sd")
    if train_mean is not None and train_sd:
        recent_mean = sum(float(v) for v in recent_predictions) / n_recent
        report.prediction_shift_sd = round(
            (recent_mean - float(train_mean)) / float(train_sd), 4
        )
    if report.band_histogram_train:
        bands = set(report.band_histogram_train) | set(report.band_histogram_recent)
        report.band_distance = round(
            0.5
            * sum(
                abs(
                    report.band_histogram_train.get(b, 0.0)
                    - report.band_histogram_recent.get(b, 0.0)
                )
                for b in bands
            ),
            4,
        )

    prediction_shift = abs(report.prediction_shift_sd or 0.0)
    if prediction_shift >= PREDICTION_WARNING_SD:
        report.warnings.append(
            f"predictions: mean moved {report.prediction_shift_sd:+.2f} training standard deviations"
        )
    if (
        len(report.warnings) >= WARNING_FEATURE_COUNT
        or prediction_shift >= PREDICTION_WARNING_SD
    ):
        report.level = WARNING
    elif report.warnings or prediction_shift >= PREDICTION_WATCH_SD:
        report.level = WATCH
    return report
