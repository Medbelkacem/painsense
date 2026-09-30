"""Prediction intervals.

The bounds come from two extra gradient boosting models fitted on the 10th and 90th
conditional quantiles of the training target, so the interval is produced by the model
rather than derived from a residual standard deviation and an assumed normal shape. The
coverage that those bounds actually achieved on held-out data is measured during training
and reported alongside the interval, so the number means something.

The interval is widened when the recorded context contests a vital sign the model used.
That widening is a stated choice, not a calibration: it is reported as such.
"""

from dataclasses import dataclass

PAIN_MIN = 0.0
PAIN_MAX = 10.0
NOMINAL_LEVEL = 0.80


@dataclass
class Interval:
    point: float
    low: float
    high: float
    nominal_level: float
    observed_coverage: float | None
    widened_by: float

    @property
    def width(self) -> float:
        return round(self.high - self.low, 2)


def _clip(value: float) -> float:
    return min(max(value, PAIN_MIN), PAIN_MAX)


def build(
    point: float,
    low: float,
    high: float,
    *,
    observed_coverage: float | None = None,
    widening: float = 0.0,
) -> Interval:
    """Assemble the reported interval from the three model outputs."""
    point = _clip(point)
    # Quantile models are fitted independently, so nothing guarantees the 10th comes out
    # below the 90th on an unusual record. Sorting is the honest fix; hiding the crossing
    # would misreport the model.
    low, high = sorted((_clip(low), _clip(high)))
    low, high = min(low, point), max(high, point)

    if widening:
        half = (high - low) * widening / 2
        low, high = _clip(low - half), _clip(high + half)

    return Interval(
        point=round(point, 1),
        low=round(low, 1),
        high=round(high, 1),
        nominal_level=NOMINAL_LEVEL,
        observed_coverage=observed_coverage,
        widened_by=widening,
    )


def coverage(targets, lows, highs) -> float:
    """Share of held-out targets that fell inside their interval."""
    inside = sum(1 for y, low, high in zip(targets, lows, highs) if low <= y <= high)
    return round(inside / len(targets), 3) if len(targets) else 0.0
