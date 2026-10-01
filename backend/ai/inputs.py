from statistics import median

from database.models import PainAssessment
from knowledge import profiles
from knowledge.context import (
    FUNCTIONAL_DOMAINS,
    ClinicalContext,
    MedicationContext,
    SiteContext,
)

VITAL_COLUMNS = ("hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c", "glucose_mmol")
BASELINE_VITALS = ("hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c")

CALIBRATION = "CALIBRATION"
EARLIER_VISITS = "EARLIER_VISITS"


def _vitals(assessment: PainAssessment) -> dict[str, float]:
    measurement = assessment.measurement
    vitals: dict[str, float] = {}
    if measurement is None:
        return vitals
    for name in VITAL_COLUMNS:
        value = getattr(measurement, name)
        if value is not None:
            vitals[name] = float(value)
    if measurement.bmi is not None:
        vitals["bmi"] = float(measurement.bmi)
    return vitals


def _timing(assessment: PainAssessment) -> frozenset[str]:
    flags = (
        ("MORNING", assessment.morning_pain),
        ("AFTERNOON", assessment.afternoon_pain),
        ("EVENING", assessment.evening_pain),
        ("NIGHT", assessment.night_pain),
        ("VARIABLE", assessment.variable_timing),
        ("AT_REST", assessment.pain_at_rest),
        ("AFTER_ACTIVITY", assessment.pain_after_activity),
    )
    return frozenset(code for code, on in flags if on)


def _sites(assessment: PainAssessment) -> tuple[SiteContext, ...]:
    rows = sorted(
        assessment.anatomical_sites, key=lambda row: (row.sequence, row.structure_code)
    )
    return tuple(
        SiteContext(
            code=row.structure_code,
            side=row.side,
            role=row.role.value,
            qualities=frozenset(row.quality_codes or ()),
            onset=None if row.onset.value == "UNKNOWN" else row.onset.value,
            pattern=None if row.pattern.value == "UNKNOWN" else row.pattern.value,
            course=None if row.course.value == "UNKNOWN" else row.course.value,
            radiation_from=(
                f"{row.radiation_from_code}|{row.radiation_from_side}"
                if row.radiation_from_code
                else None
            ),
        )
        for row in rows
    )


def _medications(assessment: PainAssessment) -> tuple[MedicationContext, ...]:
    return tuple(
        MedicationContext(
            class_code=row.class_code,
            dose_category=row.dose_category,
            frequency=row.frequency,
            hours_since_last_dose=row.hours_since_last_dose,
            pain_effect=row.pain_effect,
            sedation_effect=row.sedation_effect,
        )
        for row in assessment.medications
    )


def _functional_impact(assessment: PainAssessment) -> dict[str, int]:
    scores = {}
    for domain in FUNCTIONAL_DOMAINS:
        value = getattr(assessment, f"impact_{domain}")
        if value is not None:
            scores[domain] = int(value)
    return scores


def _age(assessment: PainAssessment) -> float | None:
    years = assessment.patient_age_years
    months = assessment.patient_age_months
    if months is not None and (years is None or years < profiles.MONTH_PRECISION_UNDER_YEARS):
        return round(months / 12, 4)
    return float(years) if years is not None else None


def _baseline(assessment: PainAssessment) -> tuple[dict[str, float], int, str | None]:
    """This patient's resting values. A calibration taken at rest wins over the median of
    earlier visits, because a visit is not a resting state. Returns nothing rather than a
    guess when neither is available."""
    calibration = assessment.patient.baseline
    if calibration is not None and calibration.vitals:
        return calibration.vitals, max(calibration.readings, 1), CALIBRATION

    readings: dict[str, list[float]] = {name: [] for name in BASELINE_VITALS}
    visits = 0
    for other in assessment.patient.assessments:
        if other.id == assessment.id or other.created_at >= assessment.created_at:
            continue
        if other.measurement is None:
            continue
        visits += 1
        for name in BASELINE_VITALS:
            value = getattr(other.measurement, name)
            if value is not None:
                readings[name].append(float(value))

    vitals = {
        name: round(float(median(values)), 2) for name, values in readings.items() if values
    }
    if not vitals:
        return {}, 0, None
    return vitals, visits, EARLIER_VISITS


def _behaviour(assessment: PainAssessment) -> tuple[dict[str, float], frozenset[str]]:
    """What a camera and a microphone measured during this assessment.

    The most recent usable observation recorded against it, not a pooling of all of them.
    Two clips taken ten minutes apart are two readings of a changing state, and averaging
    them would blur a worsening into a middle value; the latest is the one the estimate is
    about. Observations recorded at rest are excluded here — those are the reference, not
    the reading.
    """
    usable = [
        row
        for row in assessment.observations
        if not row.at_rest and row.measures and row.usable_modalities
    ]
    if not usable:
        return {}, frozenset()
    latest = max(usable, key=lambda row: row.recorded_at)
    measures = {
        name: float(value)
        for name, value in (latest.measures or {}).items()
        if value is not None
    }
    return measures, frozenset(latest.usable_modalities or ())


def _resting_behaviour(assessment: PainAssessment) -> dict[str, float]:
    baseline = assessment.patient.baseline
    return dict(baseline.behaviour) if baseline is not None else {}


def context_for(assessment: PainAssessment) -> ClinicalContext:
    sides = {row.side for row in assessment.locations}
    sides.update(row.side for row in assessment.anatomical_sites)

    age = _age(assessment)
    baseline_vitals, baseline_points, baseline_source = _baseline(assessment)
    behaviour, behaviour_modalities = _behaviour(assessment)
    primary = profiles.resolve(
        assessment.profile_code or assessment.patient.profile_code,
        assessment.profile_modifiers or (),
        age=age,
    )

    return ClinicalContext(
        age=age,
        sex=assessment.patient.sex.value if assessment.patient.sex else None,
        pain_locations=frozenset(row.location_code for row in assessment.locations),
        anatomical_structures=frozenset(
            row.structure_code for row in assessment.anatomical_sites
        ),
        sides=frozenset(sides),
        sites=_sites(assessment),
        qualities=frozenset(row.quality_code for row in assessment.qualities),
        symptoms=frozenset(row.symptom_code for row in assessment.symptoms),
        conditions=frozenset(row.disease_code for row in assessment.patient.conditions),
        factors=frozenset(row.factor_code for row in assessment.factors),
        confounders=frozenset(row.confounder_code for row in assessment.confounders),
        medications=_medications(assessment),
        onset=assessment.onset.value,
        onset_speed=assessment.onset_speed.value,
        pattern=assessment.pattern.value,
        course=assessment.course.value,
        recurrent=assessment.recurrent,
        timing=_timing(assessment),
        duration_hours=assessment.duration_hours,
        episodes_per_day=assessment.episodes_per_day,
        episode_minutes=assessment.episode_minutes,
        radiates=assessment.radiates,
        recent_trauma=assessment.recent_trauma,
        recent_surgery=assessment.recent_surgery,
        functional_impact=_functional_impact(assessment),
        vitals=_vitals(assessment),
        answers={row.question_code: row.value for row in assessment.answers},
        profile=primary.code,
        profile_modifiers=frozenset(assessment.profile_modifiers or ()),
        pregnancy_trimester=assessment.pregnancy_trimester,
        expected_pain=assessment.expected_pain,
        baseline_vitals=baseline_vitals,
        baseline_points=baseline_points,
        baseline_source=baseline_source,
        behaviour=behaviour,
        behaviour_baseline=_resting_behaviour(assessment),
        behaviour_modalities=behaviour_modalities,
    )
