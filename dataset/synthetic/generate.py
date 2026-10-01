import argparse
import json
import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
from sklearn.model_selection import GroupShuffleSplit

from backend.ai import features, quality
from backend.behaviour import schema as behaviour_schema
from config import get_settings
from dataset.synthetic import scenarios as scenario_kb
from dataset.synthetic import storage
from dataset.synthetic.archetypes import ARCHETYPES, FLARE, IMPROVING, WORSENING, Archetype, Weighted
from knowledge import (
    anatomy,
    confounders,
    diseases,
    factors,
    medications,
    pain_types,
    questions,
    reference_ranges,
    rules,
    scales,
)
from knowledge import context as context_module
from knowledge import (
    profiles as profiles_kb,
)
from knowledge import qualities as qualities_kb
from knowledge import symptoms as symptoms_kb
from knowledge.context import (
    FUNCTIONAL_DOMAINS,
    ClinicalContext,
    MedicationContext,
    SiteContext,
)

GENERATOR_VERSION = "2"

WARNING = "SYNTHETIC DATA. Not clinical data and not representative of any real population."
TARGET_NOTE = "nrs, the patient's self-reported 0-10 score, used as the training reference only"

SPLITS = ("train", "validation", "test")
VALIDATION_SHARE = 0.15
TEST_SHARE = 0.15

DEFAULT_HARD_CASE_SHARE = 0.12
DEFAULT_CHUNK_SIZE = 20000

# How the generated population is split across profiles. Chosen so every profile carries
# enough patients for a per-profile metric to mean something, while adults and older adults
# stay the bulk, as they are in a general hospital.
PROFILE_MIX = (
    (profiles_kb.ADULT, 0.30),
    (profiles_kb.OLDER_ADULT, 0.19),
    (profiles_kb.ADOLESCENT, 0.08),
    (profiles_kb.CHILD, 0.07),
    (profiles_kb.INFANT_TODDLER, 0.07),
    (profiles_kb.NEWBORN, 0.05),
    (profiles_kb.PREGNANT, 0.07),
    (profiles_kb.COGNITIVE_IMPAIRMENT, 0.08),
    (profiles_kb.CRITICAL_CARE, 0.09),
)

# Ages a state-based profile is drawn from, since the profile itself carries no age range.
STATE_PROFILE_AGES = {
    profiles_kb.PREGNANT: (18, 44),
    profiles_kb.COGNITIVE_IMPAIRMENT: (70, 95),
    profiles_kb.CRITICAL_CARE: (18, 85),
}

# The archetype a state-based profile reaches for first, so a labour profile is not handed
# a migraine.
STATE_PROFILE_ARCHETYPES = {
    profiles_kb.PREGNANT: ("OBSTETRIC_LABOUR", 0.6),
    profiles_kb.CRITICAL_CARE: ("POSTOPERATIVE", 0.55),
}

# How likely each modifier is. One the primary profile already implies is not drawn again.
MODIFIER_CHANCES = {
    profiles_kb.SIGNAL_ALTERING_MEDICATION: 0.12,
    profiles_kb.FEBRILE: 0.10,
    profiles_kb.PHYSICALLY_ACTIVE: 0.08,
    profiles_kb.CHRONIC_PAIN: 0.12,
}

# Resting sits in the lower part of a band, because a band covers awake and active states
# as well as rest. A generator constant, not a clinical figure.
RESTING_POSITION_IN_BAND = 0.35

# Every generated patient is treated as having had a calibration at rest, so the relative
# changes the model reads are populated. A real deployment has to record one; the dataset
# documents this as an assumption of the simulation.
BASELINE_READINGS = 3

# Diastolic as a share of systolic, used for both the resting value and the visit reading
# so the two are on the same footing.
DIASTOLIC_OF_SYSTOLIC = 0.62

STATE_SHIFTS = {
    "anxiety": {"hr": 9.0, "resp_rate": 3.0, "sbp": 8.0},
    "fear": {"hr": 7.0, "sbp": 6.0},
    "recent_activity": {"hr": 16.0, "resp_rate": 4.0},
    "sleep_deprivation": {"hr": 4.0},
    "caffeine": {"hr": 6.0, "sbp": 5.0},
    "beta_blocker": {"hr": -12.0},
    "opioid_regular": {"resp_rate": -3.0, "hr": -4.0},
    "opioid_recent": {"resp_rate": -2.0, "hr": -2.0},
    "antihypertensive": {"sbp": -12.0, "dbp": -6.0},
    "antidepressant": {"hr": 4.0},
    "sedative": {"resp_rate": -2.0},
    "triptan": {"sbp": 4.0},
    "analgesia_recent": {"hr": -3.0},
    # The states the paediatric and neonatal profiles turn on. Each produces the same
    # autonomic picture as pain without any pain being present, which is what makes them
    # the false positives worth generating.
    "hunger": {"hr": 8.0, "resp_rate": 3.0},
    "fatigue": {"hr": 4.0},
    "handling": {"hr": 12.0, "resp_rate": 4.0},
    "separation_distress": {"hr": 12.0, "resp_rate": 4.0},
    "sedated": {"hr": -8.0, "resp_rate": -4.0, "sbp": -8.0},
    "stress": {"hr": 9.0, "resp_rate": 3.0, "sbp": 8.0},
}

RECORDED_AS = {
    "anxiety": ("ANXIETY", 0.85),
    "fear": ("FEAR", 0.8),
    "recent_activity": ("RECENT_ACTIVITY", 0.8),
    "sleep_deprivation": ("SLEEP_DEPRIVATION", 0.8),
    "caffeine": ("CAFFEINE_STIMULANT", 0.75),
    "communication_barrier": ("COMMUNICATION_BARRIER", 0.9),
    "febrile": ("FEVER_CONTEXT", 0.6),
    "beta_blocker": ("BETA_BLOCKER", 0.7),
    "opioid_regular": ("OPIOID_THERAPY", 0.8),
    "analgesia_recent": ("ANALGESIA_RECENT", 0.75),
    "hunger": ("HUNGER", 0.7),
    "fatigue": ("FATIGUE", 0.65),
    "handling": ("HANDLING", 0.7),
    "separation_distress": ("SEPARATION_DISTRESS", 0.7),
    "sedated": ("SEDATION", 0.9),
    "stress": ("STRESS", 0.75),
}
STATE_OF_ARCHETYPE_CONFOUNDER = {code: state for state, (code, _) in RECORDED_AS.items()}

REPORT_NOISE = {
    "communication_barrier": 0.7,
    "opioid_regular": 0.5,
    "analgesia_recent": 0.4,
    "sleep_deprivation": 0.2,
}
BASE_REPORT_NOISE = 0.9

RELIEF_SHIFT = {"GOOD": 1.5, "PARTIAL": 0.8, "NONE": 0.0, "UNKNOWN": 0.4}
ANALGESIA_RECENT_HOURS = 4.0

VITAL_MISSING_PROBABILITY = {
    "hr": 0.08,
    "resp_rate": 0.18,
    "sbp": 0.12,
    "dbp": 0.14,
    "spo2": 0.16,
    "temperature_c": 0.2,
    "glucose_mmol": 0.55,
}
# --- what a camera and a microphone see ------------------------------------------------
#
# The same structure as the vitals above, for the same reason. A resting value per patient,
# a shift per point of pain, and a shift per confounding state — because the confounders
# are the point. Anxiety widens a pupil and raises a blink rate without any pain behind it,
# and sedation flattens a grimace that pain is producing. A model trained only on cases
# where behaviour and pain move together learns that a wide pupil is pain, which is the
# error this platform exists to avoid making.

#: Centre and individual spread of each resting measure. The centres are the figures the
#: observational literature quotes for an adult at rest: a blink every three or four
#: seconds, a pupil of three to four millimetres in room light, four syllables a second.
RESTING_BEHAVIOUR = {
    "eye_aperture_ratio": (0.88, 0.05),
    "pupil_diameter_mm": (3.4, 0.55),
    "blink_rate_per_min": (17.0, 5.0),
    "brow_gap_ratio": (0.33, 0.025),
    "intensity_db": (-22.0, 4.0),
    "speech_rate_per_s": (4.2, 0.6),
}

#: Resting pitch, which differs by roughly an octave between adult voices and is higher
#: again before puberty. Carried separately from the table above because no single centre
#: would be right for any of them.
RESTING_F0_HZ = {"M": (115.0, 18.0), "F": (210.0, 25.0)}
CHILD_F0_HZ = (300.0, 35.0)
INFANT_F0_HZ = (420.0, 60.0)
#: Age at which the adult pitch is used.
PITCH_ADULT_FROM_YEARS = 14.0
PITCH_INFANT_UNTIL_YEARS = 2.0

#: How much each measure moves per point of pain, in its own unit. Monotone and linear,
#: which is a simplification: the relationship in the literature is noisy and probably
#: saturates at the top of the scale. It is linear here because this is a generator, and a
#: curve nobody has measured would be a different kind of invention.
BEHAVIOUR_PER_POINT = {
    "eye_squint_index": 0.055,
    "pupil_diameter_mm": 0.12,
    "pupil_unrest_mm": 0.022,
    "blink_rate_per_min": 0.9,
    "brow_lower_index": 0.040,
    "face_motion_index": 0.028,
    "gaze_dispersion_ratio": 0.009,
    "mouth_open_ratio": 0.008,
    "f0_sd_semitones": 0.26,
    "jitter_percent": 0.22,
    "shimmer_percent": 0.55,
    "hnr_db": -1.1,
    "pause_share": 0.019,
    "speech_rate_per_s": -0.09,
}

#: Pitch rises as a fraction of the patient's own resting pitch rather than by a fixed
#: number of hertz. Two hertz is inaudible in a child and obvious in a bass.
F0_RISE_PER_POINT = 0.022

#: Which measures the vocal expressiveness applies to rather than the facial one.
VOCAL_MEASURES = frozenset(
    {
        "f0_mean_hz",
        "f0_sd_semitones",
        "jitter_percent",
        "shimmer_percent",
        "hnr_db",
        "intensity_db",
        "voiced_share",
        "pause_share",
        "speech_rate_per_s",
        "vocalisation_share",
    }
)

#: Measures that stay at zero until the pain is well past the middle of the scale, then
#: climb. Squeezing the eyes shut and moaning are not quiet versions of a grimace; they
#: start happening or they do not. Each entry is the point they start from and the rise
#: per point after it.
BEHAVIOUR_THRESHOLDS = {
    "long_closure_share": (5.0, 0.030),
    "vocalisation_share": (4.0, 0.050),
}

#: Additive effect of each confounding state, in each measure's own unit. The same shape
#: and the same purpose as VITAL_SHIFT. Negative entries matter as much as positive ones:
#: sedation and opioids suppress exactly the behaviour pain produces, which is how a
#: behavioural channel produces a false negative on the patient least able to say so.
BEHAVIOUR_SHIFT = {
    "anxiety": {
        "pupil_diameter_mm": 0.45,
        "blink_rate_per_min": 7.0,
        "f0_mean_hz": 9.0,
        "face_motion_index": 0.04,
        "jitter_percent": 0.4,
    },
    "fear": {
        "pupil_diameter_mm": 0.7,
        "blink_rate_per_min": 9.0,
        "f0_mean_hz": 14.0,
        "eye_aperture_ratio": 0.04,
        "face_motion_index": 0.05,
    },
    "stress": {
        "pupil_diameter_mm": 0.4,
        "blink_rate_per_min": 6.0,
        "f0_mean_hz": 8.0,
        "jitter_percent": 0.3,
    },
    "sleep_deprivation": {
        "eye_aperture_ratio": -0.07,
        "blink_rate_per_min": 6.0,
        "speech_rate_per_s": -0.4,
    },
    "fatigue": {"eye_aperture_ratio": -0.05, "blink_rate_per_min": 3.0},
    "caffeine": {"pupil_diameter_mm": 0.25, "blink_rate_per_min": 3.0},
    "sedated": {
        "eye_aperture_ratio": -0.10,
        "blink_rate_per_min": -8.0,
        "pupil_diameter_mm": -0.5,
        "face_motion_index": -0.04,
        "speech_rate_per_s": -1.0,
        "eye_squint_index": -0.15,
        "brow_lower_index": -0.12,
        "vocalisation_share": -0.10,
    },
    "opioid_recent": {
        "pupil_diameter_mm": -1.1,
        "blink_rate_per_min": -4.0,
        "eye_squint_index": -0.08,
    },
    "opioid_regular": {"pupil_diameter_mm": -0.7},
    "handling": {"face_motion_index": 0.06, "blink_rate_per_min": 4.0},
    "separation_distress": {
        "f0_mean_hz": 25.0,
        "vocalisation_share": 0.20,
        "face_motion_index": 0.05,
    },
    "hunger": {"vocalisation_share": 0.15, "f0_mean_hz": 15.0},
    "febrile": {"eye_aperture_ratio": -0.03, "blink_rate_per_min": 2.0},
    "recent_activity": {
        "face_motion_index": 0.05,
        "speech_rate_per_s": 0.3,
        "intensity_db": 2.0,
    },
}

#: Noise on each measure, in its own unit, standing for everything the generator does not
#: model: room light, the angle of the head, how well the lens was focused.
BEHAVIOUR_NOISE = {
    "eye_aperture_ratio": 0.035,
    "eye_squint_index": 0.05,
    "eye_open_share": 0.06,
    "eye_asymmetry_ratio": 0.02,
    "blink_rate_per_min": 3.5,
    "blink_closure_ms": 25.0,
    "long_closure_share": 0.02,
    "pupil_diameter_mm": 0.35,
    "pupil_iris_ratio": 0.04,
    "pupil_unrest_mm": 0.03,
    "pupil_asymmetry_mm": 0.08,
    "gaze_dispersion_ratio": 0.012,
    "brow_gap_ratio": 0.015,
    "brow_lower_index": 0.045,
    "mouth_open_ratio": 0.012,
    "face_motion_index": 0.025,
    "head_turn_share": 0.05,
    "f0_mean_hz": 7.0,
    "f0_sd_semitones": 0.5,
    "jitter_percent": 0.35,
    "shimmer_percent": 0.9,
    "hnr_db": 2.2,
    "intensity_db": 2.5,
    "voiced_share": 0.08,
    "pause_share": 0.05,
    "speech_rate_per_s": 0.4,
    "vocalisation_share": 0.05,
    "spectral_centroid_hz": 180.0,
    "spectral_rolloff_hz": 320.0,
    "zero_crossing_rate": 0.02,
}

#: Spread of how much a person shows pain at all, as a multiplier on everything the pain
#: drives. This is not noise dressed up: how expressively a patient grimaces or strains
#: their voice at a given pain varies several-fold between people, and older adults and
#: patients with dementia express less of it at the same reported intensity. It is the
#: single reason a behavioural channel cannot be read against a population average, and
#: generating without it would produce a dataset where facial measures predict pain far
#: better than they do in any published cohort.
EXPRESSIVENESS = (1.0, 0.45)
EXPRESSIVENESS_FLOOR = 0.15
#: Multiplied on top for the populations that express less at the same intensity.
EXPRESSIVENESS_BY_PROFILE = {
    profiles_kb.OLDER_ADULT: 0.75,
    profiles_kb.COGNITIVE_IMPAIRMENT: 0.6,
    profiles_kb.CRITICAL_CARE: 0.5,
}

#: Share of visits a clip was recorded at. A camera is not pointed at every patient at
#: every visit, and a feature set where it always was would train a model that has never
#: seen the absence.
OBSERVATION_PROBABILITY = 0.55
#: Share of patients with a resting observation to compare against. Lower, because it is
#: an extra act at a quieter moment.
RESTING_OBSERVATION_PROBABILITY = 0.6
#: Share of recorded clips in which the eye measures or the voice measures came back
#: unusable: the patient looked away, kept their eyes shut, said nothing, or the room was
#: louder than they were.
EYES_UNUSABLE_PROBABILITY = 0.18
VOICE_UNUSABLE_PROBABILITY = 0.22

ANSWER_MISSING_PROBABILITY = 0.15
DOMAIN_MISSING_PROBABILITY = 0.06
IMPACT_BLOCK_MISSING_PROBABILITY = 0.08
DOSE_TIMING_MISSING_PROBABILITY = 0.2

STRUCTURE_MISSING_PROBABILITY = 0.2
ARCHETYPE_SWITCH_PROBABILITY = 0.1

REGULAR_FREQUENCIES = frozenset(
    {"DAILY", "TWICE_DAILY", "THREE_TIMES_DAILY", "FOUR_TIMES_DAILY", "CONTINUOUS"}
)
CONDITION_MEDICATIONS: tuple[tuple[str, str, float], ...] = (
    ("HYPERTENSION", "ANTIHYPERTENSIVE", 0.75),
    ("CAD", "ANTIHYPERTENSIVE", 0.6),
    ("CAD", "ANTICOAGULANT", 0.5),
    ("DIABETES_T1", "ANTIDIABETIC", 0.95),
    ("DIABETES_T2", "ANTIDIABETIC", 0.85),
    ("DEPRESSION", "ANTIDEPRESSANT", 0.55),
    ("ANXIETY_DISORDER", "ANTIDEPRESSANT", 0.35),
    ("ANXIETY_DISORDER", "SEDATIVE", 0.15),
    ("RHEUMATOID_ARTHRITIS", "CORTICOSTEROID", 0.3),
    ("ASTHMA", "CORTICOSTEROID", 0.15),
    ("ARRHYTHMIA", "ANTICOAGULANT", 0.6),
)
BETA_BLOCKER_SHARE = 0.55

DOSE_WEIGHTS: Weighted = (("LOW", 0.25), ("STANDARD", 0.55), ("HIGH", 0.15), ("UNKNOWN", 0.05))
ANALGESIC_FREQUENCY: Weighted = (
    ("AS_NEEDED", 0.45),
    ("SINGLE", 0.15),
    ("THREE_TIMES_DAILY", 0.2),
    ("FOUR_TIMES_DAILY", 0.1),
    ("TWICE_DAILY", 0.1),
)
REGULAR_FREQUENCY: Weighted = (("DAILY", 0.6), ("TWICE_DAILY", 0.3), ("UNKNOWN", 0.1))

DOMAIN_WEIGHT = {
    "mobility": 0.9,
    "sleep": 0.85,
    "work": 1.0,
    "daily_activity": 1.0,
    "self_care": 0.7,
}


def _pick(rng: np.random.Generator, weighted: Weighted) -> str | None:
    if not weighted:
        return None
    total = 0.0
    for _, weight in weighted:
        total += weight
    if total <= 0:
        return None
    draw = rng.random() * total
    for code, weight in weighted:
        draw -= weight
        if draw < 0:
            return code
    return weighted[-1][0]


def _subset(rng: np.random.Generator, weighted: Weighted) -> set[str]:
    return {code for code, probability in weighted if rng.random() < probability}


def _sample(
    rng: np.random.Generator, pool: tuple[str, ...], count: tuple[int, int]
) -> set[str]:
    if not pool:
        return set()
    low, high = count
    size = min(int(rng.integers(low, high + 1)), len(pool))
    return {pool[int(index)] for index in rng.choice(len(pool), size=size, replace=False)}


def _log_uniform(rng: np.random.Generator, low: float, high: float) -> float:
    return float(math.exp(rng.uniform(math.log(low), math.log(high))))


def _site_spec(spec: str) -> tuple[str, str | None]:
    code, _, side = spec.partition("|")
    return code, side or None


@dataclass
class Patient:
    index: int
    patient_id: str
    sex: str
    age_at_first_visit: int
    birth_year: int
    archetype: str
    trajectory: str
    side: str
    conditions: frozenset[str]
    regular_medications: tuple[str, ...]
    beta_blocker: bool
    latent_centre: float
    hr_offset: float
    resp_rate_offset: float
    sbp_offset: float
    temperature_offset: float
    height_cm: float
    bmi: float | None
    n_visits: int
    split: str
    profile: str = profiles_kb.ADULT
    modifiers: tuple[str, ...] = ()
    age_months: int = 0
    trimester: int | None = None
    #: This patient's resting behaviour, under the codes in app.behaviour.schema. Drawn
    #: once per patient, so the same person's eyes and voice are recognisably theirs from
    #: one visit to the next, which is what makes a change from rest mean anything.
    resting_behaviour: dict[str, float] = field(default_factory=dict)
    #: True where a resting observation was recorded for this patient at all. Where it was
    #: not, the platform has nothing to compare a later clip against — a common situation,
    #: and one the model has to have seen.
    behaviour_baseline_known: bool = False
    #: How much of their pain this patient shows in the face and in the voice. One
    #: multiplier each, because the two come apart: a stoic face above a strained voice is
    #: a real presentation.
    facial_expressiveness: float = 1.0
    vocal_expressiveness: float = 1.0

    @property
    def age_years(self) -> float:
        """Fractional below three years, where whole years cannot separate a newborn from
        a toddler and the profile depends on the difference."""
        if self.age_at_first_visit < profiles_kb.MONTH_PRECISION_UNDER_YEARS:
            return round(self.age_months / 12, 4)
        return float(self.age_at_first_visit)

    def band(self) -> reference_ranges.Band:
        return profiles_kb.band_for(profiles_kb.BY_CODE[self.profile], self.age_years)

    def resting(self) -> dict[str, float]:
        """This patient's own resting values: the lower part of the band for their profile,
        plus the individual offset that makes one patient differ from the next. This is what
        the generated readings are a departure from, and what the platform later compares
        them against."""
        band = self.band()
        ranges = reference_ranges.normal(band)
        if self.trimester is not None:
            ranges = reference_ranges.with_pregnancy(ranges, self.trimester)

        def centre(name: str, fallback: float) -> float:
            span = ranges.get(name)
            if span is None:
                return fallback
            low, high = span
            return low + RESTING_POSITION_IN_BAND * (high - low)

        resting = {
            "hr": centre("hr", 70.0) + self.hr_offset,
            "resp_rate": centre("resp_rate", 14.0) + self.resp_rate_offset,
            "temperature_c": centre("temperature_c", 36.8) + self.temperature_offset,
            "spo2": centre("spo2", 97.5),
        }
        systolic = ranges.get("sbp")
        if systolic is not None:
            resting["sbp"] = (
                centre("sbp", 122.0)
                + self.sbp_offset
                + (14.0 if "HYPERTENSION" in self.conditions else 0.0)
            )
            # Same proportion the visit readings use, so a resting diastolic and a recorded
            # one are comparable.
            resting["dbp"] = resting["sbp"] * DIASTOLIC_OF_SYSTOLIC
        else:
            # No blood-pressure band for this age, so none is generated rather than one
            # being made up. See reference_ranges on AAP2017.
            resting["sbp"] = None
            resting["dbp"] = None
        return resting


@dataclass
class Draft:
    rng: np.random.Generator
    patient: Patient
    archetype: Archetype
    visit_index: int
    age: int | None
    latent: float
    episode_side: str
    localised: bool = True
    sites: list[SiteContext] = field(default_factory=list)
    qualities: set[str] = field(default_factory=set)
    symptoms: set[str] = field(default_factory=set)
    factors: set[str] = field(default_factory=set)
    conditions: set[str] = field(default_factory=set)
    truth: dict[str, bool] = field(default_factory=dict)
    confounders: set[str] = field(default_factory=set)
    medications: list[MedicationContext] = field(default_factory=list)
    onset: str = "UNKNOWN"
    onset_speed: str = "UNKNOWN"
    pattern: str = "UNKNOWN"
    course: str = "UNKNOWN"
    recurrent: bool = False
    timing: set[str] = field(default_factory=set)
    duration_hours: float | None = None
    episodes_per_day: float | None = None
    episode_minutes: float | None = None
    radiates: bool | None = None
    recent_trauma: bool = False
    recent_surgery: bool = False
    functional_impact: dict[str, int] = field(default_factory=dict)
    vitals: dict[str, float] = field(default_factory=dict)
    answers: dict = field(default_factory=dict)
    #: What a camera and a microphone measured at this visit, and which modalities came
    #: back usable. Empty where no clip was recorded.
    behaviour: dict[str, float] = field(default_factory=dict)
    behaviour_modalities: set[str] = field(default_factory=set)

    @staticmethod
    def is_analgesic(entry: MedicationContext) -> bool:
        return entry.class_code in medications.ANALGESIC

    def add_medication(self, class_code: str, **fields) -> MedicationContext:
        entry = MedicationContext(class_code=class_code, **fields)
        self.medications = [e for e in self.medications if e.class_code != class_code]
        self.medications.append(entry)
        return entry

    def _side_for(self, structure: anatomy.Structure, explicit: str | None) -> str:
        if structure.laterality != anatomy.PAIRED:
            return structure.default_side()
        return explicit or self.episode_side

    def add_site(
        self,
        spec: str,
        role: str,
        *,
        origin: SiteContext | None = None,
        qualities: tuple[str, ...] | None = None,
        count: tuple[int, int] = (1, 1),
    ) -> SiteContext | None:
        code, explicit_side = _site_spec(spec)
        structure = anatomy.BY_CODE[code]
        if structure.sex is not None and structure.sex != self.patient.sex:
            return None
        side = self._side_for(structure, explicit_side)
        if any(site.code == code and site.side == side for site in self.sites):
            return None
        pool = qualities if qualities is not None else self.archetype.qualities
        if role == "RADIATING" and qualities is None:
            pool = self.archetype.radiating_qualities
        same_course = role == "PRIMARY" or self.rng.random() < 0.6
        site = SiteContext(
            code=code,
            side=side,
            role=role,
            qualities=frozenset(_sample(self.rng, pool, count)),
            onset=self.onset if same_course else None,
            pattern=self.pattern if same_course else None,
            course=self.course if same_course else None,
            radiation_from=f"{origin.code}|{origin.side}" if origin is not None else None,
        )
        self.sites.append(site)
        return site

    def candidate_site_codes(self) -> list[str]:
        present = {site.code for site in self.sites}
        pool: list[str] = []
        for spec, _ in self.archetype.secondary_sites + self.archetype.referred_sites:
            pool.append(_site_spec(spec)[0])
        for chain in self.archetype.radiation_chains:
            pool.extend(_site_spec(spec)[0] for spec in chain)
        if self.sites:
            region = anatomy.BY_CODE[self.sites[0].code].region
            pool.extend(
                structure.code
                for structure in anatomy.in_region(region)
                if structure.type == anatomy.REGION
            )
        seen: set[str] = set()
        out = []
        for code in pool:
            structure = anatomy.BY_CODE[code]
            if code in present or code in seen:
                continue
            if structure.sex is not None and structure.sex != self.patient.sex:
                continue
            seen.add(code)
            out.append(code)
        return out

    def resting_vitals(self) -> dict[str, float]:
        """The patient at their own rest, clipped to what is plausible for their band
        rather than to adult limits."""
        base = self.patient.resting()
        limits = reference_ranges.plausible(self.patient.band())
        ranges = reference_ranges.normal(self.patient.band())
        rng = self.rng

        def settle(name: str, value: float, noise: float) -> float:
            low, high = ranges.get(name, limits.get(name, (value, value)))
            return float(np.clip(value + rng.normal(0, noise), low, high))

        out = {
            "hr": round(settle("hr", base["hr"], 3)),
            "resp_rate": round(settle("resp_rate", base["resp_rate"], 1)),
        }
        if base["sbp"] is not None:
            systolic = settle("sbp", base["sbp"], 5)
            out["sbp"] = round(systolic)
            out["dbp"] = round(
                float(np.clip(systolic * DIASTOLIC_OF_SYSTOLIC + rng.normal(0, 3), 35, 130))
            )
        return out


@dataclass
class Record:
    patient_id: str
    assessment_id: str
    visit_index: int
    days_since_previous: float | None
    archetype: str
    scenario: str
    nrs: float
    split: str
    context: ClinicalContext
    # Which instrument produced the reference, and its score on that instrument's own
    # range. The target above is the projection of this onto 0-10.
    reference_scale: str = scales.NRS
    reference_raw: float = 0.0
    reference_max: float = scales.NRS_MAX


class Generator:
    def __init__(
        self,
        seed: int,
        patients: int,
        assessments: int,
        hard_case_share: float = DEFAULT_HARD_CASE_SHARE,
    ):
        if patients < 1 or assessments < patients:
            raise ValueError("there must be at least one patient and at least one visit each")
        if not 0.0 <= hard_case_share <= 1.0:
            raise ValueError("hard_case_share must be between 0 and 1")
        self.seed = seed
        self.n_patients = patients
        self.n_assessments = assessments
        self.hard_case_share = hard_case_share
        self.archetype_weights = tuple((a.code, a.weight) for a in ARCHETYPES)
        self.scenario_weights = tuple((s.code, s.weight) for s in scenario_kb.SCENARIOS)
        layout = np.random.default_rng([seed, 0])
        self.visit_counts = self._visit_counts(layout)
        self.splits = self._splits()

    def _visit_counts(self, rng: np.random.Generator) -> np.ndarray:
        mean = self.n_assessments / self.n_patients
        cap = max(8, round(5 * mean))
        if mean <= 1.0:
            return np.ones(self.n_patients, dtype=int)
        counts = np.clip(rng.geometric(1.0 / mean, size=self.n_patients), 1, cap)
        difference = self.n_assessments - int(counts.sum())
        while difference != 0:
            index = int(rng.integers(self.n_patients))
            if difference > 0 and counts[index] < cap:
                counts[index] += 1
                difference -= 1
            elif difference < 0 and counts[index] > 1:
                counts[index] -= 1
                difference += 1
        return counts

    def _splits(self) -> np.ndarray:
        groups = np.repeat(np.arange(self.n_patients), self.visit_counts)
        labels = np.array(["train"] * self.n_patients, dtype=object)
        first = GroupShuffleSplit(n_splits=1, test_size=TEST_SHARE, random_state=self.seed)
        rest, test = next(first.split(groups, groups=groups))
        labels[np.unique(groups[test])] = "test"
        second = GroupShuffleSplit(
            n_splits=1, test_size=VALIDATION_SHARE / (1 - TEST_SHARE), random_state=self.seed
        )
        _, validation = next(second.split(groups[rest], groups=groups[rest]))
        labels[np.unique(groups[rest][validation])] = "validation"
        return labels

    def _profile_and_archetype(self, rng: np.random.Generator):
        """Pick the population first, then a presentation that population can actually
        have. Picking the archetype first is what used to keep the generated set adult:
        no archetype reached below eight years, so no newborn was ever produced."""
        profile_code = _pick(rng, PROFILE_MIX) or profiles_kb.ADULT
        profile = profiles_kb.BY_CODE[profile_code]

        if profile_code in STATE_PROFILE_AGES:
            low, high = STATE_PROFILE_AGES[profile_code]
            preferred = STATE_PROFILE_ARCHETYPES.get(profile_code)
            if preferred is not None and rng.random() < preferred[1]:
                archetype = next(a for a in ARCHETYPES if a.code == preferred[0])
                low = max(low, archetype.age_range[0])
                high = min(high, archetype.age_range[1])
                return profile_code, archetype, low, high
        else:
            low = profile.min_age if profile.min_age is not None else 0.0
            high = (profile.max_age if profile.max_age is not None else 95.0) - 1e-9

        eligible = [a for a in ARCHETYPES if a.age_range[0] <= high and a.age_range[1] >= low]
        if not eligible:
            eligible = list(ARCHETYPES)
        weights = tuple((a.code, a.weight) for a in eligible)
        chosen = _pick(rng, weights) or eligible[0].code
        archetype = next(a for a in ARCHETYPES if a.code == chosen)
        return (
            profile_code,
            archetype,
            max(low, archetype.age_range[0]),
            min(high, archetype.age_range[1]),
        )

    def _modifiers(self, rng: np.random.Generator, profile_code: str) -> tuple[str, ...]:
        implied = set(profiles_kb.BY_CODE[profile_code].confounders)
        chosen = []
        for code, chance in MODIFIER_CHANCES.items():
            modifier = profiles_kb.BY_CODE[code]
            if set(modifier.confounders) & implied:
                continue
            if rng.random() < chance:
                chosen.append(code)
        return tuple(chosen)

    def patient(self, index: int) -> Patient:
        rng = np.random.default_rng([self.seed, index + 1])
        profile_code, archetype, low, high = self._profile_and_archetype(rng)
        if high <= low:
            age_years = float(low)
        else:
            age_years = float(rng.uniform(low, high))
        age = int(age_years)
        age_months = round(age_years * 12)
        modifiers = self._modifiers(rng, profile_code)
        trimester = int(rng.integers(1, 4)) if profile_code == profiles_kb.PREGNANT else None
        female_probability = archetype.female_probability
        if profile_code == profiles_kb.PREGNANT:
            female_probability = 1.0
        sex = "F" if rng.random() < female_probability else "M"
        conditions = _subset(rng, archetype.conditions)
        regular = []
        for condition, class_code, probability in CONDITION_MEDICATIONS:
            if (
                condition in conditions
                and class_code not in regular
                and rng.random() < probability
            ):
                regular.append(class_code)

        for class_code, probability in archetype.medications:
            if (
                class_code not in medications.ANALGESIC
                and class_code not in regular
                and rng.random() < probability
            ):
                regular.append(class_code)
        height = float(rng.normal(172 if sex == "M" else 160, 7))
        bmi = None
        if rng.random() >= 0.35:
            bmi = round(
                31.0 + rng.normal(0, 2.5)
                if "OBESITY" in conditions
                else float(rng.normal(25.5, 3.5)),
                1,
            )
        return Patient(
            index=index,
            patient_id=f"SYN-{index + 1:06d}",
            sex=sex,
            age_at_first_visit=age,
            birth_year=datetime.now(timezone.utc).year - age,
            archetype=archetype.code,
            trajectory=_pick(rng, archetype.trajectories) or "STABLE",
            side="LEFT" if rng.random() < 0.5 else "RIGHT",
            conditions=frozenset(conditions),
            regular_medications=tuple(regular),
            beta_blocker="ANTIHYPERTENSIVE" in regular and rng.random() < BETA_BLOCKER_SHARE,
            latent_centre=archetype.base_pain
            + float(rng.normal(0, archetype.pain_spread * 0.8)),
            hr_offset=float(rng.normal(0, 6)),
            resp_rate_offset=float(rng.normal(0, 1.2)),
            sbp_offset=float(rng.normal(0, 9)),
            temperature_offset=float(rng.normal(0, 0.2)),
            height_cm=height,
            bmi=bmi,
            n_visits=int(self.visit_counts[index]),
            split=str(self.splits[index]),
            profile=profile_code,
            modifiers=modifiers,
            age_months=age_months,
            trimester=trimester,
            resting_behaviour=self._resting_behaviour(rng, sex, age, age_months),
            behaviour_baseline_known=rng.random() < RESTING_OBSERVATION_PROBABILITY,
            facial_expressiveness=self._expressiveness(rng, profile_code, modifiers),
            vocal_expressiveness=self._expressiveness(rng, profile_code, modifiers),
        )

    @staticmethod
    def _expressiveness(
        rng: np.random.Generator, profile: str, modifiers: tuple[str, ...]
    ) -> float:
        centre, spread = EXPRESSIVENESS
        value = float(rng.normal(centre, spread))
        for code in (profile, *modifiers):
            value *= EXPRESSIVENESS_BY_PROFILE.get(code, 1.0)
        return max(EXPRESSIVENESS_FLOOR, value)

    @staticmethod
    def _resting_behaviour(
        rng: np.random.Generator, sex: str, age: int, age_months: int
    ) -> dict[str, float]:
        """This patient's eyes and voice at rest.

        Pitch is drawn from the band for their age and sex rather than from one centre,
        because a resting pitch of 300 Hz is a seven-year-old and a resting pitch of
        115 Hz is an adult man, and a generator that mixed them would teach a model that
        pitch carries no information about anything.
        """
        resting = {
            name: float(rng.normal(centre, spread))
            for name, (centre, spread) in RESTING_BEHAVIOUR.items()
        }
        years = age_months / 12 if age < profiles_kb.MONTH_PRECISION_UNDER_YEARS else float(age)
        if years < PITCH_INFANT_UNTIL_YEARS:
            centre, spread = INFANT_F0_HZ
        elif years < PITCH_ADULT_FROM_YEARS:
            centre, spread = CHILD_F0_HZ
        else:
            centre, spread = RESTING_F0_HZ[sex]
        resting["f0_mean_hz"] = float(rng.normal(centre, spread))
        return resting

    def _archetype_index(self, rng: np.random.Generator) -> int:
        code = _pick(rng, self.archetype_weights)
        return next(i for i, a in enumerate(ARCHETYPES) if a.code == code)

    def visits(self, patient: Patient) -> Iterator[Record]:
        rng = np.random.default_rng([self.seed, patient.index + 1, 1])
        archetype = ARCHETYPES[
            next(i for i, a in enumerate(ARCHETYPES) if a.code == patient.archetype)
        ]
        centre = patient.latent_centre
        cumulative_days = 0.0
        episode_duration: float | None = None
        episode_archetype = archetype.code
        carry: dict | None = None
        for k in range(1, patient.n_visits + 1):
            days = None if k == 1 else round(_log_uniform(rng, 1.0, 120.0), 1)
            cumulative_days += days or 0.0
            switched = k > 1 and rng.random() < ARCHETYPE_SWITCH_PROBABILITY
            if switched:
                visit_archetype = ARCHETYPES[self._archetype_index(rng)]
                visit_centre = visit_archetype.base_pain + float(
                    rng.normal(0, visit_archetype.pain_spread)
                )
            else:
                visit_archetype, visit_centre = archetype, centre
            new_episode = (
                k == 1
                or switched
                or episode_archetype != visit_archetype.code
                or not visit_archetype.chronic
            )
            if new_episode:
                low, high = visit_archetype.duration_hours
                episode_duration = _log_uniform(rng, low, high)
            else:
                episode_duration = (episode_duration or 0.0) + (days or 0.0) * 24.0
            episode_archetype = visit_archetype.code

            scenario = None
            if rng.random() < self.hard_case_share:
                scenario = scenario_kb.BY_CODE[_pick(rng, self.scenario_weights)]

            draft = self._draft(
                rng,
                patient,
                visit_archetype,
                k,
                switched,
                new_episode,
                cumulative_days,
                visit_centre,
                episode_duration,
                None if new_episode else carry,
            )
            carry = {
                "onset": draft.onset,
                "onset_speed": draft.onset_speed,
                "pattern": draft.pattern,
                "episodes_per_day": draft.episodes_per_day,
                "episode_minutes": draft.episode_minutes,
            }
            if scenario is not None and scenario.prepare is not None:
                scenario.prepare(rng, draft)
            self._derive(rng, draft)
            self._apply_missingness(rng, draft)
            if scenario is not None and scenario.finish is not None:
                scenario.finish(rng, draft)
            nrs, scale_code, raw, raw_max = self._reference(rng, draft)
            yield Record(
                patient_id=patient.patient_id,
                assessment_id=f"{patient.patient_id}-{k:03d}",
                visit_index=k,
                days_since_previous=days,
                archetype=visit_archetype.code,
                scenario=scenario.code if scenario is not None else scenario_kb.STANDARD,
                nrs=nrs,
                split=patient.split,
                context=self._context(draft),
                reference_scale=scale_code,
                reference_raw=raw,
                reference_max=raw_max,
            )

    def _draft(
        self,
        rng: np.random.Generator,
        patient: Patient,
        archetype: Archetype,
        k: int,
        switched: bool,
        new_episode: bool,
        cumulative_days: float,
        centre: float,
        duration: float,
        carry: dict | None,
    ) -> Draft:
        age = patient.age_years + cumulative_days / 365.25
        if age >= profiles_kb.MONTH_PRECISION_UNDER_YEARS:
            age = float(int(age))
        bilateral = rng.random() < archetype.bilateral_probability
        draft = Draft(
            rng=rng,
            patient=patient,
            archetype=archetype,
            visit_index=k,
            age=age,
            latent=0.0,
            episode_side="BILATERAL" if bilateral else patient.side,
            localised=rng.random() >= STRUCTURE_MISSING_PROBABILITY,
        )
        draft.conditions = set(patient.conditions)
        draft.symptoms = _subset(rng, archetype.symptoms)
        draft.factors = _subset(rng, archetype.factors)
        draft.recent_trauma = rng.random() < archetype.recent_trauma_probability
        draft.recent_surgery = rng.random() < archetype.recent_surgery_probability

        if carry is not None:
            draft.onset = carry["onset"]
            draft.onset_speed = carry["onset_speed"]
            draft.pattern = carry["pattern"]
            draft.episodes_per_day = carry["episodes_per_day"]
            draft.episode_minutes = carry["episode_minutes"]
        else:
            draft.onset_speed = (
                _pick(rng, archetype.onset_speed) if rng.random() >= 0.05 else "UNKNOWN"
            )
            if draft.onset_speed in ("SECONDS", "MINUTES"):
                draft.onset = "SUDDEN"
            elif draft.onset_speed in ("DAYS", "WEEKS_OR_MORE"):
                draft.onset = "GRADUAL"
            else:
                draft.onset = _pick(rng, archetype.onset) or "UNKNOWN"
            draft.pattern = _pick(rng, archetype.pattern) or "UNKNOWN"
            if draft.pattern == "EPISODIC":
                draft.episodes_per_day = round(float(rng.uniform(1, 8)), 1)
                draft.episode_minutes = round(float(rng.uniform(5, 180)))
        draft.duration_hours = round(duration, 1)
        flare_visit = patient.trajectory == FLARE and not switched and rng.random() < 0.35
        draft.course = self._course(
            rng, archetype, patient.trajectory if not switched else None, k, flare_visit
        )
        draft.recurrent = (
            rng.random() < archetype.recurrent_probability
            or (k > 1 and new_episode and not switched and rng.random() < 0.85)
            or (patient.trajectory == FLARE and not switched and rng.random() < 0.9)
        )
        draft.timing = _subset(rng, archetype.timing)
        if "NIGHT" in draft.factors and rng.random() < 0.8:
            draft.timing.add("NIGHT")
        if not draft.timing and rng.random() < 0.5:
            draft.timing.add("VARIABLE")

        for code, probability in archetype.confounders:
            if rng.random() < probability:
                draft.truth[STATE_OF_ARCHETYPE_CONFOUNDER[code]] = True
        if rng.random() < 0.04:
            draft.truth["recent_activity"] = True
        draft.truth["febrile"] = (
            "FEVER" in draft.symptoms or rng.random() < archetype.febrile_tendency * 0.3
        )

        latent = centre + self._drift(
            patient.trajectory if not switched else "STABLE", k, flare_visit
        )
        latent += float(rng.normal(0, archetype.pain_spread * 0.6))
        latent += 0.25 * len(draft.symptoms & symptoms_kb.ALARM_SYMPTOMS)
        if draft.course in ("WORSENING", "PROGRESSIVE"):
            latent += 0.5
        elif draft.course == "IMPROVING":
            latent -= 0.4
        if draft.recent_trauma:
            latent += 0.3

        latent -= 0.012 * max(0, age - 70)
        draft.latent = float(np.clip(latent, 0.0, 10.0))

        self._sites(rng, draft)
        self._medications(rng, draft)
        return draft

    @staticmethod
    def _drift(trajectory: str, k: int, flare_visit: bool) -> float:
        if trajectory == IMPROVING:
            return max(-4.5, -0.8 * (k - 1))
        if trajectory == WORSENING:
            return min(4.0, 0.6 * (k - 1))
        if trajectory == FLARE:
            return 2.0 if flare_visit else -0.6
        return 0.0

    @staticmethod
    def _course(
        rng, archetype: Archetype, trajectory: str | None, k: int, flare_visit: bool
    ) -> str:
        if k == 1 or trajectory is None:
            return _pick(rng, archetype.course) or "UNKNOWN"
        if trajectory == IMPROVING:
            return _pick(rng, (("IMPROVING", 0.65), ("STABLE", 0.3), ("WORSENING", 0.05)))
        if trajectory == WORSENING:
            return _pick(rng, (("WORSENING", 0.55), ("PROGRESSIVE", 0.15), ("STABLE", 0.3)))
        if trajectory == FLARE:
            if flare_visit:
                return _pick(rng, (("WORSENING", 0.6), ("STABLE", 0.4)))
            return _pick(rng, (("IMPROVING", 0.5), ("STABLE", 0.5)))
        return _pick(rng, archetype.course) or "UNKNOWN"

    def _sites(self, rng: np.random.Generator, draft: Draft) -> None:
        archetype = draft.archetype
        primary = None
        for _ in range(4):
            primary = draft.add_site(
                _pick(rng, archetype.primary_sites), "PRIMARY", count=archetype.quality_count
            )
            if primary is not None:
                break
        if primary is None:
            primary = draft.add_site(
                "REG_UNSPECIFIED", "PRIMARY", count=archetype.quality_count
            )
        for spec, probability in archetype.secondary_sites:
            if rng.random() < probability:
                draft.add_site(spec, "SECONDARY")
        radiating = False
        if archetype.radiation_chains and rng.random() < archetype.radiation_probability:
            compatible = [
                chain
                for chain in archetype.radiation_chains
                if self._chain_fits(chain, draft.episode_side)
            ]
            if compatible:
                chain = compatible[int(rng.integers(len(compatible)))]
                origin = primary
                for spec in chain:
                    site = draft.add_site(spec, "RADIATING", origin=origin, count=(1, 2))
                    if site is None:
                        break
                    origin, radiating = site, True
        for spec, probability in archetype.referred_sites:
            if rng.random() < probability:
                draft.add_site(spec, "REFERRED", origin=primary)
        if radiating:
            draft.radiates = True if rng.random() < 0.97 else None
        else:
            draft.radiates = False if rng.random() < 0.9 else None
        draft.qualities = set().union(*(site.qualities for site in draft.sites))
        if not draft.qualities:
            draft.qualities = _sample(rng, archetype.qualities, archetype.quality_count)

    @staticmethod
    def _chain_fits(chain: tuple[str, ...], episode_side: str) -> bool:
        for spec in chain:
            code, explicit = _site_spec(spec)
            laterality = anatomy.BY_CODE[code].laterality
            if laterality in (anatomy.LEFT, anatomy.RIGHT) and episode_side not in (
                laterality,
                "BILATERAL",
            ):
                return False
            if (
                explicit
                and laterality == anatomy.PAIRED
                and explicit not in anatomy.SIDES_FOR_LATERALITY[laterality]
            ):
                return False
        return True

    def _medications(self, rng: np.random.Generator, draft: Draft) -> None:
        for class_code in draft.patient.regular_medications:
            self._add_drawn_medication(rng, draft, class_code, regular=True)
        for class_code, probability in draft.archetype.medications:
            if class_code in draft.patient.regular_medications:
                continue
            if class_code not in medications.ANALGESIC:
                continue
            probability *= float(np.clip(0.35 + draft.latent / 9.0, 0.3, 1.3))
            if rng.random() < probability:
                self._add_drawn_medication(rng, draft, class_code, regular=False)

    def _add_drawn_medication(
        self, rng, draft: Draft, class_code: str, *, regular: bool
    ) -> None:
        analgesic = class_code in medications.ANALGESIC
        frequency = _pick(rng, REGULAR_FREQUENCY if regular else ANALGESIC_FREQUENCY)
        hours = None
        if rng.random() >= DOSE_TIMING_MISSING_PROBABILITY:
            hours = round(_log_uniform(rng, 0.5, 72.0), 1)
        pain_effect = "UNKNOWN"
        if analgesic:
            pain_effect = _pick(
                rng,
                (
                    ("GOOD", max(0.1, 8.0 - draft.latent)),
                    ("PARTIAL", 5.0),
                    ("NONE", max(0.1, draft.latent - 2.0)),
                    ("UNKNOWN", 1.0),
                ),
            )
        sedation = "UNKNOWN"
        if class_code in medications.SEDATING:
            sedation = _pick(rng, (("NONE", 0.5), ("MILD", 0.35), ("MARKED", 0.15)))
        elif rng.random() < 0.6:
            sedation = "NONE"
        draft.add_medication(
            class_code,
            dose_category=_pick(rng, DOSE_WEIGHTS),
            frequency=frequency,
            hours_since_last_dose=hours,
            pain_effect=pain_effect,
            sedation_effect=sedation,
        )

    def _derive(self, rng: np.random.Generator, draft: Draft) -> None:
        self._treatment_states(draft)
        for state, present in draft.truth.items():
            if present and state in RECORDED_AS:
                code, probability = RECORDED_AS[state]
                if rng.random() < probability:
                    draft.confounders.add(code)
        self._functional_impact(rng, draft)
        self._vitals(rng, draft)
        self._behaviour(rng, draft)
        self._answers(rng, draft)


    def _behaviour(self, rng: np.random.Generator, draft: Draft) -> None:
        """What a camera and a microphone would have measured at this visit.

        Built the same way as the vitals: the patient's own resting value, plus the pain,
        plus every confounding state in play, plus noise. Then the quality gate is applied
        — because a clip is only as good as what the patient did in front of the lens, and
        a model that has only ever seen complete observations will lean on them.
        """
        if rng.random() >= OBSERVATION_PROBABILITY:
            return

        patient = draft.patient
        resting = patient.resting_behaviour
        latent = draft.latent
        shifts: dict[str, float] = {}
        for state, present in draft.truth.items():
            if not present:
                continue
            for name, amount in BEHAVIOUR_SHIFT.get(state, {}).items():
                shifts[name] = shifts.get(name, 0.0) + amount

        def noise(name: str) -> float:
            return float(rng.normal(0, BEHAVIOUR_NOISE[name]))

        # Expressiveness multiplies what the pain drives and nothing else. A pupil widened
        # by fear is as wide in a stoic patient as in anyone, so the confounder shifts are
        # added afterwards at full size.
        def gain(name: str) -> float:
            return (
                patient.vocal_expressiveness
                if name in VOCAL_MEASURES
                else patient.facial_expressiveness
            )

        def rise(name: str) -> float:
            driven = BEHAVIOUR_PER_POINT.get(name, 0.0) * latent * gain(name)
            return driven + shifts.get(name, 0.0)

        def threshold(name: str) -> float:
            start, slope = BEHAVIOUR_THRESHOLDS[name]
            driven = max(0.0, latent - start) * slope * gain(name)
            return driven + shifts.get(name, 0.0)

        squint = float(np.clip(rise("eye_squint_index") + noise("eye_squint_index"), 0.0, 0.95))
        brow_index = float(np.clip(rise("brow_lower_index") + noise("brow_lower_index"), 0.0, 0.95))
        aperture = float(
            np.clip(
                resting["eye_aperture_ratio"] * (1 - squint)
                + shifts.get("eye_aperture_ratio", 0.0)
                + noise("eye_aperture_ratio"),
                0.05,
                1.0,
            )
        )
        brow_gap = float(
            np.clip(resting["brow_gap_ratio"] * (1 - brow_index) + noise("brow_gap_ratio"), 0.05, 0.5)
        )
        pupil = float(
            np.clip(
                resting["pupil_diameter_mm"] + rise("pupil_diameter_mm") + noise("pupil_diameter_mm"),
                1.2,
                8.5,
            )
        )
        pitch = float(
            np.clip(
                resting["f0_mean_hz"]
                * (1 + F0_RISE_PER_POINT * latent * patient.vocal_expressiveness)
                + shifts.get("f0_mean_hz", 0.0)
                + noise("f0_mean_hz"),
                *behaviour_schema.F0_RANGE_HZ,
            )
        )

        eye = {
            "eye_aperture_ratio": aperture,
            "eye_squint_index": squint,
            "eye_open_share": float(np.clip(0.93 + noise("eye_open_share"), 0.2, 1.0)),
            "eye_asymmetry_ratio": abs(noise("eye_asymmetry_ratio")),
            "blink_rate_per_min": float(
                np.clip(
                    resting["blink_rate_per_min"] + rise("blink_rate_per_min") + noise("blink_rate_per_min"),
                    0.0,
                    90.0,
                )
            ),
            "blink_closure_ms": float(np.clip(170.0 + noise("blink_closure_ms"), 70.0, 480.0)),
            "long_closure_share": float(
                np.clip(threshold("long_closure_share") + abs(noise("long_closure_share")), 0.0, 1.0)
            ),
            "pupil_diameter_mm": pupil,
            "pupil_iris_ratio": float(np.clip(pupil / behaviour_schema.IRIS_DIAMETER_MM, 0.1, 0.8)),
            "pupil_unrest_mm": float(
                np.clip(0.06 + rise("pupil_unrest_mm") + abs(noise("pupil_unrest_mm")), 0.0, 1.8)
            ),
            "pupil_asymmetry_mm": abs(noise("pupil_asymmetry_mm")),
            "gaze_dispersion_ratio": float(
                np.clip(0.03 + rise("gaze_dispersion_ratio") + abs(noise("gaze_dispersion_ratio")), 0.0, 1.0)
            ),
        }
        face = {
            "brow_gap_ratio": brow_gap,
            "brow_lower_index": brow_index,
            "mouth_open_ratio": float(
                np.clip(0.03 + rise("mouth_open_ratio") + abs(noise("mouth_open_ratio")), 0.0, 0.5)
            ),
            "face_motion_index": float(
                np.clip(0.05 + rise("face_motion_index") + abs(noise("face_motion_index")), 0.0, 5.0)
            ),
            "head_turn_share": float(np.clip(abs(noise("head_turn_share")), 0.0, 1.0)),
        }
        voice = {
            "f0_mean_hz": pitch,
            "f0_sd_semitones": float(np.clip(1.0 + rise("f0_sd_semitones") + noise("f0_sd_semitones"), 0.0, 12.0)),
            "jitter_percent": float(np.clip(0.5 + rise("jitter_percent") + noise("jitter_percent"), 0.0, 20.0)),
            "shimmer_percent": float(np.clip(2.0 + rise("shimmer_percent") + noise("shimmer_percent"), 0.0, 40.0)),
            "hnr_db": float(np.clip(20.0 + rise("hnr_db") + noise("hnr_db"), -10.0, 40.0)),
            "intensity_db": float(
                np.clip(resting["intensity_db"] + shifts.get("intensity_db", 0.0) + noise("intensity_db"), -80.0, 0.0)
            ),
            "voiced_share": float(np.clip(0.45 + noise("voiced_share"), 0.0, 1.0)),
            "pause_share": float(np.clip(0.12 + rise("pause_share") + abs(noise("pause_share")), 0.0, 1.0)),
            "speech_rate_per_s": float(
                np.clip(resting["speech_rate_per_s"] + rise("speech_rate_per_s") + noise("speech_rate_per_s"), 0.0, 12.0)
            ),
            "vocalisation_share": float(
                np.clip(threshold("vocalisation_share") + abs(noise("vocalisation_share")), 0.0, 1.0)
            ),
            "spectral_centroid_hz": float(np.clip(1100.0 + 18.0 * latent + noise("spectral_centroid_hz"), 100.0, 11000.0)),
            "spectral_rolloff_hz": float(np.clip(1900.0 + 30.0 * latent + noise("spectral_rolloff_hz"), 100.0, 11000.0)),
            "zero_crossing_rate": float(np.clip(0.14 + abs(noise("zero_crossing_rate")), 0.0, 1.0)),
        }

        # The quality gate, as the extractor would apply it. A patient who cannot be asked
        # for a score is also the patient least likely to hold a gaze or speak a sentence,
        # so the modalities fail more often for them — which is precisely the population
        # the behavioural channel is supposed to serve, and the model has to see that.
        hard = not profiles_kb.BY_CODE[patient.profile].can_self_report
        eyes_usable = rng.random() >= EYES_UNUSABLE_PROBABILITY * (2.0 if hard else 1.0)
        voice_usable = rng.random() >= VOICE_UNUSABLE_PROBABILITY * (2.0 if hard else 1.0)
        if not eyes_usable and not voice_usable:
            return

        measured: dict[str, float] = {}
        if eyes_usable:
            measured.update(eye)
            draft.behaviour_modalities.add(behaviour_schema.EYE)
        # The facial measures survive the eyes being shut: a brow and a mouth are visible
        # either way. What they lose is the composite, which is built from eye actions.
        measured.update(face)
        draft.behaviour_modalities.add(behaviour_schema.FACE)
        if voice_usable:
            measured.update(voice)
            draft.behaviour_modalities.add(behaviour_schema.VOICE)

        parts = [measured[name] for name in ("eye_squint_index", "long_closure_share", "brow_lower_index") if name in measured]
        if parts:
            measured["facial_action_index"] = float(np.mean(parts))
        draft.behaviour = {name: round(value, 4) for name, value in measured.items()}

    @staticmethod
    def _treatment_states(draft: Draft) -> None:
        classes = {entry.class_code for entry in draft.medications}
        recent = [
            entry
            for entry in draft.medications
            if entry.hours_since_last_dose is not None
            and entry.hours_since_last_dose <= ANALGESIA_RECENT_HOURS
        ]
        draft.truth["opioid_regular"] = any(
            entry.class_code == "OPIOID" and entry.frequency in REGULAR_FREQUENCIES
            for entry in draft.medications
        )
        draft.truth["opioid_recent"] = any(entry.class_code == "OPIOID" for entry in recent)
        draft.truth["analgesia_recent"] = any(Draft.is_analgesic(entry) for entry in recent)
        draft.truth["antihypertensive"] = "ANTIHYPERTENSIVE" in classes
        if "ANTIHYPERTENSIVE" in classes and draft.patient.beta_blocker:
            draft.truth["beta_blocker"] = True
        draft.truth["antidepressant"] = "ANTIDEPRESSANT" in classes
        draft.truth["sedative"] = "SEDATIVE" in classes
        draft.truth["triptan"] = "TRIPTAN" in classes

    def _functional_impact(self, rng: np.random.Generator, draft: Draft) -> None:
        if rng.random() < IMPACT_BLOCK_MISSING_PROBABILITY:
            return
        regions = {anatomy.BY_CODE[site.code].region for site in draft.sites}
        for domain in FUNCTIONAL_DOMAINS:
            if rng.random() < DOMAIN_MISSING_PROBABILITY:
                continue
            weight = DOMAIN_WEIGHT[domain]
            if domain == "mobility" and regions & {"LOWER_LIMB", "BACK"}:
                weight = 1.15
            elif domain == "mobility" and regions & {"HEAD"}:
                weight = 0.6
            if domain == "sleep" and "NIGHT" in draft.timing:
                weight = 1.2
            if domain == "self_care" and "UPPER_LIMB" in regions:
                weight = 0.9
            score = draft.latent * 0.45 * weight + rng.normal(0, 0.75)
            draft.functional_impact[domain] = int(np.clip(round(score), 0, 4))

    def _vitals(self, rng: np.random.Generator, draft: Draft) -> None:
        patient = draft.patient
        base = patient.resting()
        truth = draft.truth

        def shift(vital: str) -> float:
            total = 0.0
            for state, present in truth.items():
                if present:
                    total += STATE_SHIFTS.get(state, {}).get(vital, 0.0)
            return total

        band = patient.band()
        limits = reference_ranges.plausible(band)

        def bound(name: str, value: float, floor: float, ceiling: float) -> float:
            low, high = limits.get(name, (floor, ceiling))
            return float(np.clip(value, low, high))

        temperature = base["temperature_c"] + rng.normal(0, 0.2)
        if truth.get("febrile"):
            temperature += float(rng.uniform(0.9, 2.6))
            if truth.get("analgesia_recent") and any(
                entry.class_code in ("NSAID", "ACETAMINOPHEN") for entry in draft.medications
            ):
                temperature -= 0.6
        activity_extra = float(rng.uniform(0, 10)) if truth.get("recent_activity") else 0.0

        # The shifts below were written for an adult. A band that is wider has more room
        # to move in, so an excursion is scaled by the ratio of band widths rather than
        # applied as a fixed number of beats. Scaling by resting value instead pushes a
        # newborn past 240 beats, which the band does not support.
        def width_scale(name: str) -> float:
            own = reference_ranges.normal(band).get(name)
            adult = reference_ranges.ADULT_BAND.normal.get(name)
            if own is None or adult is None or adult[1] <= adult[0]:
                return 1.0
            return (own[1] - own[0]) / (adult[1] - adult[0])

        hr_scale = width_scale("hr")
        resp_scale = width_scale("resp_rate")

        hr = base["hr"] + hr_scale * (
            0.95 * draft.latent
            + shift("hr")
            + activity_extra
            + 9 * max(0.0, temperature - 37.5)
            + rng.normal(0, 6)
        )
        resp = base["resp_rate"] + resp_scale * (
            0.3 * draft.latent + shift("resp_rate") + rng.normal(0, 1.6)
        )
        if base["sbp"] is None:
            sbp = None
            dbp = None
        else:
            sbp = base["sbp"] + 1.0 * draft.latent + shift("sbp") + rng.normal(0, 10)
            dbp = sbp * DIASTOLIC_OF_SYSTOLIC + shift("dbp") + rng.normal(0, 5)

        saturation = 97.6 + rng.normal(0, 0.9)
        if draft.archetype.affects_saturation:
            saturation -= float(rng.uniform(0, 7)) * float(np.clip(draft.latent / 10, 0.1, 1.0))
        if draft.conditions & {"COPD", "ASTHMA"}:
            saturation -= float(rng.uniform(0, 3))
        glucose = 5.3 + rng.normal(0, 0.7)
        if draft.conditions & {"DIABETES_T1", "DIABETES_T2"}:
            glucose += float(rng.uniform(1.5, 7.5))
            if "ANTIDIABETIC" in {entry.class_code for entry in draft.medications}:
                glucose -= 1.0
        if "CORTICOSTEROID" in {entry.class_code for entry in draft.medications}:
            glucose += 1.5

        draft.vitals = {
            "hr": round(bound("hr", hr, 35, 190)),
            "resp_rate": round(bound("resp_rate", resp, 8, 45)),
            "spo2": round(bound("spo2", min(saturation, 100.0), 78, 100)),
            "temperature_c": round(bound("temperature_c", temperature, 34.5, 41.5), 1),
            "glucose_mmol": round(bound("glucose_mmol", glucose, 2.0, 30.0), 1),
        }
        if sbp is not None:
            draft.vitals["sbp"] = round(bound("sbp", sbp, 70, 220))
            draft.vitals["dbp"] = round(bound("dbp", dbp, 40, 130))
        if patient.bmi is not None:
            draft.vitals["bmi"] = patient.bmi

    def _answers(self, rng: np.random.Generator, draft: Draft) -> None:
        answers: dict = {}
        below_knee = any(
            site.code in ("REG_LEG", "REG_FOOT") and site.role == "RADIATING"
            for site in draft.sites
        )
        for code, value, probability in draft.archetype.answers:
            if rng.random() < probability:
                answers[code] = below_knee if code == "BACK_RADIATION_BELOW_KNEE" else value
        if draft.recurrent or (draft.visit_index > 1 and rng.random() < 0.85):
            answers["FIRST_EPISODE"] = False
        else:
            answers["FIRST_EPISODE"] = rng.random() < 0.6
        if answers["FIRST_EPISODE"] is False and rng.random() < 0.5:
            answers["SIMILAR_PAST_PAIN"] = rng.random() < 0.7
        answers["REGULAR_MEDICATION"] = any(
            entry.frequency in REGULAR_FREQUENCIES for entry in draft.medications
        )
        if draft.recent_trauma and rng.random() < 0.6:
            answers["TRAUMA_RECENT"] = True
        if draft.recent_surgery:
            answers["SURGERY_LAST_30_DAYS"] = True
        draft.answers = answers

    @staticmethod
    def _apply_missingness(rng: np.random.Generator, draft: Draft) -> None:
        for name, probability in VITAL_MISSING_PROBABILITY.items():
            if rng.random() < probability:
                draft.vitals.pop(name, None)
        draft.answers = {
            code: value
            for code, value in draft.answers.items()
            if rng.random()
            >= (0.1 if code == "REGULAR_MEDICATION" else ANSWER_MISSING_PROBABILITY)
        }

    @staticmethod
    def _reference(rng: np.random.Generator, draft: Draft) -> tuple[float, str, float, float]:
        """The reference score for this visit, and which instrument produced it.

        A patient who can be asked gives a 0-10 rating. One who cannot is scored by the
        clinician on the observational scale their profile names, and that raw score is
        projected onto 0-10 the same way the platform projects a real one. The projection
        is coarser than a rating, because the instruments are coarser, and the model is
        trained against that coarseness rather than against a precision nobody had.
        """
        spread = BASE_REPORT_NOISE
        for state, extra in REPORT_NOISE.items():
            if draft.truth.get(state):
                spread += extra
        relief = 0.0
        if draft.truth.get("analgesia_recent"):
            effects = [
                entry.pain_effect
                for entry in draft.medications
                if Draft.is_analgesic(entry)
                and entry.hours_since_last_dose is not None
                and entry.hours_since_last_dose <= ANALGESIA_RECENT_HOURS
            ]
            relief = max((RELIEF_SHIFT.get(effect, 0.0) for effect in effects), default=0.0)

        perceived = float(np.clip(draft.latent - relief + rng.normal(0, spread), 0, 10))
        profile = profiles_kb.BY_CODE[draft.patient.profile]
        scale_code = profiles_kb.reference_scale_for(profile)
        scale = scales.BY_CODE[scale_code]

        if scale.steps:
            # A rating or a faces scale: the patient picks one of the offered values.
            nearest = min(scale.steps, key=lambda step: abs(step - perceived))
            raw = float(nearest)
        else:
            # An observational scale: the clinician scores the instrument, so the score
            # lands on one of its whole totals.
            fraction = perceived / scales.NRS_MAX
            raw = round(scale.minimum + fraction * (scale.maximum - scale.minimum))
            raw = float(min(max(raw, scale.minimum), scale.maximum))

        return scales.normalise(scale_code, raw), scale_code, raw, scale.maximum

    @staticmethod
    def _context(draft: Draft) -> ClinicalContext:
        locations = set()
        sides = set()
        for site in draft.sites:
            structure = anatomy.BY_CODE[site.code]
            locations.add(structure.location_for(site.side))
            sides.add(site.side)
        return ClinicalContext(
            age=draft.age,
            sex=draft.patient.sex,
            pain_locations=frozenset(locations),
            anatomical_structures=frozenset(site.code for site in draft.sites)
            if draft.localised
            else frozenset(),
            sides=frozenset(sides),
            sites=tuple(draft.sites) if draft.localised else (),
            qualities=frozenset(draft.qualities),
            symptoms=frozenset(draft.symptoms),
            conditions=frozenset(draft.conditions),
            factors=frozenset(draft.factors),
            confounders=frozenset(draft.confounders),
            medications=tuple(draft.medications),
            onset=draft.onset,
            onset_speed=draft.onset_speed,
            pattern=draft.pattern,
            course=draft.course,
            recurrent=draft.recurrent,
            timing=frozenset(draft.timing),
            duration_hours=draft.duration_hours,
            episodes_per_day=draft.episodes_per_day,
            episode_minutes=draft.episode_minutes,
            radiates=draft.radiates,
            recent_trauma=draft.recent_trauma,
            recent_surgery=draft.recent_surgery,
            functional_impact=dict(draft.functional_impact),
            vitals=dict(draft.vitals),
            answers=dict(draft.answers),
            profile=draft.patient.profile,
            profile_modifiers=frozenset(draft.patient.modifiers),
            pregnancy_trimester=draft.patient.trimester,
            expected_pain=draft.archetype.code == "OBSTETRIC_LABOUR",
            baseline_vitals={
                name: round(value, 1)
                for name, value in draft.patient.resting().items()
                if value is not None
            },
            baseline_points=BASELINE_READINGS,
            baseline_source="CALIBRATION",
            behaviour=dict(draft.behaviour),
            behaviour_baseline=(
                {
                    name: round(value, 4)
                    for name, value in draft.patient.resting_behaviour.items()
                }
                if draft.patient.behaviour_baseline_known
                else {}
            ),
            behaviour_modalities=frozenset(draft.behaviour_modalities),
        )

    def patients(self) -> Iterator[Patient]:
        for index in range(self.n_patients):
            yield self.patient(index)

    def records(self) -> Iterator[tuple[Patient, Record]]:
        for patient in self.patients():
            for record in self.visits(patient):
                yield patient, record


class Summary:
    def __init__(self):
        self.rows = 0
        self.archetypes = Counter()
        self.archetype_nrs = Counter()
        self.scenarios = Counter()
        self.nrs_histogram = Counter()
        self.nrs_total = 0.0
        self.nrs_square_total = 0.0
        self.vitals_recorded = Counter()
        self.split_rows = Counter()
        self.split_patients = Counter()
        self.sex = Counter()
        self.age_bands = Counter()
        self.regions = Counter()
        self.structure_types = Counter()
        self.localised = 0
        self.site_counts = Counter()
        self.roles = Counter()
        self.medication_classes = Counter()
        self.confounders = Counter()
        self.quality_levels = Counter()
        self.visits_per_patient = Counter()
        self.conditions = Counter()

    def add_patient(self, patient: Patient) -> None:
        self.split_patients[patient.split] += 1
        self.visits_per_patient[str(patient.n_visits)] += 1

    def add(self, record: Record) -> None:
        ctx = record.context
        self.rows += 1
        self.archetypes[record.archetype] += 1
        self.archetype_nrs[record.archetype] += record.nrs
        self.scenarios[record.scenario] += 1
        self.nrs_histogram[str(round(record.nrs))] += 1
        self.nrs_total += record.nrs
        self.nrs_square_total += record.nrs * record.nrs
        self.vitals_recorded.update(ctx.vitals.keys())
        self.split_rows[record.split] += 1
        self.sex[ctx.sex] += 1
        if ctx.age is not None:
            self.age_bands[f"{(ctx.age // 10) * 10}-{(ctx.age // 10) * 10 + 9}"] += 1
        self.regions.update(ctx.regions)
        self.structure_types.update(ctx.structure_types)
        if ctx.sites:
            self.localised += 1
        self.site_counts[str(len(ctx.sites))] += 1
        self.roles.update(site.role for site in ctx.sites)
        self.medication_classes.update(ctx.medication_classes)
        self.confounders.update(ctx.confounders)
        self.conditions.update(ctx.conditions)
        self.quality_levels[quality.assess(ctx).level.value] += 1

    def distribution(self) -> dict:
        mean = self.nrs_total / self.rows if self.rows else 0.0
        variance = self.nrs_square_total / self.rows - mean * mean if self.rows else 0.0
        return {
            "archetypes": dict(self.archetypes.most_common()),
            "archetype_mean_nrs": {
                code: round(self.archetype_nrs[code] / count, 2)
                for code, count in self.archetypes.items()
            },
            "scenarios": dict(self.scenarios.most_common()),
            "regions": dict(self.regions.most_common()),
            "structure_types": dict(self.structure_types.most_common()),
            "structures_localised": self.localised,
            "sites_per_record": dict(sorted(self.site_counts.items())),
            "site_roles": dict(self.roles.most_common()),
            "sex": dict(self.sex),
            "age_bands": dict(self.age_bands.most_common()),
            "self_report_histogram": {
                str(score): self.nrs_histogram[str(score)] for score in range(11)
            },
            "self_report_mean": round(mean, 2),
            "self_report_sd": round(math.sqrt(max(variance, 0.0)), 2),
            "vitals_recorded": dict(self.vitals_recorded.most_common()),
            "medication_classes": dict(self.medication_classes.most_common()),
            "confounders": dict(self.confounders.most_common()),
            "conditions_recorded": dict(self.conditions.most_common(12)),
            "quality_levels": dict(self.quality_levels.most_common()),
            "visits_per_patient": dict(
                sorted(self.visits_per_patient.items(), key=lambda kv: int(kv[0]))
            ),
        }


def version_for(
    seed: int, patients: int, assessments: int, moment: datetime | None = None
) -> str:
    stamp = (moment or datetime.now(timezone.utc)).date().isoformat()
    return f"synthetic-v{GENERATOR_VERSION}-{stamp}-seed{seed}-p{patients}-n{assessments}"


ASSESSMENT_COLUMNS = (
    ("patient_id", pa.string()),
    ("assessment_id", pa.string()),
    ("visit_index", pa.int32()),
    ("days_since_previous", pa.float64()),
    ("archetype", pa.string()),
    ("scenario", pa.string()),
    ("profile", pa.string()),
    ("nrs", pa.float64()),
    # The instrument behind the target, and its own score. Kept beside the projection so a
    # metric can be reported per instrument rather than only pooled across all of them.
    ("reference_scale", pa.string()),
    ("reference_raw", pa.float64()),
    ("reference_max", pa.float64()),
    ("split", pa.string()),
    ("context_json", pa.string()),
)
TARGET_COLUMN = "nrs"
FEATURE_COLUMN_PREFIX = "f_"


def feature_column(name: str) -> str:
    return FEATURE_COLUMN_PREFIX + name


FEATURE_COLUMNS = tuple(feature_column(name) for name in features.NAMES)


def assessment_schema() -> pa.Schema:
    fields = [pa.field(name, kind) for name, kind in ASSESSMENT_COLUMNS]
    fields += [pa.field(column, pa.float64()) for column in FEATURE_COLUMNS]
    return pa.schema(fields)


def _row(record: Record) -> dict:
    row = {
        "patient_id": record.patient_id,
        "assessment_id": record.assessment_id,
        "visit_index": record.visit_index,
        "days_since_previous": record.days_since_previous,
        "archetype": record.archetype,
        "scenario": record.scenario,
        "profile": record.context.profile,
        TARGET_COLUMN: record.nrs,
        "reference_scale": record.reference_scale,
        "reference_raw": record.reference_raw,
        "reference_max": record.reference_max,
        "split": record.split,
        "context_json": json.dumps(
            context_module.to_dict(record.context), separators=(",", ":")
        ),
    }
    vector = features.vector(record.context)
    for column, value in zip(FEATURE_COLUMNS, vector):
        row[column] = float(value)
    return row


def _patient_row(patient: Patient) -> dict:
    resting = patient.resting()
    return {
        "patient_id": patient.patient_id,
        "sex": patient.sex,
        "birth_year": patient.birth_year,
        "age_at_first_visit": patient.age_at_first_visit,
        "conditions": json.dumps(sorted(patient.conditions)),
        "regular_medications": json.dumps(list(patient.regular_medications)),
        "archetype": patient.archetype,
        "trajectory": patient.trajectory,
        "resting_hr": round(resting["hr"], 1),
        "resting_resp_rate": round(resting["resp_rate"], 1),
        "resting_sbp": None if resting["sbp"] is None else round(resting["sbp"], 1),
        "resting_temperature_c": round(resting["temperature_c"], 2),
        "profile": patient.profile,
        "profile_modifiers": json.dumps(list(patient.modifiers)),
        "age_months": patient.age_months,
        "trimester": patient.trimester,
        "bmi": patient.bmi,
        "height_cm": round(patient.height_cm, 1),
        "n_visits": patient.n_visits,
        "split": patient.split,
    }


PATIENT_SCHEMA = pa.schema(
    [
        ("patient_id", pa.string()),
        ("sex", pa.string()),
        ("birth_year", pa.int32()),
        ("age_at_first_visit", pa.int32()),
        ("conditions", pa.string()),
        ("regular_medications", pa.string()),
        ("archetype", pa.string()),
        ("trajectory", pa.string()),
        ("resting_hr", pa.float64()),
        ("resting_resp_rate", pa.float64()),
        ("resting_sbp", pa.float64()),
        ("resting_temperature_c", pa.float64()),
        ("profile", pa.string()),
        ("profile_modifiers", pa.string()),
        ("age_months", pa.int32()),
        ("trimester", pa.int32()),
        ("bmi", pa.float64()),
        ("height_cm", pa.float64()),
        ("n_visits", pa.int32()),
        ("split", pa.string()),
    ]
)


def _write_reference_tables(directory: Path) -> None:
    storage.write_table(
        directory / "anatomy" / "anatomy_master.parquet",
        [
            {
                "code": s.code,
                "label": s.label,
                "type": s.type,
                "region": s.region,
                "laterality": s.laterality,
                "latin": s.latin,
                "parent": s.parent,
                "subregion": s.subregion or anatomy.subregion_of(s.code),
                "location": s.location,
                "sex": s.sex,
            }
            for s in anatomy.STRUCTURES
        ],
    )
    pain_rows = [
        {
            "kind": "QUALITY",
            "code": q.code,
            "label": q.label,
            "group": None,
            "parent": None,
            "neuropathic_hint": q.neuropathic_hint,
        }
        for q in qualities_kb.QUALITIES
    ] + [
        {
            "kind": "PAIN_TYPE",
            "code": t.code,
            "label": t.label,
            "group": t.group,
            "parent": t.parent,
            "neuropathic_hint": None,
        }
        for t in pain_types.PAIN_TYPES
    ]
    storage.write_table(directory / "pain" / "pain_master.parquet", pain_rows)
    clinical_rows = (
        [
            {
                "kind": "SYMPTOM",
                "code": s.code,
                "label": s.label,
                "group": s.group,
                "detail": json.dumps({"systemic": s.systemic, "alarm": s.alarm}),
            }
            for s in symptoms_kb.SYMPTOMS
        ]
        + [
            {
                "kind": "DISEASE",
                "code": d.code,
                "label": d.label,
                "group": d.category,
                "detail": json.dumps({"pain_relevant": d.pain_relevant}),
            }
            for d in diseases.DISEASES
        ]
        + [
            {
                "kind": "FACTOR",
                "code": f.code,
                "label": f.label,
                "group": f.kind,
                "detail": "{}",
            }
            for f in factors.FACTORS
        ]
        + [
            {
                "kind": "CONFOUNDER",
                "code": c.code,
                "label": c.label,
                "group": None,
                "detail": json.dumps({"affects": list(c.affects)}),
            }
            for c in confounders.CONFOUNDERS
        ]
        + [
            {
                "kind": "MEDICATION_CLASS",
                "code": m.code,
                "label": m.label,
                "group": None,
                "detail": json.dumps(
                    {
                        "analgesic": m.analgesic,
                        "sedating": m.sedating,
                        "affects": list(m.affects),
                    }
                ),
            }
            for m in medications.MEDICATION_CLASSES
        ]
        + [
            {
                "kind": "QUESTION",
                "code": q.code,
                "label": q.prompt,
                "group": q.group,
                "detail": json.dumps(
                    {"kind": q.kind, "options": [code for code, _ in q.options], "unit": q.unit}
                ),
            }
            for q in questions.QUESTIONS
        ]
    )
    storage.write_table(directory / "clinical" / "clinical_master.parquet", clinical_rows)
    storage.write_table(
        directory / "physiology" / "reference_ranges.parquet",
        [
            {
                "vital": name,
                "normal_low": rules.VITAL_NORMAL_RANGES.get(name, (None, None))[0],
                "normal_high": rules.VITAL_NORMAL_RANGES.get(name, (None, None))[1],
                "implausible_low": quality.IMPLAUSIBLE.get(name, (None, None))[0],
                "implausible_high": quality.IMPLAUSIBLE.get(name, (None, None))[1],
            }
            for name in sorted(set(rules.VITAL_NORMAL_RANGES) | set(quality.IMPLAUSIBLE))
        ],
    )


def _file_inventory(directory: Path) -> list[dict]:
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "path": str(path.relative_to(directory)),
                    "bytes": path.stat().st_size,
                    "sha256": storage.sha256_of(path),
                }
            )
    return files


def write(
    assessments: int,
    seed: int,
    *,
    patients: int | None = None,
    destination: Path | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    storage_format: str = storage.PARQUET,
    hard_case_share: float = DEFAULT_HARD_CASE_SHARE,
) -> tuple[Path, dict]:
    patients = patients or max(1, assessments // 20)
    generator = Generator(seed, patients, assessments, hard_case_share)
    started = datetime.now(timezone.utc)
    version = version_for(seed, patients, assessments, started)
    directory = (destination or get_settings().dataset_path) / version
    directory.mkdir(parents=True, exist_ok=True)

    _write_reference_tables(directory)

    schema = assessment_schema()
    suffix = "parquet" if storage_format == storage.PARQUET else "jsonl"
    master = storage.ChunkedWriter(
        directory / "assessments" / f"assessment_master.{suffix}", schema, storage_format
    )
    split_writers = {
        split: storage.ChunkedWriter(directory / "integrated" / f"{split}.parquet", schema)
        for split in SPLITS
    }
    summary = Summary()
    patient_rows: list[dict] = []
    buffer: list[dict] = []
    by_split: dict[str, list[dict]] = {split: [] for split in SPLITS}

    def flush() -> None:
        master.write(buffer)
        buffer.clear()
        for split, rows in by_split.items():
            split_writers[split].write(rows)
            rows.clear()

    try:
        for patient in generator.patients():
            summary.add_patient(patient)
            patient_rows.append(_patient_row(patient))
            for record in generator.visits(patient):
                row = _row(record)
                buffer.append(row)
                by_split[record.split].append(row)
                summary.add(record)
                if len(buffer) >= chunk_size:
                    flush()
        flush()
    finally:
        master.close()
        for writer in split_writers.values():
            writer.close()

    storage.write_table(
        directory / "patients" / "patient_master.parquet", patient_rows, PATIENT_SCHEMA
    )
    storage.write_table(
        directory / "scenarios" / "scenarios.parquet",
        [
            {
                "code": scenario.code,
                "version": scenario.version,
                "description": scenario.description,
                "count": summary.scenarios.get(scenario.code, 0),
            }
            for scenario in scenario_kb.SCENARIOS
        ]
        + [
            {
                "code": scenario_kb.STANDARD,
                "version": GENERATOR_VERSION,
                "description": "No scenario applied.",
                "count": summary.scenarios.get(scenario_kb.STANDARD, 0),
            }
        ],
    )

    distribution = summary.distribution()
    parameters = {
        "patients": patients,
        "assessments": assessments,
        "seed": seed,
        "chunk_size": chunk_size,
        "storage_format": storage_format,
        "hard_case_share": hard_case_share,
        "validation_share": VALIDATION_SHARE,
        "test_share": TEST_SHARE,
    }
    report = {
        "rows": summary.rows,
        "patients": patients,
        "split_rows": dict(summary.split_rows),
        "split_patients": dict(summary.split_patients),
        "patient_overlap_between_splits": 0,
        "nrs_histogram": distribution["self_report_histogram"],
        "missingness_per_vital": {
            name: round(1 - summary.vitals_recorded.get(name, 0) / summary.rows, 4)
            for name in VITAL_MISSING_PROBABILITY
        },
        "per_scenario_counts": distribution["scenarios"],
        "per_archetype_mean_nrs": distribution["archetype_mean_nrs"],
        "quality_levels": distribution["quality_levels"],
        "leakage_checks": {
            "target_column": TARGET_COLUMN,
            "target_in_feature_columns": TARGET_COLUMN in FEATURE_COLUMNS,
            "feature_names_mentioning_target": [
                name
                for name in features.NAMES
                if "nrs" in name.lower() or "self" in name.lower()
            ],
        },
    }
    storage.write_json(directory / "quality" / "validation_report.json", report)

    manifest = {
        "version": version,
        "generator_version": GENERATOR_VERSION,
        "feature_schema_version": features.FEATURE_SCHEMA_VERSION,
        "generated_at": started.isoformat(),
        "seed": seed,
        "parameters": parameters,
        "scenario_versions": dict(scenario_kb.VERSIONS),
        "counts": {
            "patients": patients,
            "assessments": summary.rows,
            "split_rows": dict(summary.split_rows),
            "split_patients": dict(summary.split_patients),
        },
        "synthetic": True,
        "warning": WARNING,
        "target": TARGET_NOTE,
        "distribution": distribution,
        "files": _file_inventory(directory),
    }
    storage.write_json(directory / "provenance" / "manifest.json", manifest)
    return directory, manifest


@dataclass
class Dataset:
    version: str
    path: Path
    contexts: list[ClinicalContext]
    targets: list[float]
    patient_ids: list[str]
    archetypes: list[str]
    scenarios: list[str]
    splits: list[str]
    profiles: list[str] = field(default_factory=list)
    reference_scales: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.targets)


LOAD_COLUMNS = [
    "patient_id",
    "nrs",
    "archetype",
    "scenario",
    "profile",
    "reference_scale",
    "split",
    "context_json",
]


def _load_legacy(path: Path) -> Dataset:
    contexts, targets, archetypes, patient_ids, splits = [], [], [], [], []
    for index, payload in enumerate(storage.iter_jsonl(path)):
        contexts.append(context_module.from_dict(payload["context"]))
        targets.append(float(payload["nrs"]))
        archetypes.append(payload.get("archetype", "UNKNOWN"))
        patient_ids.append(f"ROW-{index}")
        position = index % 20
        splits.append("train" if position < 14 else "validation" if position < 17 else "test")
    return Dataset(
        version=path.stem,
        path=path,
        contexts=contexts,
        targets=targets,
        patient_ids=patient_ids,
        archetypes=archetypes,
        scenarios=[scenario_kb.STANDARD] * len(targets),
        profiles=[ctx.profile or profiles_kb.ADULT for ctx in contexts],
        reference_scales=[scales.NRS] * len(targets),
        splits=splits,
    )


def load(path: Path) -> Dataset:
    path = Path(path)
    if path.is_file():
        return _load_legacy(path)
    manifest_path = path / "provenance" / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    dataset = Dataset(
        version=manifest.get("version", path.name),
        path=path,
        contexts=[],
        targets=[],
        patient_ids=[],
        archetypes=[],
        scenarios=[],
        splits=[],
        manifest=manifest,
    )
    for split in SPLITS:
        file = path / "integrated" / f"{split}.parquet"
        if not file.exists():
            continue
        for row in storage.iter_rows(file, LOAD_COLUMNS):
            dataset.contexts.append(context_module.from_dict(json.loads(row["context_json"])))
            dataset.targets.append(float(row["nrs"]))
            dataset.patient_ids.append(row["patient_id"])
            dataset.archetypes.append(row["archetype"])
            dataset.scenarios.append(row["scenario"] or scenario_kb.STANDARD)
            dataset.profiles.append(row["profile"] or profiles_kb.ADULT)
            dataset.reference_scales.append(row["reference_scale"] or scales.NRS)
            dataset.splits.append(row["split"] or split)
    return dataset


def register(metadata: dict, path: Path, actor_id=None) -> None:
    from database.session import SessionLocal
    from database.models import DatasetVersion
    from security import audit

    counts = metadata.get("counts", {})
    parameters = metadata.get("parameters", {})
    n_rows = counts.get("assessments", metadata.get("rows", 0))
    with SessionLocal() as db:
        existing = db.query(DatasetVersion).filter_by(version=metadata["version"]).one_or_none()
        if existing is None:
            existing = DatasetVersion(version=metadata["version"])
            db.add(existing)
        generated_at = metadata.get("generated_at")
        if generated_at:
            existing.generated_at = datetime.fromisoformat(generated_at)
        existing.generator_version = metadata.get("generator_version", GENERATOR_VERSION)
        existing.seed = metadata["seed"]
        existing.n_rows = n_rows
        existing.n_patients = counts.get("patients", parameters.get("patients", 0))
        existing.storage_format = parameters.get("storage_format", storage.PARQUET)
        existing.parameters = parameters
        existing.scenario_versions = metadata.get("scenario_versions", {})
        existing.split = counts.get("split_patients", {})
        existing.distribution = metadata.get("distribution", {})
        existing.path = str(path)
        db.commit()
        audit.record(
            db,
            event_type=audit.DATASET_GENERATED,
            actor_id=actor_id,
            resource="dataset",
            resource_id=metadata["version"],
            meta={"rows": n_rows, "patients": existing.n_patients, "seed": metadata["seed"]},
            ledger_payload={
                "version": metadata["version"],
                "rows": n_rows,
                "patients": existing.n_patients,
                "seed": metadata["seed"],
                "generator_version": existing.generator_version,
            },
        )


def main(argv: list[str] | None = None) -> None:
    import time

    parser = argparse.ArgumentParser(description="Generate a synthetic pain dataset.")
    parser.add_argument("--patients", type=int, default=5000)
    parser.add_argument("--assessments", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output", type=Path, default=None, help="parent directory for the dataset"
    )
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--format", choices=storage.FORMATS, default=storage.PARQUET)
    parser.add_argument("--hard-case-share", type=float, default=DEFAULT_HARD_CASE_SHARE)
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="skip writing the dataset version to the database",
    )
    arguments = parser.parse_args(argv)

    started = time.perf_counter()
    path, manifest = write(
        arguments.assessments,
        arguments.seed,
        patients=arguments.patients,
        destination=arguments.output,
        chunk_size=arguments.chunk_size,
        storage_format=arguments.format,
        hard_case_share=arguments.hard_case_share,
    )
    elapsed = time.perf_counter() - started
    if not arguments.no_register:
        register(manifest, path)

    distribution = manifest["distribution"]
    counts = manifest["counts"]
    print(f"SYNTHETIC DATA written to {path}")
    print(
        f"version {manifest['version']}  patients {counts['patients']}  "
        f"assessments {counts['assessments']}  seed {manifest['seed']}  "
        f"in {elapsed:.1f}s"
    )
    print("split rows: " + ", ".join(f"{k} {v}" for k, v in counts["split_rows"].items()))
    print(
        f"self-reported score mean {distribution['self_report_mean']} "
        f"sd {distribution['self_report_sd']}"
    )
    print("scenarios: " + ", ".join(f"{k} {v}" for k, v in distribution["scenarios"].items()))
    print(
        "presentations: " + ", ".join(f"{k} {v}" for k, v in distribution["archetypes"].items())
    )
    print(
        "quality gate: "
        + ", ".join(f"{k} {v}" for k, v in distribution["quality_levels"].items())
    )


if __name__ == "__main__":
    main()
