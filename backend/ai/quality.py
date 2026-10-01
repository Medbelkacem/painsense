from dataclasses import dataclass, field

from database.models import DataQuality
from knowledge import profiles, reference_ranges
from knowledge.context import (
    FUNCTIONAL_DOMAIN_LABELS,
    FUNCTIONAL_DOMAINS,
    VITAL_FIELDS,
    ClinicalContext,
)

# What any input field has to accept, before a profile is known: the union of every
# band's limits, so a newborn's respiratory rate is not refused for being adult-impossible.
IMPLAUSIBLE = reference_ranges.widest_plausible()

# The adult tiers, for a caller with no patient in hand. Anything holding a context reads
# the tiers for that patient's band instead.
OUTLIER = reference_ranges.outlier(reference_ranges.ADULT_BAND)

VITAL_LABELS = {
    "hr": "Heart rate",
    "resp_rate": "Respiratory rate",
    "sbp": "Systolic blood pressure",
    "dbp": "Diastolic blood pressure",
    "spo2": "Oxygen saturation",
    "temperature_c": "Temperature",
    "glucose_mmol": "Blood glucose",
    "bmi": "Body mass index",
}

MINIMUM_VITALS = 2
BLOCKING_COMPLETENESS = 0.35


@dataclass
class QualityReport:
    level: DataQuality
    completeness: float
    issues: list[str] = field(default_factory=list)
    outliers: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return not self.blocking

    @property
    def score(self) -> float:
        penalty = 0.08 * len(self.issues) + 0.03 * len(self.outliers)
        return round(max(0.0, min(1.0, self.completeness - penalty)), 2)


def _contradictions(ctx: ClinicalContext) -> list[str]:
    plausible = profiles.plausible_ranges(ctx)
    found = []
    if ctx.radiates is False and ctx.answers.get("BACK_RADIATION_BELOW_KNEE") is True:
        found.append(
            "Radiation is recorded as absent but the record also says the pain radiates "
            "below the knee."
        )
    if ctx.radiates is False and ctx.sites_with_role("RADIATING"):
        found.append("Radiation is recorded as absent but a site is marked as radiating pain.")
    if ctx.pattern == "CONSTANT" and ctx.episodes_per_day:
        found.append(
            "The pain is recorded as constant but a number of episodes per day is given."
        )
    if ctx.duration_hours is not None and ctx.duration_hours < 0:
        found.append("The duration is negative.")
    if ctx.onset_speed == "SECONDS" and ctx.onset == "GRADUAL":
        found.append(
            "The onset is recorded as gradual but as reaching full intensity in seconds."
        )
    if ctx.answers.get("FIRST_EPISODE") is True and "SIMILAR_PAST_PAIN" in ctx.answers:
        found.append(
            "This is recorded as the first episode but a comparison with previous episodes "
            "has also been answered."
        )
    if ctx.answers.get("FIRST_EPISODE") is True and ctx.recurrent:
        found.append("This is recorded as the first episode and also as recurrent.")
    if "REST" in ctx.factors and "MOVEMENT_REL" in ctx.factors:
        found.append("Both rest and movement are recorded as relieving the pain.")
    if ctx.sites and not ctx.sites_with_role("PRIMARY"):
        found.append("Sites are recorded but none is marked as the primary site.")
    by_key = {(site.code, site.side) for site in ctx.sites}
    for site in ctx.sites_with_role("RADIATING"):
        if site.radiation_from:
            origin_code, _, origin_side = site.radiation_from.partition("|")
            if (origin_code, origin_side) not in by_key:
                found.append(
                    "A radiating site names an origin that is not among the recorded sites."
                )
                break
    for entry in ctx.medications:
        if entry.hours_since_last_dose is not None and entry.hours_since_last_dose < 0:
            found.append("A medication is recorded as last taken in the future.")
            break
    band = profiles.band_for(profiles.primary_of(ctx), ctx.age)
    for name, (low, high) in plausible.items():
        value = ctx.vitals.get(name)
        if value is not None and not low <= value <= high:
            found.append(
                f"{VITAL_LABELS[name]} recorded as {value:g}, outside the plausible range "
                f"for {band.label.lower()}."
            )
    systolic, diastolic = ctx.vitals.get("sbp"), ctx.vitals.get("dbp")
    if systolic is not None and diastolic is not None and diastolic >= systolic:
        found.append("Diastolic pressure is recorded at or above systolic pressure.")
    return found


def _outliers(ctx: ClinicalContext) -> list[str]:
    band = profiles.band_for(profiles.primary_of(ctx), ctx.age)
    limits = reference_ranges.plausible(band)
    found = []
    for name, (low, high) in reference_ranges.outlier(band).items():
        value = ctx.vitals.get(name)
        if value is None:
            continue
        plausible = limits.get(name)
        if plausible and not plausible[0] <= value <= plausible[1]:
            continue
        if not low <= value <= high:
            found.append(
                f"{VITAL_LABELS[name]} of {value:g} is unusual. Confirm the entry before "
                "reading anything into it."
            )
    if ctx.duration_hours is not None and ctx.duration_hours > 24 * 365 * 30:
        found.append("A duration of more than thirty years was recorded. Confirm the units.")
    if ctx.age is not None and ctx.age > 105:
        found.append(f"An age of {ctx.age} was recorded. Confirm the date of birth.")
    return found


def _missing(ctx: ClinicalContext, present_vitals: list[str]) -> list[str]:
    missing = []
    if not ctx.pain_locations:
        missing.append("Site of the pain")
    if not ctx.qualities and not any(site.qualities for site in ctx.sites):
        missing.append("Character of the pain")
    if ctx.duration_hours is None:
        missing.append("Pain duration")
    if ctx.onset in (None, "UNKNOWN"):
        missing.append("Onset")
    if ctx.pattern in (None, "UNKNOWN"):
        missing.append("Pattern over time")
    if ctx.course in (None, "UNKNOWN"):
        missing.append("Course since onset")
    for name in ("hr", "resp_rate", "sbp", "spo2", "temperature_c"):
        if name not in present_vitals:
            missing.append(VITAL_LABELS[name])
    if ctx.age is None:
        missing.append("Patient age")
    if not ctx.symptoms:
        missing.append("Associated symptoms, or an explicit note that there are none")
    for domain in FUNCTIONAL_DOMAINS:
        if domain not in ctx.functional_impact:
            missing.append(f"Functional impact: {FUNCTIONAL_DOMAIN_LABELS[domain].lower()}")
    if ctx.medications and ctx.hours_since_analgesia is None and ctx.on_analgesia:
        missing.append("Medication timing")
    return missing


def assess(ctx: ClinicalContext) -> QualityReport:
    present_vitals = [name for name in VITAL_FIELDS if ctx.vitals.get(name) is not None]
    scored_domains = sum(1 for domain in FUNCTIONAL_DOMAINS if domain in ctx.functional_impact)

    filled = [
        bool(ctx.pain_locations),
        bool(ctx.qualities) or any(site.qualities for site in ctx.sites),
        ctx.duration_hours is not None,
        ctx.onset not in (None, "UNKNOWN"),
        ctx.pattern not in (None, "UNKNOWN"),
        ctx.course not in (None, "UNKNOWN"),
        ctx.radiates is not None,
        bool(ctx.symptoms),
        bool(ctx.factors),
        len(present_vitals) >= MINIMUM_VITALS,
        len(present_vitals) >= 4,
        "resp_rate" in present_vitals,
        ctx.age is not None,
        ctx.sex is not None,
        scored_domains >= 1,
        scored_domains == len(FUNCTIONAL_DOMAINS),
        bool(ctx.medications) or ctx.answers.get("REGULAR_MEDICATION") is False,
        bool(ctx.answers),
        len(ctx.answers) >= 4,
    ]
    completeness = round(sum(filled) / len(filled), 2)

    issues = _contradictions(ctx)
    outliers = _outliers(ctx)
    missing = _missing(ctx, present_vitals)

    blocking = []
    if not ctx.pain_locations:
        blocking.append("No painful site is recorded.")
    if not ctx.qualities and not ctx.symptoms and not any(site.qualities for site in ctx.sites):
        blocking.append(
            "Neither the character of the pain nor any associated symptom is recorded."
        )
    if ctx.age is None:
        blocking.append("The patient's age is unknown, and age is a model input.")
    if completeness < BLOCKING_COMPLETENESS:
        blocking.append(
            f"Only {int(completeness * 100)} per cent of the expected clinical fields are filled in."
        )
    for issue in issues:
        if "plausible range" in issue:
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
        outliers=outliers,
        missing=missing,
        blocking=blocking,
    )
