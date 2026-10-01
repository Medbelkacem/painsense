from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from statistics import median

CHANGE_THRESHOLD = 0.5
FLUCTUATION_THRESHOLD = 1.0
BASELINE_MINIMUM_POINTS = 2

# A series has to move by more than this between two points for the step to count as a
# direction rather than as noise around a plateau.
PHASE_THRESHOLD = 0.5
# An episode opens when the series reaches this and closes when it falls back below it.
# 3.5 is the bottom of the MILD band in knowledge.rules, so an episode is a stretch the
# platform would not call "no pain".
EPISODE_THRESHOLD = 3.5

BASELINE_TOLERANCE = {
    "hr": 0.15,
    "resp_rate": 0.25,
    "sbp": 0.15,
    "dbp": 0.15,
    "spo2": 0.03,
    "temperature_c": 0.02,
    "glucose_mmol": 0.30,
}

IMPROVING = "IMPROVING"
WORSENING = "WORSENING"
STABLE = "STABLE"
FLUCTUATING = "FLUCTUATING"
UNKNOWN = "UNKNOWN"

RISING = "RISING"
FALLING = "FALLING"
PLATEAU = "PLATEAU"


@dataclass(frozen=True)
class EarlierAssessment:
    created_at: datetime
    estimated_pain: float | None
    vitals: dict[str, float]


@dataclass
class Phase:
    direction: str
    # Indices into the series the phase spans, inclusive.
    start: int
    end: int
    from_pain: float
    to_pain: float

    @property
    def change(self) -> float:
        return round(self.to_pain - self.from_pain, 1)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "start": self.start,
            "end": self.end,
            "from_pain": self.from_pain,
            "to_pain": self.to_pain,
            "change": self.change,
        }


@dataclass
class Episode:
    start: int
    end: int
    peak: float
    points: int
    # False while the series is still above the threshold at its last point, so a current
    # episode is not reported as resolved.
    resolved: bool

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "peak": self.peak,
            "points": self.points,
            "resolved": self.resolved,
        }


@dataclass
class BaselineComparison:
    trajectory: str = UNKNOWN
    previous_pain: float | None = None
    pain_change: float | None = None
    points_compared: int = 0

    vitals: dict[str, dict[str, float]] = field(default_factory=dict)

    departures: list[str] = field(default_factory=list)
    source: str | None = None
    phases: list[Phase] = field(default_factory=list)
    episodes: list[Episode] = field(default_factory=list)

    @property
    def current_episode(self) -> Episode | None:
        return next((e for e in reversed(self.episodes) if not e.resolved), None)

    def to_dict(self) -> dict:
        return {
            "trajectory": self.trajectory,
            "previous_pain": self.previous_pain,
            "pain_change": self.pain_change,
            "points_compared": self.points_compared,
            "vitals": self.vitals,
            "departures": self.departures,
            "source": self.source,
            "phases": [phase.to_dict() for phase in self.phases],
            "episodes": [episode.to_dict() for episode in self.episodes],
        }


def _trajectory(history: list[float], current: float) -> str:
    if not history:
        return UNKNOWN
    series = history[-2:] + [current]
    steps = [later - earlier for earlier, later in pairwise(series)]
    last = steps[-1]
    if (
        len(steps) == 2
        and steps[0] * steps[1] < 0
        and all(abs(step) >= FLUCTUATION_THRESHOLD for step in steps)
    ):
        return FLUCTUATING
    if last > CHANGE_THRESHOLD:
        return WORSENING
    if last < -CHANGE_THRESHOLD:
        return IMPROVING
    return STABLE


def _direction(change: float) -> str:
    if change > PHASE_THRESHOLD:
        return RISING
    if change < -PHASE_THRESHOLD:
        return FALLING
    return PLATEAU


def phases(series: list[float]) -> list[Phase]:
    """Split a series into stretches that move the same way. Two points give one phase;
    one point gives none, because a single reading has no direction."""
    if len(series) < 2:
        return []

    found: list[Phase] = []
    start = 0
    direction = _direction(series[1] - series[0])
    for index in range(1, len(series)):
        step = _direction(series[index] - series[index - 1])
        if step != direction:
            found.append(
                Phase(
                    direction,
                    start,
                    index - 1,
                    round(series[start], 1),
                    round(series[index - 1], 1),
                )
            )
            start = index - 1
            direction = step
    found.append(
        Phase(direction, start, len(series) - 1, round(series[start], 1), round(series[-1], 1))
    )
    return found


def episodes(series: list[float], threshold: float = EPISODE_THRESHOLD) -> list[Episode]:
    """Stretches where the series sits at or above the threshold. An episode still open at
    the last point is reported as unresolved rather than closed at that point."""
    found: list[Episode] = []
    start: int | None = None
    peak = 0.0

    for index, value in enumerate(series):
        if value >= threshold:
            if start is None:
                start, peak = index, value
            else:
                peak = max(peak, value)
        elif start is not None:
            found.append(
                Episode(start, index - 1, round(peak, 1), index - start, resolved=True)
            )
            start = None

    if start is not None:
        found.append(
            Episode(
                start,
                len(series) - 1,
                round(peak, 1),
                len(series) - start,
                resolved=False,
            )
        )
    return found


def compare(
    earlier: list[EarlierAssessment],
    current_pain: float | None,
    current_vitals: dict[str, float],
    baseline: dict[str, float] | None = None,
) -> BaselineComparison:
    """Where this visit sits against the patient's own history.

    `baseline` is the patient's resting values where a calibration gave them. It wins over
    the median of earlier visits, because a visit is not a resting state and a calibration
    is. Without either, the vital comparison is simply not made.
    """
    ordered = sorted(earlier, key=lambda entry: entry.created_at)
    pains = [entry.estimated_pain for entry in ordered if entry.estimated_pain is not None]

    result = BaselineComparison(points_compared=len(ordered))
    if current_pain is not None and pains:
        result.trajectory = _trajectory(pains, current_pain)
        result.previous_pain = pains[-1]
        result.pain_change = round(current_pain - pains[-1], 1)

    series = pains + ([current_pain] if current_pain is not None else [])
    result.phases = phases(series)
    result.episodes = episodes(series)

    calibrated = bool(baseline)
    result.source = "CALIBRATION" if calibrated else ("EARLIER_VISITS" if ordered else None)

    for name, tolerance in BASELINE_TOLERANCE.items():
        current = current_vitals.get(name)
        if current is None:
            continue

        if calibrated and name in baseline:
            resting = float(baseline[name])
            readings = 1
        else:
            values = [entry.vitals[name] for entry in ordered if name in entry.vitals]
            if len(values) < BASELINE_MINIMUM_POINTS:
                continue
            resting = float(median(values))
            readings = len(values)

        delta = current - resting
        result.vitals[name] = {
            "baseline": round(resting, 1),
            "current": round(current, 1),
            "delta": round(delta, 1),
            "readings": readings,
        }
        if resting and abs(delta) / abs(resting) > tolerance:
            result.departures.append(name)
    return result
