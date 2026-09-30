"""The feature vector.

One ordered list of features, used by both training and inference. Anything that changes
here changes both at once, which is the only way the vector a model was fitted on stays
the vector it is asked to predict from.

Two properties are deliberate:

- Missing values are left as NaN. The estimator is a histogram gradient boosting model,
  which routes NaN down its own branch, so an absent measurement is never replaced by a
  mean or a zero that the record does not support.
- Nothing here reads a self-reported score. ClinicalContext has no field for one, so the
  separation is structural rather than a rule each extractor has to remember.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from app.knowledge import anatomy, diseases, qualities, rules, symptoms
from app.knowledge.context import ClinicalContext

NAN = float("nan")


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
    Feature("night_pain", "Night pain", lambda ctx: _flag("NIGHT" in ctx.factors)),
    Feature("pain_at_rest", "Pain at rest", lambda ctx: _flag("REST" not in ctx.factors)),
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
    # What the 3D model adds to the region a site already carries: whether the anatomy was
    # identified at all, and what kind of tissue it was. The per-site intensities recorded
    # beside those structures are not here and cannot be: ClinicalContext has no field for
    # them, for the same reason it has none for the self-reported score.
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
    Feature("structure_nerve", "A nerve is involved", _has_structure_type(anatomy.NERVE)),
    Feature("structure_vessel", "A vessel is involved", _has_structure_type(anatomy.VESSEL)),
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
        lambda ctx: _count([code for code in ctx.factors if not code.startswith("REST")]),
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
        lambda ctx: _count(rules.deranged_vitals(ctx.vitals)),
    ),
    Feature(
        "functional_impact",
        "Limitation of usual activity",
        _ordinal(
            "FUNCTIONAL_IMPACT", {"NONE": 0.0, "MILD": 1.0, "MODERATE": 2.0, "SEVERE": 3.0}
        ),
    ),
    Feature("sleep_disturbed", "Sleep disturbed by the pain", _bool_answer("SLEEP_DISTURBED")),
    Feature("analgesia_taken", "Analgesia already taken", _bool_answer("ANALGESIA_TAKEN")),
    Feature(
        "analgesia_effect",
        "Relief obtained from analgesia",
        _ordinal("ANALGESIA_EFFECT", {"NONE": 0.0, "PARTIAL": 1.0, "GOOD": 2.0}),
    ),
    Feature("allodynia", "Pain on light touch", _bool_answer("NEURO_ALLODYNIA")),
    Feature("first_episode", "First episode of this pain", _bool_answer("FIRST_EPISODE")),
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
