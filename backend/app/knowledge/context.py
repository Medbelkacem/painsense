"""The clinical picture that the configuration-driven engines are allowed to read.

One deliberate omission: the patient's self-reported NRS is not a field here. The question
engine, the rule engine and the model all take a ClinicalContext, so leaving self-report
out of this structure is what stops it reaching inference, rather than a convention that
each caller has to remember.
"""

from dataclasses import dataclass, field

from app.knowledge import anatomy, locations

VITAL_FIELDS = (
    "hr",
    "resp_rate",
    "sbp",
    "dbp",
    "spo2",
    "temperature_c",
    "glucose_mmol",
)


@dataclass
class ClinicalContext:
    age: int | None = None
    sex: str | None = None
    pain_locations: frozenset[str] = frozenset()
    # Structures localised on the 3D model. They refine pain_locations rather than
    # replacing it: every structure projects onto one of those codes on the way in.
    anatomical_structures: frozenset[str] = frozenset()
    sides: frozenset[str] = frozenset()
    qualities: frozenset[str] = frozenset()
    symptoms: frozenset[str] = frozenset()
    conditions: frozenset[str] = frozenset()
    factors: frozenset[str] = frozenset()
    confounders: frozenset[str] = frozenset()
    onset: str | None = None
    pattern: str | None = None
    course: str | None = None
    duration_hours: float | None = None
    episodes_per_day: float | None = None
    episode_minutes: float | None = None
    radiates: bool | None = None
    recent_surgery: bool = False
    recent_trauma: bool = False
    vitals: dict[str, float] = field(default_factory=dict)
    answers: dict[str, object] = field(default_factory=dict)

    @property
    def regions(self) -> frozenset[str]:
        return frozenset(locations.regions_of(list(self.pain_locations)))

    @property
    def structure_types(self) -> frozenset[str]:
        return frozenset(anatomy.types_of(self.anatomical_structures))

    @property
    def bilateral(self) -> bool:
        """Whether any recorded site is on both sides, or two sites are on opposite ones."""
        return "BILATERAL" in self.sides or {"LEFT", "RIGHT"} <= set(self.sides)


_OPERATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
}


@dataclass(frozen=True)
class Criteria:
    """A condition on a ClinicalContext.

    Every field left at its default is ignored. Within a field the entries are an
    any-of, except `all_symptoms` which requires the whole set; across fields the
    constraints are an and-of.
    """

    regions: tuple[str, ...] = ()
    pain_locations: tuple[str, ...] = ()
    qualities: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()
    all_symptoms: tuple[str, ...] = ()
    without_symptoms: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    factors: tuple[str, ...] = ()
    confounders: tuple[str, ...] = ()
    sex: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    onset: tuple[str, ...] = ()
    pattern: tuple[str, ...] = ()
    course: tuple[str, ...] = ()
    radiates: bool | None = None
    recent_surgery: bool | None = None
    recent_trauma: bool | None = None
    min_duration_hours: float | None = None
    max_duration_hours: float | None = None
    vitals: tuple[tuple[str, str, float], ...] = ()
    answer_equals: tuple[tuple[str, object], ...] = ()
    answer_present: tuple[str, ...] = ()
    answer_at_least: tuple[tuple[str, float], ...] = ()
    answer_at_most: tuple[tuple[str, float], ...] = ()

    def matches(self, ctx: ClinicalContext) -> bool:
        checks = (
            self._any(self.regions, ctx.regions),
            self._any(self.pain_locations, ctx.pain_locations),
            self._any(self.qualities, ctx.qualities),
            self._any(self.symptoms, ctx.symptoms),
            self._any(self.conditions, ctx.conditions),
            self._any(self.factors, ctx.factors),
            self._any(self.confounders, ctx.confounders),
            not self.all_symptoms or set(self.all_symptoms) <= ctx.symptoms,
            not self.without_symptoms or not (set(self.without_symptoms) & ctx.symptoms),
            self.sex is None or self.sex == ctx.sex,
            self._at_least(self.min_age, ctx.age),
            self._at_most(self.max_age, ctx.age),
            self._any(self.onset, {ctx.onset} if ctx.onset else frozenset()),
            self._any(self.pattern, {ctx.pattern} if ctx.pattern else frozenset()),
            self._any(self.course, {ctx.course} if ctx.course else frozenset()),
            self.radiates is None or self.radiates == bool(ctx.radiates),
            self.recent_surgery is None or self.recent_surgery == ctx.recent_surgery,
            self.recent_trauma is None or self.recent_trauma == ctx.recent_trauma,
            self._at_least(self.min_duration_hours, ctx.duration_hours),
            self._at_most(self.max_duration_hours, ctx.duration_hours),
            self._vitals(ctx),
            self._answers(ctx),
        )
        return all(checks)

    @staticmethod
    def _any(expected: tuple[str, ...], present: frozenset[str] | set[str]) -> bool:
        return not expected or bool(set(expected) & set(present))

    @staticmethod
    def _at_least(threshold: float | None, value: float | None) -> bool:
        # An unknown value cannot satisfy a threshold, so the criterion does not match.
        if threshold is None:
            return True
        return value is not None and value >= threshold

    @staticmethod
    def _at_most(threshold: float | None, value: float | None) -> bool:
        if threshold is None:
            return True
        return value is not None and value <= threshold

    def _vitals(self, ctx: ClinicalContext) -> bool:
        for name, operator, threshold in self.vitals:
            value = ctx.vitals.get(name)
            if value is None or not _OPERATORS[operator](value, threshold):
                return False
        return True

    def _answers(self, ctx: ClinicalContext) -> bool:
        for code in self.answer_present:
            if ctx.answers.get(code) in (None, "", [], False):
                return False
        for code, expected in self.answer_equals:
            given = ctx.answers.get(code)
            if isinstance(given, list):
                if expected not in given:
                    return False
            elif given != expected:
                return False
        for code, threshold in self.answer_at_least:
            if not self._numeric_at_least(ctx.answers.get(code), threshold):
                return False
        for code, threshold in self.answer_at_most:
            given = ctx.answers.get(code)
            if not isinstance(given, (int, float)) or given > threshold:
                return False
        return True

    @staticmethod
    def _numeric_at_least(given: object, threshold: float) -> bool:
        return (
            isinstance(given, (int, float))
            and not isinstance(given, bool)
            and given >= threshold
        )


_SET_FIELDS = (
    "pain_locations",
    "anatomical_structures",
    "sides",
    "qualities",
    "symptoms",
    "conditions",
    "factors",
    "confounders",
)
_SCALAR_FIELDS = (
    "age",
    "sex",
    "onset",
    "pattern",
    "course",
    "duration_hours",
    "episodes_per_day",
    "episode_minutes",
    "radiates",
    "recent_surgery",
    "recent_trauma",
)


def to_dict(ctx: ClinicalContext) -> dict:
    """Plain-JSON form of a context, used by the dataset files."""
    payload = {name: getattr(ctx, name) for name in _SCALAR_FIELDS}
    payload.update({name: sorted(getattr(ctx, name)) for name in _SET_FIELDS})
    payload["vitals"] = dict(ctx.vitals)
    payload["answers"] = dict(ctx.answers)
    return payload


def from_dict(payload: dict) -> ClinicalContext:
    values = {name: payload.get(name) for name in _SCALAR_FIELDS}
    values.update({name: frozenset(payload.get(name) or ()) for name in _SET_FIELDS})
    values["vitals"] = dict(payload.get("vitals") or {})
    values["answers"] = dict(payload.get("answers") or {})
    return ClinicalContext(**values)
