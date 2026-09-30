"""Data-quality gate, run before the model is asked for anything.

Two separate jobs. It reports how complete the record is, which the clinician sees next to
the estimate. And it refuses outright when the record cannot support an estimate, because
returning a number from three fields would be worse than returning nothing.

Contradictions are reported, never resolved. If the assessment says the pain does not
radiate and also records radiating numbness, the platform says so and leaves the correction
to the clinician.
"""

from dataclasses import dataclass, field

from app.database.models import DataQuality
from app.knowledge.context import ClinicalContext

# Plausibility bounds. Outside these a value is treated as a recording error rather than a
# finding: the record keeps what was entered, and the estimate is withheld.
IMPLAUSIBLE = {
    "hr": (10.0, 300.0),
    "resp_rate": (2.0, 80.0),
    "sbp": (40.0, 300.0),
    "dbp": (20.0, 200.0),
    "spo2": (30.0, 100.0),
    "temperature_c": (25.0, 45.0),
    "glucose_mmol": (0.5, 60.0),
}

MINIMUM_VITALS = 2


@dataclass
class QualityReport:
    level: DataQuality
    completeness: float
    issues: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return not self.blocking


def _contradictions(ctx: ClinicalContext) -> list[str]:
    found = []
    if ctx.radiates is False and ctx.answers.get("BACK_RADIATION_BELOW_KNEE") is True:
        found.append(
            "Radiation is recorded as absent but the record also says the pain radiates "
            "below the knee."
        )
    if ctx.pattern == "CONSTANT" and ctx.episodes_per_day:
        found.append(
            "The pain is recorded as constant but a number of episodes per day is given."
        )
    if ctx.duration_hours is not None and ctx.duration_hours < 0:
        found.append("The duration is negative.")
    if ctx.answers.get("FIRST_EPISODE") is True and "SIMILAR_PAST_PAIN" in ctx.answers:
        found.append(
            "This is recorded as the first episode but a comparison with previous episodes "
            "has also been answered."
        )
    if "REST" in ctx.factors and "MOVEMENT_REL" in ctx.factors:
        found.append("Both rest and movement are recorded as relieving the pain.")
    for name, (low, high) in IMPLAUSIBLE.items():
        value = ctx.vitals.get(name)
        if value is not None and not low <= value <= high:
            found.append(
                f"{name} recorded as {value:g}, outside the plausible range for a person."
            )
    return found


def assess(ctx: ClinicalContext) -> QualityReport:
    missing = []
    if not ctx.pain_locations:
        missing.append("Site of the pain")
    if not ctx.qualities:
        missing.append("Character of the pain")
    if ctx.duration_hours is None and ctx.onset in (None, "UNKNOWN"):
        missing.append("Onset or duration")
    present_vitals = [name for name in IMPLAUSIBLE if ctx.vitals.get(name) is not None]
    if len(present_vitals) < MINIMUM_VITALS:
        missing.append("Vital signs (at least two)")
    if ctx.age is None:
        missing.append("Patient age")
    if not ctx.symptoms:
        missing.append("Associated symptoms, or an explicit note that there are none")

    filled = [
        bool(ctx.pain_locations),
        bool(ctx.qualities),
        ctx.duration_hours is not None or ctx.onset not in (None, "UNKNOWN"),
        ctx.pattern not in (None, "UNKNOWN"),
        ctx.course not in (None, "UNKNOWN"),
        ctx.radiates is not None,
        bool(ctx.symptoms),
        bool(ctx.factors),
        len(present_vitals) >= MINIMUM_VITALS,
        len(present_vitals) >= 4,
        ctx.age is not None,
        ctx.sex is not None,
        bool(ctx.answers),
        len(ctx.answers) >= 6,
    ]
    completeness = round(sum(filled) / len(filled), 2)

    issues = _contradictions(ctx)

    blocking = []
    if not ctx.pain_locations:
        blocking.append("No painful site is recorded.")
    if not ctx.qualities and not ctx.symptoms:
        blocking.append(
            "Neither the character of the pain nor any associated symptom is recorded."
        )
    if ctx.age is None:
        blocking.append("The patient's age is unknown, and age is a model input.")
    if completeness < 0.35:
        blocking.append(
            f"Only {int(completeness * 100)} per cent of the expected clinical fields are filled in."
        )
    for issue in issues:
        if "outside the plausible range" in issue:
            blocking.append(issue)

    if blocking:
        level = DataQuality.INSUFFICIENT
    elif completeness >= 0.8 and not issues:
        level = DataQuality.GOOD
    elif completeness >= 0.6:
        level = DataQuality.ADEQUATE
    else:
        level = DataQuality.LIMITED

    return QualityReport(
        level=level,
        completeness=completeness,
        issues=issues,
        missing=missing,
        blocking=blocking,
    )
