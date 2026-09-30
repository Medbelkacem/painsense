"""Potentially compatible causes and categories.

Nothing here is a diagnosis. A cause is listed when its gate matches the picture, and it
is scored by how many of its signals the recorded information satisfies. The score is the
matched weight over the total weight, so it says how well the picture fits the pattern and
nothing about how likely the condition is in this patient.

Both the satisfied and the unsatisfied signals are returned, because what is missing is
often the more useful half: a pattern scoring 0.4 because four of its features were never
asked about is not the same as one scoring 0.4 because they were asked and absent.
"""

from dataclasses import dataclass, field

from app.knowledge.context import ClinicalContext, Criteria

GROUPS = (
    ("HEAD", "Head and face pain"),
    ("CHEST", "Chest pain"),
    ("ABDOMEN", "Abdominal and pelvic pain"),
    ("BACK", "Spinal pain"),
    ("LIMB", "Limb and joint pain"),
    ("NEUROPATHIC", "Neuropathic pain"),
    ("SYSTEMIC", "Widespread and context-driven pain"),
)


@dataclass(frozen=True)
class Signal:
    label: str
    weight: int
    criteria: Criteria


@dataclass(frozen=True)
class Cause:
    code: str
    label: str
    group: str
    gate: Criteria
    signals: tuple[Signal, ...]
    pain_types: tuple[str, ...] = ()
    note: str = ""

    @property
    def total_weight(self) -> int:
        return sum(signal.weight for signal in self.signals)


@dataclass
class Match:
    cause: Cause
    score: float
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _s(label: str, weight: int, **criteria) -> Signal:
    return Signal(label, weight, Criteria(**criteria))


_HEAD = Criteria(regions=("HEAD", "NECK"))
_CHEST = Criteria(regions=("CHEST",))
_ABDOMEN = Criteria(regions=("ABDOMEN", "PELVIS"))
_BACK = Criteria(regions=("BACK",))
_LIMB = Criteria(regions=("UPPER_LIMB", "LOWER_LIMB"))
_NEURO = Criteria(qualities=("BURNING", "ELECTRIC", "SHOOTING", "TINGLING", "NUMBNESS"))

CAUSES = (
    Cause(
        "MIGRAINE_PATTERN",
        "Migraine-type headache",
        "HEAD",
        _HEAD,
        (
            _s("Throbbing or pulsating character", 3, qualities=("THROBBING", "PULSATING")),
            _s("Photophobia or phonophobia", 3, answer_equals=(("HEAD_PHOTOPHOBIA", True),)),
            _s("Preceding aura", 2, answer_equals=(("HEAD_AURA", True),)),
            _s("Nausea or vomiting", 2, symptoms=("NAUSEA", "VOMITING")),
            _s("Unilateral temporal site", 1, pain_locations=("TEMPLE",)),
            _s("Known migraine", 2, conditions=("MIGRAINE",)),
        ),
        ("NOCICEPTIVE", "RECURRENT"),
    ),
    Cause(
        "TENSION_TYPE_PATTERN",
        "Tension-type headache",
        "HEAD",
        _HEAD,
        (
            _s("Pressing or tightening character", 3, qualities=("PRESSURE", "TIGHTNESS")),
            _s("Stress as an aggravating factor", 2, factors=("STRESS",)),
            _s("No photophobia", 2, answer_equals=(("HEAD_PHOTOPHOBIA", False),)),
            _s("No nausea or vomiting", 1, without_symptoms=("NAUSEA", "VOMITING")),
            _s("Neck involvement", 1, pain_locations=("NECK", "OCCIPUT")),
        ),
        ("NOCICEPTIVE", "MUSCULOSKELETAL"),
    ),
    Cause(
        "SINUS_PATTERN",
        "Sinus-related facial pain",
        "HEAD",
        _HEAD,
        (
            _s("Frontal or facial site", 3, pain_locations=("FOREHEAD", "FACE")),
            _s("Pressure character", 2, qualities=("PRESSURE",)),
            _s(
                "Worse on bending or straining",
                2,
                answer_equals=(("HEAD_VALSALVA_WORSE", True),),
            ),
            _s("Cough or fever", 2, symptoms=("COUGH", "FEVER")),
        ),
        ("INFLAMMATORY", "NOCICEPTIVE"),
    ),
    Cause(
        "MEDICATION_OVERUSE_PATTERN",
        "Medication-overuse headache",
        "HEAD",
        _HEAD,
        (
            _s(
                "Analgesia on 15 days a month or more",
                4,
                answer_at_least=(("HEAD_ANALGESIC_DAYS_PER_MONTH", 15),),
            ),
            _s("Pain present for three months or more", 3, min_duration_hours=2160),
            _s("Daily or near-daily pattern", 2, pattern=("CONSTANT",)),
        ),
        ("CHRONIC",),
    ),
    Cause(
        "CERVICOGENIC_PATTERN",
        "Cervicogenic headache",
        "HEAD",
        _HEAD,
        (
            _s("Neck or occipital site", 3, pain_locations=("NECK", "OCCIPUT")),
            _s("Provoked by neck movement", 3, factors=("MOVEMENT",)),
            _s(
                "Known cervical spine disorder",
                2,
                conditions=("CHRONIC_BACK_DISORDER", "OSTEOARTHRITIS"),
            ),
        ),
        ("MUSCULOSKELETAL", "NOCICEPTIVE_SOMATIC"),
    ),
    Cause(
        "SUBARACHNOID_PATTERN",
        "Thunderclap headache pattern requiring urgent exclusion of subarachnoid haemorrhage",
        "HEAD",
        _HEAD,
        (
            _s(
                "Maximum intensity within one minute",
                5,
                answer_equals=(("HEAD_THUNDERCLAP", True),),
            ),
            _s(
                "Worst headache ever experienced", 4, answer_equals=(("HEAD_WORST_EVER", True),)
            ),
            _s("Sudden onset", 2, onset=("SUDDEN",)),
            _s("Neck stiffness", 2, answer_equals=(("HEAD_NECK_STIFFNESS", True),)),
            _s(
                "Reduced consciousness or focal deficit",
                3,
                symptoms=("SYNCOPE", "FOCAL_DEFICIT"),
            ),
        ),
        ("ACUTE",),
        note="Listed as a pattern to exclude, not as a diagnosis.",
    ),
    Cause(
        "MENINGEAL_PATTERN",
        "Meningeal irritation pattern",
        "HEAD",
        _HEAD,
        (
            _s("Fever", 4, symptoms=("FEVER",)),
            _s("Neck stiffness", 4, answer_equals=(("HEAD_NECK_STIFFNESS", True),)),
            _s("Photophobia", 2, answer_equals=(("HEAD_PHOTOPHOBIA", True),)),
            _s("Rash", 2, symptoms=("RASH",)),
            _s(
                "Raised inflammatory markers",
                2,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("ACUTE", "INFLAMMATORY"),
    ),
    Cause(
        "CRANIAL_ARTERITIS_PATTERN",
        "Cranial arteritis pattern",
        "HEAD",
        Criteria(regions=("HEAD",), min_age=50),
        (
            _s(
                "Jaw claudication or scalp tenderness",
                4,
                answer_equals=(("HEAD_JAW_CLAUDICATION", True),),
            ),
            _s("Temporal site", 3, pain_locations=("TEMPLE",)),
            _s("Visual disturbance", 3, symptoms=("VISION_CHANGE",)),
            _s(
                "Raised inflammatory markers",
                3,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
            _s("Age 50 or over", 1, min_age=50),
        ),
        ("INFLAMMATORY",),
    ),
    Cause(
        "ISCHAEMIC_CHEST_PATTERN",
        "Ischaemic cardiac pattern",
        "CHEST",
        _CHEST,
        (
            _s("Brought on by exertion", 4, answer_equals=(("CHEST_EXERTIONAL", True),)),
            _s("Settles with rest", 3, answer_equals=(("CHEST_RELIEVED_BY_REST", True),)),
            _s(
                "Radiation to arm, jaw or neck",
                4,
                answer_equals=(("CHEST_RADIATION_SITE", "LEFT_ARM"),),
            ),
            _s(
                "Pressure or tightness character",
                3,
                qualities=("PRESSURE", "TIGHTNESS", "HEAVY"),
            ),
            _s("Central site", 2, pain_locations=("CHEST_CENTRAL", "CHEST_LEFT")),
            _s("Sweating or nausea", 2, symptoms=("SWEATING", "NAUSEA")),
            _s("Known coronary disease", 3, conditions=("CAD",)),
            _s(
                "Diabetes or hypertension",
                1,
                conditions=("DIABETES_T1", "DIABETES_T2", "HYPERTENSION"),
            ),
            _s("Abnormal ECG", 4, answer_equals=(("ECG_RESULT", "ABNORMAL"),)),
            _s("Raised troponin", 5, answer_equals=(("TROPONIN_RESULT", "RAISED"),)),
        ),
        ("NOCICEPTIVE_VISCERAL", "ACUTE"),
    ),
    Cause(
        "CHEST_WALL_PATTERN",
        "Chest-wall or musculoskeletal pattern",
        "CHEST",
        _CHEST,
        (
            _s("Reproduced by palpation", 4, answer_equals=(("CHEST_WALL_TENDER", True),)),
            _s("Worse on movement", 3, factors=("MOVEMENT",)),
            _s("Preceding trauma or strain", 2, recent_trauma=True),
            _s("No breathlessness", 2, without_symptoms=("DYSPNOEA",)),
            _s("Not exertional", 2, answer_equals=(("CHEST_EXERTIONAL", False),)),
        ),
        ("MUSCULOSKELETAL", "NOCICEPTIVE_SOMATIC"),
    ),
    Cause(
        "PLEURAL_PATTERN",
        "Pleural or pulmonary infective pattern",
        "CHEST",
        _CHEST,
        (
            _s("Worse on deep inspiration", 4, answer_equals=(("CHEST_PLEURITIC", True),)),
            _s("Cough", 3, symptoms=("COUGH",)),
            _s("Fever", 3, symptoms=("FEVER",)),
            _s("Breathlessness", 2, symptoms=("DYSPNOEA",)),
            _s(
                "Abnormal chest radiograph",
                3,
                answer_equals=(("CHEST_XRAY_RESULT", "ABNORMAL"),),
            ),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "PULMONARY_EMBOLIC_PATTERN",
        "Pulmonary embolic pattern",
        "CHEST",
        _CHEST,
        (
            _s(
                "Thromboembolic risk factor",
                4,
                answer_equals=(("CHEST_THROMBOEMBOLIC_RISK", True),),
            ),
            _s("Breathlessness", 3, symptoms=("DYSPNOEA",)),
            _s("Pleuritic character", 2, answer_equals=(("CHEST_PLEURITIC", True),)),
            _s("Tachycardia above 100", 3, vitals=(("hr", "gt", 100.0),)),
            _s("Oxygen saturation below 94 per cent", 3, vitals=(("spo2", "lt", 94.0),)),
            _s("Active cancer", 2, conditions=("CANCER_ACTIVE", "CANCER_TREATMENT")),
            _s(
                "Unilateral limb swelling",
                2,
                answer_equals=(("LIMB_UNILATERAL_SWELLING", True),),
            ),
        ),
        ("ACUTE",),
    ),
    Cause(
        "OESOPHAGEAL_PATTERN",
        "Gastro-oesophageal pattern",
        "CHEST",
        _CHEST,
        (
            _s(
                "Burning after meals or lying flat",
                4,
                answer_equals=(("CHEST_REFLUX_PATTERN", True),),
            ),
            _s("Burning character", 2, qualities=("BURNING",)),
            _s("Relieved by food or antacids", 2, factors=("FOOD",)),
            _s("Known reflux or ulcer disease", 3, conditions=("GORD", "PEPTIC_ULCER")),
            _s("Epigastric involvement", 2, pain_locations=("ABD_EPIGASTRIC",)),
        ),
        ("NOCICEPTIVE_VISCERAL",),
    ),
    Cause(
        "PERICARDIAL_PATTERN",
        "Pericardial pattern",
        "CHEST",
        _CHEST,
        (
            _s("Changes with posture", 4, answer_equals=(("CHEST_POSITIONAL", True),)),
            _s("Pleuritic character", 3, answer_equals=(("CHEST_PLEURITIC", True),)),
            _s("Sharp character", 2, qualities=("SHARP", "STABBING")),
            _s("Recent febrile or viral illness", 2, symptoms=("FEVER",)),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "ANXIETY_RELATED_CHEST_PATTERN",
        "Anxiety or stress-related chest pain",
        "CHEST",
        _CHEST,
        (
            _s("Anxiety or distress recorded", 4, confounders=("ANXIETY", "FEAR")),
            _s("Known anxiety disorder", 3, conditions=("ANXIETY_DISORDER",)),
            _s("Stress as an aggravating factor", 3, factors=("STRESS",)),
            _s(
                "Tightness without exertional relation",
                2,
                answer_equals=(("CHEST_EXERTIONAL", False),),
            ),
            _s("Normal oxygen saturation", 1, vitals=(("spo2", "gte", 95.0),)),
            _s("Palpitations", 2, symptoms=("PALPITATIONS",)),
        ),
        ("NOCIPLASTIC",),
    ),
    Cause(
        "BILIARY_PATTERN",
        "Biliary pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s(
                "Right upper quadrant or epigastric site",
                4,
                pain_locations=("ABD_RUQ", "ABD_EPIGASTRIC"),
            ),
            _s("Worse after eating", 3, answer_equals=(("ABD_FOOD_RELATION", "WORSE_AFTER"),)),
            _s("Cramping or colicky character", 3, qualities=("CRAMPING",)),
            _s("Nausea or vomiting", 2, symptoms=("NAUSEA", "VOMITING")),
            _s("Radiation to the back or shoulder", 2, radiates=True),
            _s("Abnormal ultrasound", 3, answer_equals=(("ULTRASOUND_RESULT", "ABNORMAL"),)),
        ),
        ("NOCICEPTIVE_VISCERAL",),
    ),
    Cause(
        "APPENDICULAR_PATTERN",
        "Appendicular pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s("Right lower quadrant site", 4, pain_locations=("ABD_RLQ",)),
            _s("Pain migrated since onset", 3, answer_equals=(("ABD_PAIN_MIGRATED", True),)),
            _s("Guarding or rebound tenderness", 4, answer_equals=(("ABD_GUARDING", True),)),
            _s("Fever", 2, symptoms=("FEVER",)),
            _s("Nausea or vomiting", 2, symptoms=("NAUSEA", "VOMITING")),
            _s(
                "Raised inflammatory markers",
                2,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "OBSTRUCTION_PATTERN",
        "Intestinal obstruction pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s("Abdominal distension", 4, symptoms=("ABDOMINAL_DISTENSION",)),
            _s(
                "Bilious or faeculent vomiting", 4, answer_equals=(("ABD_VOMIT_BILIOUS", True),)
            ),
            _s("No flatus passed", 3, answer_equals=(("ABD_FLATUS_PASSING", False),)),
            _s(
                "No bowel motion for three days or more",
                2,
                answer_equals=(("ABD_LAST_BOWEL_MOTION", "THREE_PLUS_DAYS"),),
            ),
            _s(
                "Previous abdominal surgery", 3, answer_equals=(("ABD_PREVIOUS_SURGERY", True),)
            ),
            _s("Cramping character", 2, qualities=("CRAMPING",)),
        ),
        ("NOCICEPTIVE_VISCERAL", "ACUTE"),
    ),
    Cause(
        "PEPTIC_PATTERN",
        "Peptic pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s("Epigastric site", 4, pain_locations=("ABD_EPIGASTRIC",)),
            _s("Burning character", 3, qualities=("BURNING",)),
            _s(
                "Worse when fasting or better after eating",
                3,
                answer_equals=(("ABD_FOOD_RELATION", "WORSE_FASTING"),),
            ),
            _s("Known ulcer or reflux disease", 3, conditions=("PEPTIC_ULCER", "GORD")),
        ),
        ("NOCICEPTIVE_VISCERAL",),
    ),
    Cause(
        "PANCREATIC_PATTERN",
        "Pancreatic pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s("Epigastric site", 3, pain_locations=("ABD_EPIGASTRIC",)),
            _s("Radiates through to the back", 4, radiates=True),
            _s("Recent heavy alcohol intake", 3, answer_equals=(("ABD_ALCOHOL_BINGE", True),)),
            _s("Persistent vomiting", 3, symptoms=("VOMITING",)),
            _s("Abnormal CT", 3, answer_equals=(("CT_RESULT", "ABNORMAL"),)),
        ),
        ("NOCICEPTIVE_VISCERAL", "ACUTE", "INFLAMMATORY"),
    ),
    Cause(
        "RENAL_COLIC_PATTERN",
        "Renal colic pattern",
        "ABDOMEN",
        Criteria(regions=("ABDOMEN", "PELVIS", "BACK")),
        (
            _s("Flank or lumbar site", 3, pain_locations=("ABD_LUQ", "ABD_RUQ", "BACK_LUMBAR")),
            _s("Colicky character", 3, qualities=("CRAMPING", "SHARP")),
            _s("Radiation to the groin", 3, radiates=True),
            _s("Blood on urine dipstick", 4, answer_equals=(("URINE_DIPSTICK", "BLOOD"),)),
            _s("Known stone disease", 2, conditions=("NEPHROLITHIASIS",)),
            _s("Nausea or vomiting", 1, symptoms=("NAUSEA", "VOMITING")),
        ),
        ("NOCICEPTIVE_VISCERAL", "ACUTE"),
    ),
    Cause(
        "URINARY_INFECTION_PATTERN",
        "Urinary tract infective pattern",
        "ABDOMEN",
        Criteria(regions=("ABDOMEN", "PELVIS", "BACK")),
        (
            _s(
                "Suprapubic or lumbar site", 3, pain_locations=("ABD_SUPRAPUBIC", "BACK_LUMBAR")
            ),
            _s("Urinary symptoms", 4, symptoms=("URINARY_SYMPTOMS",)),
            _s(
                "Leucocytes or nitrites on dipstick",
                4,
                answer_equals=(("URINE_DIPSTICK", "LEUCOCYTES_NITRITES"),),
            ),
            _s("Fever", 3, symptoms=("FEVER",)),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "GYNAECOLOGICAL_PATTERN",
        "Gynaecological pattern",
        "ABDOMEN",
        Criteria(regions=("ABDOMEN", "PELVIS"), sex="F", min_age=12, max_age=60),
        (
            _s(
                "Lower abdominal or pelvic site",
                3,
                pain_locations=("ABD_RLQ", "ABD_LLQ", "ABD_SUPRAPUBIC", "PELVIS"),
            ),
            _s("Cramping character", 2, qualities=("CRAMPING",)),
            _s("Recurrent or cyclical pattern", 2, pattern=("EPISODIC", "INTERMITTENT")),
            _s("Abnormal ultrasound", 3, answer_equals=(("ULTRASOUND_RESULT", "ABNORMAL"),)),
            _s("Vaginal bleeding", 2, symptoms=("BLEEDING",)),
        ),
        ("NOCICEPTIVE_VISCERAL",),
    ),
    Cause(
        "EARLY_PREGNANCY_PATTERN",
        "Early-pregnancy complication pattern",
        "ABDOMEN",
        Criteria(regions=("ABDOMEN", "PELVIS"), sex="F"),
        (
            _s(
                "Pregnancy confirmed or possible",
                5,
                answer_equals=(("ABD_PREGNANCY_STATUS", "CONFIRMED"),),
            ),
            _s(
                "Lower abdominal site",
                3,
                pain_locations=("ABD_RLQ", "ABD_LLQ", "ABD_SUPRAPUBIC", "PELVIS"),
            ),
            _s("Bleeding", 4, symptoms=("BLEEDING",)),
            _s("Dizziness or syncope", 3, symptoms=("DIZZINESS", "SYNCOPE")),
        ),
        ("ACUTE",),
        note="Listed so that the possibility is documented, not as a diagnosis.",
    ),
    Cause(
        "DIVERTICULAR_PATTERN",
        "Diverticular pattern",
        "ABDOMEN",
        Criteria(regions=("ABDOMEN",), min_age=45),
        (
            _s("Left lower quadrant site", 4, pain_locations=("ABD_LLQ",)),
            _s("Fever", 3, symptoms=("FEVER",)),
            _s("Change in bowel habit", 2, symptoms=("CONSTIPATION", "DIARRHOEA")),
            _s(
                "Raised inflammatory markers",
                3,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("INFLAMMATORY",),
    ),
    Cause(
        "FUNCTIONAL_BOWEL_PATTERN",
        "Functional bowel pattern",
        "ABDOMEN",
        _ABDOMEN,
        (
            _s("Present for three months or more", 3, min_duration_hours=2160),
            _s("Known irritable bowel syndrome", 3, conditions=("IBS",)),
            _s("Altered bowel habit", 2, symptoms=("DIARRHOEA", "CONSTIPATION")),
            _s(
                "No fever, bleeding or weight loss",
                3,
                without_symptoms=("FEVER", "BLEEDING", "WEIGHT_LOSS"),
            ),
        ),
        ("NOCIPLASTIC", "CHRONIC"),
    ),
    Cause(
        "MECHANICAL_BACK_PATTERN",
        "Mechanical spinal pain",
        "BACK",
        _BACK,
        (
            _s("Worse on movement", 3, factors=("MOVEMENT", "WALKING")),
            _s("Eased by rest", 3, factors=("REST",)),
            _s(
                "No radiation below the knee",
                3,
                answer_equals=(("BACK_RADIATION_BELOW_KNEE", False),),
            ),
            _s("No systemic symptoms", 2, without_symptoms=("FEVER", "WEIGHT_LOSS")),
            _s("Preceding strain or trauma", 2, recent_trauma=True),
        ),
        ("MUSCULOSKELETAL", "NOCICEPTIVE_SOMATIC"),
    ),
    Cause(
        "RADICULAR_PATTERN",
        "Radicular pattern",
        "BACK",
        _BACK,
        (
            _s(
                "Radiates below the knee",
                4,
                answer_equals=(("BACK_RADIATION_BELOW_KNEE", True),),
            ),
            _s(
                "Positive straight leg raise",
                3,
                answer_equals=(("BACK_STRAIGHT_LEG_RAISE", "POSITIVE"),),
            ),
            _s(
                "Dermatomal distribution",
                3,
                answer_equals=(("NEURO_DISTRIBUTION", "DERMATOMAL"),),
            ),
            _s("Shooting or electric character", 3, qualities=("SHOOTING", "ELECTRIC")),
            _s("Numbness or tingling", 2, symptoms=("NUMBNESS", "TINGLING")),
            _s("Motor weakness", 3, symptoms=("MOTOR_WEAKNESS",)),
        ),
        ("NEUROPATHIC_RADICULAR",),
    ),
    Cause(
        "INFLAMMATORY_SPINAL_PATTERN",
        "Inflammatory spinal pattern",
        "BACK",
        _BACK,
        (
            _s(
                "Morning stiffness of 30 minutes or more",
                4,
                answer_at_least=(("BACK_MORNING_STIFFNESS", 30),),
            ),
            _s("Eased by movement", 3, factors=("MOVEMENT_REL",)),
            _s("Onset before 45", 3, max_age=45),
            _s("Night pain", 2, factors=("NIGHT",)),
            _s("Present for three months or more", 2, min_duration_hours=2160),
        ),
        ("INFLAMMATORY", "CHRONIC"),
    ),
    Cause(
        "VERTEBRAL_FRAGILITY_PATTERN",
        "Vertebral fragility pattern",
        "BACK",
        _BACK,
        (
            _s("Age 65 or over", 3, min_age=65),
            _s("Known osteoporosis", 4, conditions=("OSTEOPOROSIS",)),
            _s(
                "Long-term corticosteroids",
                3,
                answer_equals=(("BACK_STEROID_OR_IMMUNOSUPPRESSION", True),),
            ),
            _s("Sudden onset", 2, onset=("SUDDEN",)),
            _s("Thoracic or lumbar site", 2, pain_locations=("BACK_THORACIC", "BACK_LUMBAR")),
        ),
        ("NOCICEPTIVE_SOMATIC", "TRAUMATIC"),
    ),
    Cause(
        "SPINAL_INFECTION_PATTERN",
        "Spinal infective pattern",
        "BACK",
        _BACK,
        (
            _s("Fever", 4, symptoms=("FEVER",)),
            _s(
                "Injection drug use or recent bacteraemia",
                4,
                answer_equals=(("BACK_INJECTION_DRUG_USE", True),),
            ),
            _s(
                "Immunosuppression",
                3,
                answer_equals=(("BACK_STEROID_OR_IMMUNOSUPPRESSION", True),),
            ),
            _s("Night pain", 2, factors=("NIGHT",)),
            _s(
                "Raised inflammatory markers",
                3,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "CAUDA_EQUINA_PATTERN",
        "Cauda equina pattern requiring urgent assessment",
        "BACK",
        _BACK,
        (
            _s("Urinary retention or incontinence", 5, symptoms=("URINARY_RETENTION",)),
            _s("Saddle anaesthesia", 5, symptoms=("SADDLE_ANAESTHESIA",)),
            _s("Bilateral leg symptoms", 3, answer_equals=(("NEURO_DISTRIBUTION", "PATCHY"),)),
            _s("Motor weakness", 4, symptoms=("MOTOR_WEAKNESS",)),
        ),
        ("NEUROPATHIC_RADICULAR", "ACUTE"),
        note="Listed as a pattern to exclude urgently, not as a diagnosis.",
    ),
    Cause(
        "SPINAL_MALIGNANCY_PATTERN",
        "Spinal malignancy pattern",
        "BACK",
        _BACK,
        (
            _s(
                "Known or previous cancer",
                5,
                conditions=("CANCER_ACTIVE", "CANCER_HISTORY", "CANCER_TREATMENT"),
            ),
            _s("Age 50 or over", 2, min_age=50),
            _s("Unintentional weight loss", 3, symptoms=("WEIGHT_LOSS",)),
            _s("Night pain", 3, factors=("NIGHT",)),
            _s("Progressive course", 2, course=("PROGRESSIVE", "WORSENING")),
        ),
        ("CANCER_RELATED",),
    ),
    Cause(
        "OSTEOARTHRITIC_PATTERN",
        "Degenerative joint pattern",
        "LIMB",
        _LIMB,
        (
            _s("Age 50 or over", 2, min_age=50),
            _s("Known osteoarthritis", 4, conditions=("OSTEOARTHRITIS",)),
            _s("Worse on use, eased by rest", 3, factors=("MOVEMENT", "WALKING")),
            _s("Weight-bearing joint", 2, pain_locations=("KNEE", "HIP")),
            _s(
                "Morning stiffness under 30 minutes",
                2,
                answer_at_most=(("BACK_MORNING_STIFFNESS", 29),),
            ),
        ),
        ("MUSCULOSKELETAL", "CHRONIC"),
    ),
    Cause(
        "INFLAMMATORY_ARTHRITIS_PATTERN",
        "Inflammatory arthritis pattern",
        "LIMB",
        _LIMB,
        (
            _s(
                "Hot, swollen, restricted joint",
                4,
                answer_equals=(("LIMB_JOINT_HOT_SWOLLEN", True),),
            ),
            _s("Known inflammatory arthritis", 4, conditions=("RHEUMATOID_ARTHRITIS",)),
            _s(
                "Morning stiffness of 30 minutes or more",
                3,
                answer_at_least=(("BACK_MORNING_STIFFNESS", 30),),
            ),
            _s("Joint stiffness", 2, symptoms=("JOINT_STIFFNESS",)),
        ),
        ("INFLAMMATORY", "CHRONIC"),
    ),
    Cause(
        "SEPTIC_JOINT_PATTERN",
        "Septic joint pattern requiring urgent assessment",
        "LIMB",
        _LIMB,
        (
            _s(
                "Hot, swollen, restricted joint",
                5,
                answer_equals=(("LIMB_JOINT_HOT_SWOLLEN", True),),
            ),
            _s("Fever", 4, symptoms=("FEVER",)),
            _s(
                "Raised inflammatory markers",
                3,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
            _s("Rapid onset", 2, onset=("SUDDEN",)),
        ),
        ("INFLAMMATORY", "ACUTE"),
        note="Listed as a pattern to exclude urgently, not as a diagnosis.",
    ),
    Cause(
        "DEEP_VEIN_PATTERN",
        "Deep vein thrombotic pattern",
        "LIMB",
        Criteria(regions=("LOWER_LIMB",)),
        (
            _s(
                "Unilateral limb swelling",
                5,
                answer_equals=(("LIMB_UNILATERAL_SWELLING", True),),
            ),
            _s("Calf or leg site", 2, pain_locations=("LEG", "THIGH")),
            _s(
                "Thromboembolic risk factor",
                4,
                answer_equals=(("CHEST_THROMBOEMBOLIC_RISK", True),),
            ),
            _s("Active cancer", 3, conditions=("CANCER_ACTIVE", "CANCER_TREATMENT")),
            _s("Abnormal ultrasound", 4, answer_equals=(("ULTRASOUND_RESULT", "ABNORMAL"),)),
        ),
        ("ACUTE",),
    ),
    Cause(
        "PERIPHERAL_ARTERIAL_PATTERN",
        "Peripheral arterial pattern",
        "LIMB",
        Criteria(regions=("LOWER_LIMB",)),
        (
            _s("Pain on walking a predictable distance", 4, factors=("WALKING",)),
            _s(
                "Reduced or absent distal pulse",
                5,
                answer_equals=(("LIMB_DISTAL_PULSE", "REDUCED"),),
            ),
            _s("Known peripheral vascular disease", 4, conditions=("PVD",)),
            _s("Diabetes", 2, conditions=("DIABETES_T1", "DIABETES_T2")),
            _s("Pale or cyanotic limb", 3, answer_equals=(("LIMB_COLOUR", "PALE"),)),
        ),
        ("NOCICEPTIVE_SOMATIC",),
    ),
    Cause(
        "SOFT_TISSUE_INFECTION_PATTERN",
        "Soft-tissue infective pattern",
        "LIMB",
        _LIMB,
        (
            _s("Red and warm limb", 4, answer_equals=(("LIMB_COLOUR", "ERYTHEMATOUS"),)),
            _s("Swelling", 3, symptoms=("SWELLING",)),
            _s("Fever", 3, symptoms=("FEVER",)),
            _s(
                "Raised inflammatory markers",
                2,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("INFLAMMATORY", "ACUTE"),
    ),
    Cause(
        "TENDINOPATHY_PATTERN",
        "Tendon or soft-tissue overuse pattern",
        "LIMB",
        _LIMB,
        (
            _s("Worse on specific movement", 4, factors=("MOVEMENT",)),
            _s("Tender to local pressure", 3, factors=("PRESSURE_AGG", "TOUCH")),
            _s("Periarticular site", 2, pain_locations=("SHOULDER", "ELBOW", "WRIST", "ANKLE")),
            _s("No systemic symptoms", 2, without_symptoms=("FEVER", "WEIGHT_LOSS")),
            _s("Gradual onset", 2, onset=("GRADUAL",)),
        ),
        ("MUSCULOSKELETAL",),
    ),
    Cause(
        "POLYNEUROPATHY_PATTERN",
        "Polyneuropathy pattern",
        "NEUROPATHIC",
        _NEURO,
        (
            _s(
                "Symmetrical distal distribution",
                5,
                answer_equals=(("NEURO_DISTRIBUTION", "STOCKING_GLOVE"),),
            ),
            _s("Diabetes", 4, conditions=("DIABETES_T1", "DIABETES_T2")),
            _s("Known neuropathy", 4, conditions=("NEUROPATHY",)),
            _s("Burning character", 3, qualities=("BURNING", "TINGLING")),
            _s("Feet or hands", 2, pain_locations=("FOOT", "TOE", "HAND", "FINGER")),
            _s("Worse at night", 2, factors=("NIGHT",)),
        ),
        ("NEUROPATHIC_POLYNEUROPATHY", "CHRONIC"),
    ),
    Cause(
        "POST_HERPETIC_PATTERN",
        "Post-herpetic neuralgia pattern",
        "NEUROPATHIC",
        _NEURO,
        (
            _s(
                "Vesicular rash in the same territory",
                5,
                answer_equals=(("NEURO_VESICULAR_RASH", True),),
            ),
            _s("Single dermatome", 4, answer_equals=(("NEURO_DISTRIBUTION", "DERMATOMAL"),)),
            _s("Pain on light touch", 3, answer_equals=(("NEURO_ALLODYNIA", True),)),
            _s("Burning character", 2, qualities=("BURNING",)),
        ),
        ("NEUROPATHIC_NEURALGIA",),
    ),
    Cause(
        "ENTRAPMENT_PATTERN",
        "Nerve entrapment pattern",
        "NEUROPATHIC",
        _NEURO,
        (
            _s(
                "Territory of a single nerve",
                5,
                answer_equals=(("NEURO_DISTRIBUTION", "SINGLE_NERVE"),),
            ),
            _s("Hand or wrist site", 3, pain_locations=("HAND", "WRIST", "FINGER")),
            _s("Worse at night", 3, factors=("NIGHT",)),
            _s("Tingling or numbness", 2, symptoms=("TINGLING", "NUMBNESS")),
        ),
        ("NEUROPATHIC_PERIPHERAL",),
    ),
    Cause(
        "TRIGEMINAL_PATTERN",
        "Trigeminal neuralgia pattern",
        "NEUROPATHIC",
        Criteria(regions=("HEAD",)),
        (
            _s("Facial or jaw site", 4, pain_locations=("FACE", "JAW", "TEETH")),
            _s("Electric-shock-like character", 5, qualities=("ELECTRIC", "SHOOTING")),
            _s("Brief episodic attacks", 3, pattern=("EPISODIC",)),
            _s("Triggered by light touch", 3, factors=("TOUCH",)),
        ),
        ("NEUROPATHIC_NEURALGIA",),
    ),
    Cause(
        "WIDESPREAD_PAIN_PATTERN",
        "Widespread persistent pain pattern",
        "SYSTEMIC",
        Criteria(min_duration_hours=2160),
        (
            _s(
                "Widespread rather than localised",
                4,
                answer_equals=(("CHRONIC_WIDESPREAD", True),),
            ),
            _s("Known fibromyalgia", 4, conditions=("FIBROMYALGIA",)),
            _s("Disturbed sleep", 3, answer_equals=(("SLEEP_DISTURBED", True),)),
            _s("Impact on mood", 2, answer_equals=(("CHRONIC_MOOD_IMPACT", "MODERATE"),)),
            _s("Generalised site recorded", 3, pain_locations=("GENERALIZED",)),
        ),
        ("NOCIPLASTIC", "CHRONIC"),
        note="Recorded as a category. The platform does not assert a nociplastic mechanism.",
    ),
    Cause(
        "CANCER_PAIN_PATTERN",
        "Cancer-related pain pattern",
        "SYSTEMIC",
        Criteria(conditions=("CANCER_ACTIVE", "CANCER_HISTORY", "CANCER_TREATMENT")),
        (
            _s("Active cancer", 4, conditions=("CANCER_ACTIVE", "CANCER_TREATMENT")),
            _s("Known metastases", 4, answer_equals=(("CANCER_KNOWN_METASTASES", True),)),
            _s("New site compared with before", 3, answer_equals=(("CANCER_NEW_SITE", True),)),
            _s("Night pain", 2, factors=("NIGHT",)),
            _s("Progressive course", 2, course=("PROGRESSIVE", "WORSENING")),
        ),
        ("CANCER_RELATED",),
    ),
    Cause(
        "POSTOPERATIVE_PATTERN",
        "Expected postoperative pain",
        "SYSTEMIC",
        Criteria(answer_equals=(("SURGERY_LAST_30_DAYS", True),)),
        (
            _s(
                "Pain at the operative site", 4, answer_equals=(("POSTOP_PAIN_AT_WOUND", True),)
            ),
            _s("Within the first postoperative week", 3, answer_at_most=(("POSTOP_DAYS", 7),)),
            _s("Clean wound", 2, answer_equals=(("POSTOP_WOUND_APPEARANCE", "CLEAN"),)),
            _s("Mobilising as expected", 2, answer_equals=(("POSTOP_MOBILISING", True),)),
        ),
        ("POSTOPERATIVE", "ACUTE", "NOCICEPTIVE_SOMATIC"),
    ),
    Cause(
        "SURGICAL_SITE_INFECTION_PATTERN",
        "Surgical site infective pattern",
        "SYSTEMIC",
        Criteria(answer_equals=(("SURGERY_LAST_30_DAYS", True),)),
        (
            _s(
                "Wound erythema or discharge",
                5,
                answer_equals=(("POSTOP_WOUND_APPEARANCE", "DISCHARGE"),),
            ),
            _s("Fever", 4, symptoms=("FEVER",)),
            _s("Pain worsening rather than settling", 3, course=("WORSENING", "PROGRESSIVE")),
            _s(
                "Raised inflammatory markers",
                3,
                answer_equals=(("INFLAMMATORY_MARKERS", "RAISED"),),
            ),
        ),
        ("INFLAMMATORY", "POSTOPERATIVE"),
    ),
)

BY_CODE = {cause.code: cause for cause in CAUSES}


def candidates(ctx: ClinicalContext, limit: int = 6, floor: float = 0.2) -> list[Match]:
    """Causes whose gate matches, scored and sorted by how well the picture fits."""
    matches = []
    for cause in CAUSES:
        if not cause.gate.matches(ctx):
            continue
        match = Match(cause=cause, score=0.0)
        earned = 0
        for signal in cause.signals:
            if signal.criteria.matches(ctx):
                earned += signal.weight
                match.matched.append(signal.label)
            else:
                match.missing.append(signal.label)
        match.score = round(earned / cause.total_weight, 3)
        if match.score >= floor:
            matches.append(match)
    matches.sort(key=lambda match: match.score, reverse=True)
    return matches[:limit]
