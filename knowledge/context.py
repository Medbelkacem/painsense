from dataclasses import dataclass, field

from knowledge import anatomy, locations, medications

FUNCTIONAL_DOMAINS = ("mobility", "sleep", "work", "daily_activity", "self_care")
FUNCTIONAL_DOMAIN_LABELS = {
    "mobility": "Mobility",
    "sleep": "Sleep",
    "work": "Work",
    "daily_activity": "Daily activities",
    "self_care": "Self-care",
}
FUNCTIONAL_MAX = 4

TIMINGS = ("MORNING", "AFTERNOON", "EVENING", "NIGHT", "VARIABLE")
ONSET_SPEEDS = ("SECONDS", "MINUTES", "HOURS", "DAYS", "WEEKS_OR_MORE", "UNKNOWN")
SITE_ROLES = ("PRIMARY", "SECONDARY", "RADIATING", "REFERRED")

VITAL_FIELDS = (
    "hr",
    "resp_rate",
    "sbp",
    "dbp",
    "spo2",
    "temperature_c",
    "glucose_mmol",
)


@dataclass(frozen=True)
class SiteContext:
    code: str
    side: str
    role: str = "SECONDARY"
    qualities: frozenset[str] = frozenset()
    onset: str | None = None
    pattern: str | None = None
    course: str | None = None
    radiation_from: str | None = None


@dataclass(frozen=True)
class MedicationContext:
    class_code: str
    dose_category: str = "UNKNOWN"
    frequency: str = "UNKNOWN"
    hours_since_last_dose: float | None = None
    pain_effect: str = "UNKNOWN"
    sedation_effect: str = "UNKNOWN"


@dataclass
class ClinicalContext:
    age: int | None = None
    sex: str | None = None
    pain_locations: frozenset[str] = frozenset()

    anatomical_structures: frozenset[str] = frozenset()
    sides: frozenset[str] = frozenset()

    sites: tuple[SiteContext, ...] = ()
    qualities: frozenset[str] = frozenset()
    symptoms: frozenset[str] = frozenset()
    conditions: frozenset[str] = frozenset()
    factors: frozenset[str] = frozenset()
    confounders: frozenset[str] = frozenset()
    medications: tuple[MedicationContext, ...] = ()
    onset: str | None = None
    onset_speed: str | None = None
    pattern: str | None = None
    course: str | None = None
    recurrent: bool = False
    timing: frozenset[str] = frozenset()
    duration_hours: float | None = None
    episodes_per_day: float | None = None
    episode_minutes: float | None = None
    radiates: bool | None = None
    recent_surgery: bool = False
    recent_trauma: bool = False

    functional_impact: dict[str, int] = field(default_factory=dict)
    vitals: dict[str, float] = field(default_factory=dict)
    answers: dict[str, object] = field(default_factory=dict)

    # Which population this patient is read as. None means age decides.
    profile: str | None = None
    profile_modifiers: frozenset[str] = frozenset()
    pregnancy_trimester: int | None = None
    # Pain the clinician expects for the situation, such as contractions in labour.
    # Recorded so an expected pain is not reported as an unexplained finding.
    expected_pain: bool = False

    # This patient's own resting values, from a calibration at rest or from the median of
    # earlier visits. What the vitals are read against, rather than a population band.
    baseline_vitals: dict[str, float] = field(default_factory=dict)
    baseline_points: int = 0
    baseline_source: str | None = None

    # What a camera and a microphone measured during the examination, under the codes in
    # app.behaviour.schema: how open the eyes were, how often they closed, what the pupils
    # were doing, where the brow sat, how the voice sounded. Empty when no clip was
    # recorded, which is the ordinary case and not a gap to be filled in.
    behaviour: dict[str, float] = field(default_factory=dict)
    # The same measures from an observation recorded with the patient at rest. Orbital
    # tightening and brow lowering are changes from these.
    behaviour_baseline: dict[str, float] = field(default_factory=dict)
    # Which modalities the quality gate allowed. A clip whose eyes were never open
    # contributes a voice and no eyes, and this is how that is visible.
    behaviour_modalities: frozenset[str] = frozenset()

    @property
    def regions(self) -> frozenset[str]:
        return frozenset(locations.regions_of(list(self.pain_locations)))

    @property
    def structure_types(self) -> frozenset[str]:
        return frozenset(anatomy.types_of(self.anatomical_structures))

    @property
    def bilateral(self) -> bool:
        return "BILATERAL" in self.sides or {"LEFT", "RIGHT"} <= set(self.sides)

    def sites_with_role(self, role: str) -> tuple[SiteContext, ...]:
        return tuple(site for site in self.sites if site.role == role)

    @property
    def radiation_chain_length(self) -> int:
        by_key = {(site.code, site.side): site for site in self.sites}
        longest = 0
        for site in self.sites:
            length, current, seen = 0, site, set()
            while (
                current is not None
                and current.radiation_from
                and (current.code, current.side) not in seen
            ):
                seen.add((current.code, current.side))
                origin_code, _, origin_side = current.radiation_from.partition("|")
                current = by_key.get((origin_code, origin_side))
                length += 1
            longest = max(longest, length)
        return longest

    @property
    def functional_mean(self) -> float | None:
        scores = [
            self.functional_impact[d] for d in FUNCTIONAL_DOMAINS if d in self.functional_impact
        ]
        return sum(scores) / len(scores) if scores else None

    @property
    def medication_classes(self) -> frozenset[str]:
        return frozenset(entry.class_code for entry in self.medications)

    def relative_change(self, name: str) -> float | None:
        """How far a vital sits from this patient's own resting value, as a fraction of
        it. None when either side is missing, which keeps a missing baseline missing
        rather than turning it into a zero change."""
        baseline = self.baseline_vitals.get(name)
        current = self.vitals.get(name)
        if baseline is None or current is None or baseline == 0:
            return None
        return (current - baseline) / abs(baseline)

    def absolute_change(self, name: str) -> float | None:
        baseline = self.baseline_vitals.get(name)
        current = self.vitals.get(name)
        if baseline is None or current is None:
            return None
        return current - baseline

    def behaviour_change(self, name: str) -> float | None:
        """How far a behavioural measure sits from this patient's own resting value, as a
        fraction of it. None when either side is missing, which keeps an unrecorded
        baseline missing rather than turning it into a zero change."""
        resting = self.behaviour_baseline.get(name)
        current = self.behaviour.get(name)
        if resting is None or current is None or resting == 0:
            return None
        return (current - resting) / abs(resting)

    @property
    def observed(self) -> bool:
        """True where a camera-and-microphone observation contributed anything."""
        return bool(self.behaviour)

    @property
    def on_analgesia(self) -> bool:
        return bool(self.medication_classes & medications.ANALGESIC)

    @property
    def hours_since_analgesia(self) -> float | None:
        timed = [
            entry.hours_since_last_dose
            for entry in self.medications
            if entry.class_code in medications.ANALGESIC
            and entry.hours_since_last_dose is not None
        ]
        return min(timed) if timed else None

    @property
    def analgesia_effect(self) -> str | None:
        order = {"NONE": 0, "PARTIAL": 1, "GOOD": 2}
        rated = [
            entry.pain_effect
            for entry in self.medications
            if entry.class_code in medications.ANALGESIC and entry.pain_effect in order
        ]
        return max(rated, key=order.get) if rated else None


_OPERATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
}


@dataclass(frozen=True)
class Criteria:
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
    impact_at_least: tuple[tuple[str, int], ...] = ()
    medication_classes: tuple[str, ...] = ()
    onset_speed: tuple[str, ...] = ()
    site_roles: tuple[str, ...] = ()

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
            self._impact(ctx),
            self._any(self.medication_classes, ctx.medication_classes),
            self._any(self.onset_speed, {ctx.onset_speed} if ctx.onset_speed else frozenset()),
            self._any(self.site_roles, {site.role for site in ctx.sites}),
        )
        return all(checks)

    def _impact(self, ctx: ClinicalContext) -> bool:
        for domain, threshold in self.impact_at_least:
            score = ctx.functional_impact.get(domain)
            if score is None or score < threshold:
                return False
        return True

    @staticmethod
    def _any(expected: tuple[str, ...], present: frozenset[str] | set[str]) -> bool:
        return not expected or bool(set(expected) & set(present))

    @staticmethod
    def _at_least(threshold: float | None, value: float | None) -> bool:
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
_SET_FIELDS = _SET_FIELDS + ("timing", "profile_modifiers", "behaviour_modalities")
_SCALAR_FIELDS = (
    "age",
    "sex",
    "onset",
    "onset_speed",
    "pattern",
    "course",
    "recurrent",
    "duration_hours",
    "episodes_per_day",
    "episode_minutes",
    "radiates",
    "recent_surgery",
    "recent_trauma",
    "profile",
    "pregnancy_trimester",
    "expected_pain",
    "baseline_points",
    "baseline_source",
)


def _site_to_dict(site: SiteContext) -> dict:
    return {
        "code": site.code,
        "side": site.side,
        "role": site.role,
        "qualities": sorted(site.qualities),
        "onset": site.onset,
        "pattern": site.pattern,
        "course": site.course,
        "radiation_from": site.radiation_from,
    }


def _site_from_dict(payload: dict) -> SiteContext:
    return SiteContext(
        code=payload["code"],
        side=payload.get("side", "MIDLINE"),
        role=payload.get("role", "SECONDARY"),
        qualities=frozenset(payload.get("qualities") or ()),
        onset=payload.get("onset"),
        pattern=payload.get("pattern"),
        course=payload.get("course"),
        radiation_from=payload.get("radiation_from"),
    )


def _medication_to_dict(entry: MedicationContext) -> dict:
    return {
        "class_code": entry.class_code,
        "dose_category": entry.dose_category,
        "frequency": entry.frequency,
        "hours_since_last_dose": entry.hours_since_last_dose,
        "pain_effect": entry.pain_effect,
        "sedation_effect": entry.sedation_effect,
    }


def _medication_from_dict(payload: dict) -> MedicationContext:
    return MedicationContext(
        class_code=payload["class_code"],
        dose_category=payload.get("dose_category", "UNKNOWN"),
        frequency=payload.get("frequency", "UNKNOWN"),
        hours_since_last_dose=payload.get("hours_since_last_dose"),
        pain_effect=payload.get("pain_effect", "UNKNOWN"),
        sedation_effect=payload.get("sedation_effect", "UNKNOWN"),
    )


def to_dict(ctx: ClinicalContext) -> dict:
    payload = {name: getattr(ctx, name) for name in _SCALAR_FIELDS}
    payload.update({name: sorted(getattr(ctx, name)) for name in _SET_FIELDS})
    payload["sites"] = [_site_to_dict(site) for site in ctx.sites]
    payload["medications"] = [_medication_to_dict(entry) for entry in ctx.medications]
    payload["functional_impact"] = dict(ctx.functional_impact)
    payload["vitals"] = dict(ctx.vitals)
    payload["answers"] = dict(ctx.answers)
    payload["baseline_vitals"] = dict(ctx.baseline_vitals)
    payload["behaviour"] = dict(ctx.behaviour)
    payload["behaviour_baseline"] = dict(ctx.behaviour_baseline)
    return payload


def from_dict(payload: dict) -> ClinicalContext:
    values = {name: payload.get(name) for name in _SCALAR_FIELDS}
    values["recurrent"] = bool(payload.get("recurrent"))
    values["recent_surgery"] = bool(payload.get("recent_surgery"))
    values["recent_trauma"] = bool(payload.get("recent_trauma"))
    values.update({name: frozenset(payload.get(name) or ()) for name in _SET_FIELDS})
    values["sites"] = tuple(_site_from_dict(site) for site in payload.get("sites") or ())
    values["medications"] = tuple(
        _medication_from_dict(entry) for entry in payload.get("medications") or ()
    )
    values["functional_impact"] = {
        domain: int(score)
        for domain, score in (payload.get("functional_impact") or {}).items()
        if score is not None
    }
    values["vitals"] = dict(payload.get("vitals") or {})
    values["answers"] = dict(payload.get("answers") or {})
    values["baseline_vitals"] = dict(payload.get("baseline_vitals") or {})
    values["behaviour"] = dict(payload.get("behaviour") or {})
    values["behaviour_baseline"] = dict(payload.get("behaviour_baseline") or {})
    values["expected_pain"] = bool(payload.get("expected_pain"))
    values["baseline_points"] = int(payload.get("baseline_points") or 0)
    return ClinicalContext(**values)
