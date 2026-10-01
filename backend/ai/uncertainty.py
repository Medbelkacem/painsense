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
    point = _clip(point)

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
    inside = sum(1 for y, low, high in zip(targets, lows, highs) if low <= y <= high)
    return round(inside / len(targets), 3) if len(targets) else 0.0
