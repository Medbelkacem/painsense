import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from knowledge import (
    anatomy,
    diseases,
    factors,
    medications,
    profiles,
    qualities,
    reference_ranges,
    rules,
    symptoms,
)
from knowledge.context import FUNCTIONAL_DOMAINS, ClinicalContext

# 3 added the baseline-relative changes, the position of a vital inside its profile band,
# and the profile flags. 4 added what a camera and a microphone measure: the eyes, the
# brow, the mouth, head movement and the voice. A model fitted on an earlier version is
# refused rather than reused — it would accept the right number of columns and mean
# something different by them.
FEATURE_SCHEMA_VERSION = "4"

# Vitals the platform reasons about in relative terms as well as absolute ones.
RELATIVE_VITALS = ("hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c")
# Vitals with a resting band in enough profiles for a within-band position to mean
# something.
BANDED_VITALS = ("hr", "resp_rate", "sbp", "temperature_c")

NAN = float("nan")

ONSET_SPEED_SCALE = {
    "SECONDS": 0.0,
    "MINUTES": 1.0,
    "HOURS": 2.0,
    "DAYS": 3.0,
    "WEEKS_OR_MORE": 4.0,
}
ANALGESIA_EFFECT_SCALE = {"NONE": 0.0, "PARTIAL": 1.0, "GOOD": 2.0}
AGGRAVATING_CODES = frozenset(entry.code for entry in factors.of_kind(factors.AGGRAVATING))


def _flag(value: bool | None) -> float:
    if value is None:
        return NAN
    return 1.0 if value else 0.0


def _count(values) -> float:
    return float(len(values))


def _vital(name: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: float(ctx.vitals.get(name, NAN))


def _has_quality(code: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(code in ctx.qualities)


def _has_region(code: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(code in ctx.regions)


def _has_structure_type(code: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(code in ctx.structure_types)


def _has_symptom(*codes: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(bool(set(codes) & ctx.symptoms))


def _has_condition(*codes: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(bool(set(codes) & ctx.conditions))


def _has_factor(*codes: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(bool(set(codes) & ctx.factors))


def _ordinal(question: str, scale: dict[str, float]) -> Callable[[ClinicalContext], float]:
    def extract(ctx: ClinicalContext) -> float:
        given = ctx.answers.get(question)
        return scale.get(given, NAN) if isinstance(given, str) else NAN

    return extract


def _bool_answer(question: str) -> Callable[[ClinicalContext], float]:
    def extract(ctx: ClinicalContext) -> float:
        given = ctx.answers.get(question)
        return _flag(given) if isinstance(given, bool) else NAN

    return extract


def _duration_log(ctx: ClinicalContext) -> float:
    if ctx.duration_hours is None or ctx.duration_hours < 0:
        return NAN
    return math.log1p(ctx.duration_hours)


def _bmi(ctx: ClinicalContext) -> float:
    return float(ctx.vitals.get("bmi", NAN))


def _impact(domain: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: (
        float(ctx.functional_impact[domain]) if domain in ctx.functional_impact else NAN
    )


def _impact_max(ctx: ClinicalContext) -> float:
    scores = [
        ctx.functional_impact[d] for d in FUNCTIONAL_DOMAINS if d in ctx.functional_impact
    ]
    return float(max(scores)) if scores else NAN


def _timing(code: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(code in ctx.timing)


def _site_role_count(role: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _count(ctx.sites_with_role(role))


def _sites_with_neuropathic_quality(ctx: ClinicalContext) -> float:
    return _count([site for site in ctx.sites if site.qualities & qualities.NEUROPATHIC_HINTS])


def _has_medication(*codes: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(bool(set(codes) & ctx.medication_classes))


def _hours_since_analgesia_log(ctx: ClinicalContext) -> float:
    hours = ctx.hours_since_analgesia
    return math.log1p(hours) if hours is not None and hours >= 0 else NAN


def _analgesia_effect(ctx: ClinicalContext) -> float:
    effect = ctx.analgesia_effect
    return ANALGESIA_EFFECT_SCALE[effect] if effect else NAN


def _sedation_marked(ctx: ClinicalContext) -> float:
    if not ctx.medications:
        return NAN
    return _flag(any(entry.sedation_effect == "MARKED" for entry in ctx.medications))


def _onset_speed(ctx: ClinicalContext) -> float:
    return ONSET_SPEED_SCALE.get(ctx.onset_speed or "", NAN)


def _relative_change(name: str) -> Callable[[ClinicalContext], float]:
    """How far a vital sits from this patient's own resting value, as a fraction of it.
    This is the ΔHR / ΔRR / ΔTemp the brief asks for, and it stays NaN rather than zero
    when there is no baseline to compare against."""

    def extract(ctx: ClinicalContext) -> float:
        change = ctx.relative_change(name)
        return NAN if change is None else float(change)

    return extract


def _band_position(name: str) -> Callable[[ClinicalContext], float]:
    """Where a reading sits inside the resting band for this patient's profile. 0 is the
    bottom of the band, 1 the top, above 1 outside it. This is what lets one feature mean
    the same thing for a newborn at 150 beats and an adult at 80."""

    def extract(ctx: ClinicalContext) -> float:
        value = ctx.vitals.get(name)
        if value is None:
            return NAN
        band = profiles.normal_ranges(ctx).get(name)
        if band is None:
            return NAN
        low, high = band
        if high <= low:
            return NAN
        return (value - low) / (high - low)

    return extract


def _hr_beyond_fever(ctx: ClinicalContext) -> float:
    """How much of a raised heart rate the recorded temperature does not account for.
    Keeps a febrile tachycardia from being read as pain."""
    hr = ctx.vitals.get("hr")
    if hr is None:
        return NAN
    band = profiles.normal_ranges(ctx).get("hr")
    if band is None:
        return NAN
    allowance = reference_ranges.fever_heart_rate_allowance(ctx.vitals.get("temperature_c"))
    return hr - band[1] - allowance


def _observed(code: str) -> Callable[[ClinicalContext], float]:
    """A measure from the camera-and-microphone observation, or NaN where there was none.

    NaN rather than a stand-in value, for the same reason it is used for an unmeasured
    vital: the gradient-boosted trees this schema is fitted with branch on missingness
    directly, so "no clip was recorded" and "the eyes were never open" stay distinct from
    "the eyes were barely open", which a zero would not.
    """
    return lambda ctx: float(ctx.behaviour.get(code, NAN))


def _observed_change(code: str) -> Callable[[ClinicalContext], float]:
    """A behavioural measure against this patient's own resting observation.

    The ΔMovement the brief asks for, and its equivalents for the eyes and the voice. A
    pupil of 5 mm and a pitch of 180 Hz mean nothing in isolation — the first is wide for
    one person and ordinary for another, and the second is low for one voice and high for
    another — so the change from the same patient at rest is the figure that transfers.
    """

    def extract(ctx: ClinicalContext) -> float:
        change = ctx.behaviour_change(code)
        return NAN if change is None else float(change)

    return extract


def _profile_flag(code: str) -> Callable[[ClinicalContext], float]:
    return lambda ctx: _flag(ctx.profile == code or code in ctx.profile_modifiers)


def _cannot_be_asked(ctx: ClinicalContext) -> float:
    return _flag(not profiles.primary_of(ctx).can_self_report)


def _profile_penalty(ctx: ClinicalContext) -> float:
    return profiles.confidence_penalty(profiles.applicable_to(ctx))


@dataclass(frozen=True)
class Feature:
    name: str
    label: str
    extract: Callable[[ClinicalContext], float]


FEATURES = (
    Feature("age", "Age", lambda ctx: float(ctx.age) if ctx.age is not None else NAN),
    Feature("sex_female", "Female sex", lambda ctx: _flag(ctx.sex == "F") if ctx.sex else NAN),
    Feature("duration_log", "Duration of the pain", _duration_log),
    Feature("onset_sudden", "Sudden onset", lambda ctx: _flag(ctx.onset == "SUDDEN")),
    Feature("onset_speed", "How quickly the pain reached its present intensity", _onset_speed),
    Feature("recurrent", "Recurrent episodes", lambda ctx: _flag(ctx.recurrent)),
    Feature("pattern_constant", "Constant pain", lambda ctx: _flag(ctx.pattern == "CONSTANT")),
    Feature(
        "pattern_intermittent",
        "Intermittent pain",
        lambda ctx: _flag(ctx.pattern == "INTERMITTENT"),
    ),
    Feature("pattern_episodic", "Episodic pain", lambda ctx: _flag(ctx.pattern == "EPISODIC")),
    Feature(
        "course_worsening",
        "Worsening or progressive course",
        lambda ctx: _flag(ctx.course in ("WORSENING", "PROGRESSIVE")),
    ),
    Feature(
        "course_improving", "Improving course", lambda ctx: _flag(ctx.course == "IMPROVING")
    ),
    Feature(
        "episodes_per_day",
        "Episodes per day",
        lambda ctx: float(ctx.episodes_per_day) if ctx.episodes_per_day is not None else NAN,
    ),
    Feature(
        "episode_minutes",
        "Length of each episode",
        lambda ctx: float(ctx.episode_minutes) if ctx.episode_minutes is not None else NAN,
    ),
    Feature(
        "night_pain",
        "Night pain",
        lambda ctx: _flag("NIGHT" in ctx.timing or "NIGHT" in ctx.factors),
    ),
    Feature("morning_pain", "Worst in the morning", _timing("MORNING")),
    Feature("evening_pain", "Worst in the evening", _timing("EVENING")),
    Feature("variable_timing", "No fixed time of day", _timing("VARIABLE")),
    Feature("pain_at_rest", "Present at rest", _timing("AT_REST")),
    Feature("pain_after_activity", "Brought on by activity", _timing("AFTER_ACTIVITY")),
    Feature("n_locations", "Number of painful sites", lambda ctx: _count(ctx.pain_locations)),
    Feature("n_regions", "Number of body regions involved", lambda ctx: _count(ctx.regions)),
    Feature("region_head", "Head or face involved", _has_region("HEAD")),
    Feature("region_neck", "Neck involved", _has_region("NECK")),
    Feature("region_chest", "Chest involved", _has_region("CHEST")),
    Feature("region_back", "Back involved", _has_region("BACK")),
    Feature("region_abdomen", "Abdomen involved", _has_region("ABDOMEN")),
    Feature("region_pelvis", "Pelvis involved", _has_region("PELVIS")),
    Feature("region_upper_limb", "Upper limb involved", _has_region("UPPER_LIMB")),
    Feature("region_lower_limb", "Lower limb involved", _has_region("LOWER_LIMB")),
    Feature("region_systemic", "Generalised distribution", _has_region("SYSTEMIC")),
    Feature(
        "sites_bilateral",
        "Pain recorded on both sides",
        lambda ctx: _flag(ctx.bilateral),
    ),
    Feature(
        "n_structures",
        "Number of anatomical structures localised",
        lambda ctx: _count(ctx.anatomical_structures),
    ),
    Feature(
        "structure_localised",
        "Anatomy identified rather than approximated to a region",
        lambda ctx: _flag(bool(ctx.structure_types & anatomy.EXACT_TYPES)),
    ),
    Feature("structure_muscle", "A muscle is involved", _has_structure_type(anatomy.MUSCLE)),
    Feature(
        "structure_tendon",
        "A tendon or ligament is involved",
        _has_structure_type(anatomy.TENDON),
    ),
    Feature("structure_bone", "A bone is involved", _has_structure_type(anatomy.BONE)),
    Feature("structure_joint", "A joint is involved", _has_structure_type(anatomy.JOINT)),
    Feature("structure_organ", "An organ is involved", _has_structure_type(anatomy.ORGAN)),
    Feature(
        "structure_ligament", "A ligament is involved", _has_structure_type(anatomy.LIGAMENT)
    ),
    Feature("structure_nerve", "A nerve is involved", _has_structure_type(anatomy.NERVE)),
    Feature("structure_vessel", "A vessel is involved", _has_structure_type(anatomy.VESSEL)),
    Feature("n_sites_secondary", "Secondary pain sites", _site_role_count("SECONDARY")),
    Feature("n_sites_radiating", "Radiating pain sites", _site_role_count("RADIATING")),
    Feature("n_sites_referred", "Referred pain sites", _site_role_count("REFERRED")),
    Feature(
        "radiation_chain_length",
        "Length of the traced radiation path",
        lambda ctx: float(ctx.radiation_chain_length),
    ),
    Feature(
        "sites_neuropathic_quality",
        "Sites described with a neuropathic quality",
        _sites_with_neuropathic_quality,
    ),
    Feature("n_qualities", "Number of pain descriptors", lambda ctx: _count(ctx.qualities)),
    Feature(
        "neuropathic_qualities",
        "Descriptors associated with neuropathic pain",
        lambda ctx: _count(ctx.qualities & qualities.NEUROPATHIC_HINTS),
    ),
    Feature("quality_pressure", "Pressure or tightness", _has_quality("PRESSURE")),
    Feature("quality_burning", "Burning character", _has_quality("BURNING")),
    Feature("quality_cramping", "Cramping character", _has_quality("CRAMPING")),
    Feature("quality_sharp", "Sharp or stabbing character", _has_quality("SHARP")),
    Feature("quality_throbbing", "Throbbing character", _has_quality("THROBBING")),
    Feature("quality_electric", "Electric-shock-like character", _has_quality("ELECTRIC")),
    Feature("radiates", "Pain radiates", lambda ctx: _flag(ctx.radiates)),
    Feature(
        "radiation_neuro",
        "Radiation with numbness, tingling or weakness",
        lambda ctx: _flag(bool({"NUMBNESS", "TINGLING", "MOTOR_WEAKNESS"} & ctx.symptoms)),
    ),
    Feature("n_symptoms", "Number of associated symptoms", lambda ctx: _count(ctx.symptoms)),
    Feature(
        "n_alarm_symptoms",
        "Number of alarm symptoms",
        lambda ctx: _count(ctx.symptoms & symptoms.ALARM_SYMPTOMS),
    ),
    Feature(
        "n_systemic_symptoms",
        "Number of systemic symptoms",
        lambda ctx: _count(ctx.symptoms & symptoms.SYSTEMIC_SYMPTOMS),
    ),
    Feature("symptom_fever", "Fever", _has_symptom("FEVER")),
    Feature("symptom_gi", "Nausea or vomiting", _has_symptom("NAUSEA", "VOMITING")),
    Feature("symptom_dyspnoea", "Breathlessness", _has_symptom("DYSPNOEA")),
    Feature("symptom_sensory", "Numbness or tingling", _has_symptom("NUMBNESS", "TINGLING")),
    Feature("symptom_motor", "Motor weakness", _has_symptom("MOTOR_WEAKNESS")),
    Feature(
        "n_aggravating",
        "Number of aggravating factors",
        lambda ctx: _count(ctx.factors & AGGRAVATING_CODES),
    ),
    Feature(
        "n_relieving",
        "Number of relieving factors",
        lambda ctx: _count(ctx.factors - AGGRAVATING_CODES),
    ),
    Feature(
        "factor_movement", "Worse on movement", _has_factor("MOVEMENT", "WALKING", "EXERCISE")
    ),
    Feature("factor_rest_relieves", "Eased by rest", _has_factor("REST")),
    Feature("factor_medication_relieves", "Eased by medication", _has_factor("MEDICATION")),
    Feature("n_conditions", "Number of chronic conditions", lambda ctx: _count(ctx.conditions)),
    Feature(
        "n_pain_relevant_conditions",
        "Chronic conditions relevant to pain",
        lambda ctx: _count(ctx.conditions & diseases.PAIN_RELEVANT),
    ),
    Feature(
        "condition_cancer",
        "Cancer, active or previous",
        _has_condition("CANCER_ACTIVE", "CANCER_HISTORY", "CANCER_TREATMENT"),
    ),
    Feature("condition_diabetes", "Diabetes", _has_condition("DIABETES_T1", "DIABETES_T2")),
    Feature("condition_neuropathy", "Known neuropathy", _has_condition("NEUROPATHY")),
    Feature(
        "condition_inflammatory",
        "Inflammatory joint disease",
        _has_condition("RHEUMATOID_ARTHRITIS", "IBD"),
    ),
    Feature(
        "n_confounders", "Recorded contextual factors", lambda ctx: _count(ctx.confounders)
    ),
    Feature("recent_trauma", "Recent trauma", lambda ctx: _flag(ctx.recent_trauma)),
    Feature("recent_surgery", "Recent surgery", lambda ctx: _flag(ctx.recent_surgery)),
    Feature("hr", "Heart rate", _vital("hr")),
    Feature("resp_rate", "Respiratory rate", _vital("resp_rate")),
    Feature("sbp", "Systolic blood pressure", _vital("sbp")),
    Feature("dbp", "Diastolic blood pressure", _vital("dbp")),
    Feature("spo2", "Oxygen saturation", _vital("spo2")),
    Feature("temperature_c", "Temperature", _vital("temperature_c")),
    Feature("glucose_mmol", "Blood glucose", _vital("glucose_mmol")),
    Feature("bmi", "Body mass index", _bmi),
    Feature(
        "n_deranged_vitals",
        "Vital signs outside the configured range",
        lambda ctx: _count(rules.deranged_for(ctx)),
    ),
    Feature("impact_mobility", "Impact on mobility", _impact("mobility")),
    Feature("impact_sleep", "Impact on sleep", _impact("sleep")),
    Feature("impact_work", "Impact on work", _impact("work")),
    Feature("impact_daily_activity", "Impact on daily activities", _impact("daily_activity")),
    Feature("impact_self_care", "Impact on self-care", _impact("self_care")),
    Feature(
        "impact_mean",
        "Functional impact across domains",
        lambda ctx: ctx.functional_mean if ctx.functional_mean is not None else NAN,
    ),
    Feature("impact_max", "Worst functional domain", _impact_max),
    Feature("med_opioid", "Opioid in effect", _has_medication("OPIOID")),
    Feature("med_nsaid", "NSAID in effect", _has_medication("NSAID")),
    Feature("med_acetaminophen", "Paracetamol in effect", _has_medication("ACETAMINOPHEN")),
    Feature(
        "med_corticosteroid", "Corticosteroid in effect", _has_medication("CORTICOSTEROID")
    ),
    Feature(
        "med_neuropathic_agent",
        "Antidepressant or anticonvulsant for pain",
        _has_medication("ANTIDEPRESSANT", "ANTICONVULSANT"),
    ),
    Feature(
        "med_antihypertensive",
        "Antihypertensive in effect",
        _has_medication("ANTIHYPERTENSIVE"),
    ),
    Feature(
        "med_sedating",
        "Sedating medication in effect",
        lambda ctx: _flag(bool(ctx.medication_classes & medications.SEDATING)),
    ),
    Feature(
        "n_analgesic_classes",
        "Analgesic classes in effect",
        lambda ctx: _count(ctx.medication_classes & medications.ANALGESIC),
    ),
    Feature(
        "hours_since_analgesia_log",
        "Time since the last analgesic dose",
        _hours_since_analgesia_log,
    ),
    Feature("analgesia_effect", "Relief obtained from analgesia", _analgesia_effect),
    Feature("sedation_marked", "Markedly sedated", _sedation_marked),
    Feature("allodynia", "Pain on light touch", _bool_answer("NEURO_ALLODYNIA")),
    Feature("first_episode", "First episode of this pain", _bool_answer("FIRST_EPISODE")),
    Feature(
        "delta_hr_rel",
        "Heart rate against this patient's own resting rate",
        _relative_change("hr"),
    ),
    Feature(
        "delta_resp_rate_rel",
        "Respiratory rate against this patient's own resting rate",
        _relative_change("resp_rate"),
    ),
    Feature(
        "delta_sbp_rel",
        "Systolic pressure against this patient's own resting pressure",
        _relative_change("sbp"),
    ),
    Feature(
        "delta_dbp_rel",
        "Diastolic pressure against this patient's own resting pressure",
        _relative_change("dbp"),
    ),
    Feature(
        "delta_spo2_rel",
        "Oxygen saturation against this patient's own resting saturation",
        _relative_change("spo2"),
    ),
    Feature(
        "delta_temperature_rel",
        "Temperature against this patient's own resting temperature",
        _relative_change("temperature_c"),
    ),
    Feature(
        "baseline_points",
        "Readings the resting baseline rests on",
        lambda ctx: float(ctx.baseline_points),
    ),
    Feature("hr_in_band", "Heart rate within the band for this profile", _band_position("hr")),
    Feature(
        "resp_rate_in_band",
        "Respiratory rate within the band for this profile",
        _band_position("resp_rate"),
    ),
    Feature(
        "sbp_in_band",
        "Systolic pressure within the band for this profile",
        _band_position("sbp"),
    ),
    Feature(
        "temperature_in_band",
        "Temperature within the band for this profile",
        _band_position("temperature_c"),
    ),
    Feature(
        "hr_beyond_fever",
        "Heart rate above what the band and the fever together account for",
        _hr_beyond_fever,
    ),
    Feature("cannot_be_asked", "Patient cannot be asked for a score", _cannot_be_asked),
    Feature(
        "profile_penalty",
        "Certainty given back for this profile",
        _profile_penalty,
    ),
    Feature("profile_newborn", "Newborn", _profile_flag(profiles.NEWBORN)),
    Feature(
        "profile_infant_toddler",
        "Infant or young child",
        _profile_flag(profiles.INFANT_TODDLER),
    ),
    Feature("profile_child", "Child", _profile_flag(profiles.CHILD)),
    Feature("profile_adolescent", "Adolescent", _profile_flag(profiles.ADOLESCENT)),
    Feature("profile_pregnant", "Pregnant", _profile_flag(profiles.PREGNANT)),
    Feature("profile_older_adult", "Older adult", _profile_flag(profiles.OLDER_ADULT)),
    Feature(
        "profile_cognitive_impairment",
        "Cognitive impairment or dementia",
        _profile_flag(profiles.COGNITIVE_IMPAIRMENT),
    ),
    Feature(
        "profile_critical_care",
        "Critical care, sedated or intubated",
        _profile_flag(profiles.CRITICAL_CARE),
    ),
    Feature(
        "profile_signal_altering_medication",
        "On medication that alters the recorded signals",
        _profile_flag(profiles.SIGNAL_ALTERING_MEDICATION),
    ),
    Feature("profile_febrile", "Fever or infection", _profile_flag(profiles.FEBRILE)),
    Feature(
        "profile_physically_active",
        "Physical activity or exertion",
        _profile_flag(profiles.PHYSICALLY_ACTIVE),
    ),
    Feature(
        "profile_chronic_pain", "Established chronic pain", _profile_flag(profiles.CHRONIC_PAIN)
    ),
    Feature(
        "pregnancy_trimester",
        "Trimester",
        lambda ctx: (
            float(ctx.pregnancy_trimester) if ctx.pregnancy_trimester is not None else NAN
        ),
    ),
    Feature(
        "expected_pain", "Pain expected for the situation", lambda ctx: _flag(ctx.expected_pain)
    ),
    # What the camera and the microphone measured. Every one of these is a measurement of
    # behaviour and not of pain: they move with fear, fatigue, room light, sedation and
    # distance from the lens as well as with pain, and the model weighs them against the
    # rest of the examination rather than reading them on their own.
    Feature("eye_squint_index", "Orbital tightening", _observed("eye_squint_index")),
    Feature("eye_aperture_ratio", "Eye aperture", _observed("eye_aperture_ratio")),
    Feature("eye_open_share", "Frames with both eyes open", _observed("eye_open_share")),
    Feature("blink_rate_per_min", "Blink rate", _observed("blink_rate_per_min")),
    Feature(
        "long_closure_share", "Time with the eyes squeezed shut", _observed("long_closure_share")
    ),
    Feature("pupil_diameter_mm", "Pupil diameter", _observed("pupil_diameter_mm")),
    Feature("pupil_unrest_mm", "Pupillary unrest", _observed("pupil_unrest_mm")),
    Feature("gaze_dispersion_ratio", "Gaze movement", _observed("gaze_dispersion_ratio")),
    Feature("brow_lower_index", "Brow lowering", _observed("brow_lower_index")),
    Feature("mouth_open_ratio", "Mouth opening", _observed("mouth_open_ratio")),
    Feature("face_motion_index", "Head movement", _observed("face_motion_index")),
    Feature("head_turn_share", "Time facing away from the camera", _observed("head_turn_share")),
    Feature(
        "facial_action_index",
        "Facial pain actions measured",
        _observed("facial_action_index"),
    ),
    Feature("voice_f0_mean_hz", "Pitch", _observed("f0_mean_hz")),
    Feature("voice_f0_sd_semitones", "Pitch variability", _observed("f0_sd_semitones")),
    Feature("voice_jitter_percent", "Jitter", _observed("jitter_percent")),
    Feature("voice_shimmer_percent", "Shimmer", _observed("shimmer_percent")),
    Feature("voice_hnr_db", "Harmonics to noise in the voice", _observed("hnr_db")),
    Feature("voice_pause_share", "Time silent", _observed("pause_share")),
    Feature("voice_speech_rate_per_s", "Speech rate", _observed("speech_rate_per_s")),
    Feature(
        "voice_vocalisation_share",
        "Non-speech vocalisation",
        _observed("vocalisation_share"),
    ),
    Feature(
        "delta_eye_aperture_rel",
        "Eye aperture against this patient's own resting opening",
        _observed_change("eye_aperture_ratio"),
    ),
    Feature(
        "delta_pupil_rel",
        "Pupil against this patient's own resting pupil",
        _observed_change("pupil_diameter_mm"),
    ),
    Feature(
        "delta_blink_rate_rel",
        "Blink rate against this patient's own resting rate",
        _observed_change("blink_rate_per_min"),
    ),
    Feature(
        "delta_voice_f0_rel",
        "Pitch against this patient's own resting pitch",
        _observed_change("f0_mean_hz"),
    ),
)

NAMES = tuple(feature.name for feature in FEATURES)
LABELS = {feature.name: feature.label for feature in FEATURES}
VITAL_FEATURES = frozenset(
    {"hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c", "glucose_mmol", "bmi"}
)


def vector(ctx: ClinicalContext) -> np.ndarray:
    return np.array([feature.extract(ctx) for feature in FEATURES], dtype=float)


def matrix(contexts: list[ClinicalContext]) -> np.ndarray:
    return (
        np.vstack([vector(ctx) for ctx in contexts])
        if contexts
        else np.empty((0, len(FEATURES)))
    )
