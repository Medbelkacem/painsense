from dataclasses import dataclass

from knowledge import confounders as confounder_kb
from knowledge import profiles, reference_ranges
from knowledge.context import ClinicalContext, Criteria

HIGH = "HIGH"
MODERATE = "MODERATE"

PAIN_BANDS = (
    (0.5, "NONE", "No pain"),
    (3.5, "MILD", "Mild"),
    (6.5, "MODERATE", "Moderate"),
    (9.5, "SEVERE", "Severe"),
    (10.01, "EXTREME", "Extreme"),
)


def band(estimate: float) -> tuple[str, str]:
    for upper, code, label in PAIN_BANDS:
        if estimate < upper:
            return code, label
    return PAIN_BANDS[-1][1], PAIN_BANDS[-1][2]


@dataclass(frozen=True)
class RedFlag:
    code: str
    label: str
    severity: str
    points: float
    criteria: Criteria
    advice: str

    vitals_used: tuple[str, ...] = ()


RED_FLAGS = (
    RedFlag(
        "SPO2_LOW",
        "Oxygen saturation below 92 per cent",
        HIGH,
        2.5,
        Criteria(vitals=(("spo2", "lt", 92.0),)),
        "Assess airway, breathing and oxygenation before continuing the assessment.",
        ("spo2",),
    ),
    RedFlag(
        "SPO2_BORDERLINE",
        "Oxygen saturation between 92 and 94 per cent",
        MODERATE,
        1.0,
        Criteria(vitals=(("spo2", "gte", 92.0), ("spo2", "lt", 95.0))),
        "Recheck saturation and compare with the patient's usual value.",
        ("spo2",),
    ),
    RedFlag(
        "HYPOTENSION",
        "Systolic blood pressure below 90 mmHg",
        HIGH,
        2.5,
        Criteria(vitals=(("sbp", "lt", 90.0),)),
        "Assess perfusion and consider an urgent review.",
        ("sbp",),
    ),
    RedFlag(
        "SEVERE_TACHYCARDIA",
        "Heart rate above 130 per minute",
        HIGH,
        2.0,
        Criteria(vitals=(("hr", "gt", 130.0),)),
        "Look for a cause other than pain before attributing the rate to pain.",
        ("hr",),
    ),
    RedFlag(
        "MODERATE_TACHYCARDIA",
        "Heart rate between 110 and 130 per minute",
        MODERATE,
        0.8,
        Criteria(vitals=(("hr", "gte", 110.0), ("hr", "lte", 130.0))),
        "Interpret alongside the recorded context, not as evidence of pain on its own.",
        ("hr",),
    ),
    RedFlag(
        "SEVERE_BRADYCARDIA",
        "Heart rate below 45 per minute",
        HIGH,
        2.0,
        Criteria(vitals=(("hr", "lt", 45.0),)),
        "Check medication and conduction before continuing.",
        ("hr",),
    ),
    RedFlag(
        "TACHYPNOEA",
        "Respiratory rate above 30 per minute",
        HIGH,
        2.0,
        Criteria(vitals=(("resp_rate", "gt", 30.0),)),
        "Assess respiratory effort and oxygenation.",
        ("resp_rate",),
    ),
    RedFlag(
        "HIGH_FEVER",
        "Temperature of 39.5 degrees or above",
        MODERATE,
        1.2,
        Criteria(vitals=(("temperature_c", "gte", 39.5),)),
        "Look for a source of infection.",
        ("temperature_c",),
    ),
    RedFlag(
        "HYPOTHERMIA",
        "Temperature below 35 degrees",
        HIGH,
        2.0,
        Criteria(vitals=(("temperature_c", "lt", 35.0),)),
        "Recheck with a core measurement and assess for sepsis.",
        ("temperature_c",),
    ),
    RedFlag(
        "HYPOGLYCAEMIA",
        "Blood glucose below 3.5 mmol/L",
        HIGH,
        2.0,
        Criteria(vitals=(("glucose_mmol", "lt", 3.5),)),
        "Treat the hypoglycaemia before interpreting anything else.",
        ("glucose_mmol",),
    ),
    RedFlag(
        "SEVERE_HYPERGLYCAEMIA",
        "Blood glucose above 25 mmol/L",
        HIGH,
        1.8,
        Criteria(vitals=(("glucose_mmol", "gt", 25.0),)),
        "Check ketones and hydration.",
        ("glucose_mmol",),
    ),
    RedFlag(
        "SYNCOPE",
        "Loss of consciousness reported",
        HIGH,
        2.5,
        Criteria(symptoms=("SYNCOPE",)),
        "Needs prompt clinical evaluation regardless of the pain estimate.",
    ),
    RedFlag(
        "FOCAL_NEUROLOGICAL_DEFICIT",
        "Sudden focal neurological deficit",
        HIGH,
        3.0,
        Criteria(symptoms=("FOCAL_DEFICIT",)),
        "Time-critical. Escalate before completing the assessment.",
    ),
    RedFlag(
        "CAUDA_EQUINA_FEATURES",
        "Spinal pain with urinary retention or saddle anaesthesia",
        HIGH,
        3.0,
        Criteria(regions=("BACK",), symptoms=("URINARY_RETENTION", "SADDLE_ANAESTHESIA")),
        "Requires urgent assessment for cauda equina compression.",
    ),
    RedFlag(
        "BLEEDING_WITH_INSTABILITY",
        "Bleeding with tachycardia or hypotension",
        HIGH,
        3.0,
        Criteria(symptoms=("BLEEDING",), vitals=(("hr", "gt", 110.0),)),
        "Treat as potentially uncontrolled blood loss.",
        ("hr",),
    ),
    RedFlag(
        "ISCHAEMIC_CHEST_FEATURES",
        "Chest pain with features that warrant cardiac assessment",
        HIGH,
        2.5,
        Criteria(
            regions=("CHEST",),
            symptoms=("SWEATING", "NAUSEA", "DYSPNOEA", "CHEST_PRESSURE"),
            answer_equals=(("CHEST_EXERTIONAL", True),),
        ),
        "Consider an ECG and cardiac assessment now.",
    ),
    RedFlag(
        "TROPONIN_RAISED",
        "Troponin recorded as raised",
        HIGH,
        3.0,
        Criteria(answer_equals=(("TROPONIN_RESULT", "RAISED"),)),
        "Follow the local acute coronary syndrome pathway.",
    ),
    RedFlag(
        "THUNDERCLAP_HEADACHE",
        "Headache reaching maximum intensity within one minute",
        HIGH,
        3.0,
        Criteria(answer_equals=(("HEAD_THUNDERCLAP", True),)),
        "Needs urgent imaging before other explanations are pursued.",
    ),
    RedFlag(
        "MENINGEAL_FEATURES",
        "Fever with neck stiffness",
        HIGH,
        3.0,
        Criteria(symptoms=("FEVER",), answer_equals=(("HEAD_NECK_STIFFNESS", True),)),
        "Assess urgently for meningeal infection.",
    ),
    RedFlag(
        "PERITONEAL_FEATURES",
        "Abdominal pain with guarding and fever",
        HIGH,
        2.5,
        Criteria(
            regions=("ABDOMEN",),
            symptoms=("FEVER",),
            answer_equals=(("ABD_GUARDING", True),),
        ),
        "Surgical assessment should not wait for the pain estimate.",
    ),
    RedFlag(
        "ABSENT_DISTAL_PULSE",
        "Absent distal pulse in a painful limb",
        HIGH,
        3.0,
        Criteria(
            regions=("UPPER_LIMB", "LOWER_LIMB"),
            answer_equals=(("LIMB_DISTAL_PULSE", "ABSENT"),),
        ),
        "Treat as possible acute limb ischaemia.",
    ),
    RedFlag(
        "HOT_SWOLLEN_JOINT_WITH_FEVER",
        "Hot swollen joint with fever",
        HIGH,
        2.5,
        Criteria(symptoms=("FEVER",), answer_equals=(("LIMB_JOINT_HOT_SWOLLEN", True),)),
        "Assess urgently for joint infection.",
    ),
    RedFlag(
        "FEVER_WITH_SPINAL_PAIN",
        "Spinal pain with fever",
        MODERATE,
        1.5,
        Criteria(regions=("BACK",), symptoms=("FEVER",)),
        "Consider spinal infection, particularly with immunosuppression.",
    ),
    RedFlag(
        "PROGRESSIVE_MOTOR_WEAKNESS",
        "Objective motor weakness",
        MODERATE,
        1.5,
        Criteria(symptoms=("MOTOR_WEAKNESS",)),
        "Document the deficit and reassess for progression.",
    ),
    RedFlag(
        "CANCER_WITH_NEW_PAIN",
        "Known cancer with pain at a new site",
        MODERATE,
        1.5,
        Criteria(
            conditions=("CANCER_ACTIVE", "CANCER_HISTORY", "CANCER_TREATMENT"),
            answer_equals=(("CANCER_NEW_SITE", True),),
        ),
        "Consider imaging of the new site.",
    ),
    RedFlag(
        "UNEXPLAINED_WEIGHT_LOSS",
        "Unintentional weight loss over the age of 50",
        MODERATE,
        1.2,
        Criteria(symptoms=("WEIGHT_LOSS",), min_age=50),
        "Warrants investigation independent of the pain assessment.",
    ),
    RedFlag(
        "VISUAL_SYMPTOMS_OLDER_ADULT",
        "Visual disturbance with head pain over the age of 50",
        HIGH,
        2.0,
        Criteria(regions=("HEAD",), symptoms=("VISION_CHANGE",), min_age=50),
        "Sight-threatening causes need same-day assessment.",
    ),
    RedFlag(
        "PREGNANCY_WITH_ABDOMINAL_PAIN",
        "Abdominal or pelvic pain with a possible or confirmed pregnancy",
        HIGH,
        2.0,
        Criteria(
            regions=("ABDOMEN", "PELVIS"),
            answer_equals=(("ABD_PREGNANCY_STATUS", "CONFIRMED"),),
        ),
        "Needs obstetric assessment.",
    ),
    RedFlag(
        "WOUND_COMPLICATION",
        "Postoperative wound discharge or dehiscence",
        MODERATE,
        1.5,
        Criteria(answer_equals=(("POSTOP_WOUND_APPEARANCE", "DISCHARGE"),)),
        "Inspect the wound and consider infection.",
    ),
)

BY_CODE = {flag.code: flag for flag in RED_FLAGS}


@dataclass
class Alert:
    code: str
    label: str
    severity: str
    advice: str
    points: float

    context_notes: list[str]


def evaluate(ctx: ClinicalContext) -> list[Alert]:
    alerts = []
    for flag in RED_FLAGS:
        if not flag.criteria.matches(ctx):
            continue
        notes = []
        for vital in flag.vitals_used:
            for code in confounder_kb.affecting(vital):
                if code in ctx.confounders:
                    notes.append(confounder_kb.BY_CODE[code].label)
        alerts.append(
            Alert(
                code=flag.code,
                label=flag.label,
                severity=flag.severity,
                advice=flag.advice,
                points=flag.points,
                context_notes=sorted(set(notes)),
            )
        )
    alerts.sort(key=lambda alert: (alert.severity != HIGH, -alert.points))
    return alerts


PAIN_CONTRIBUTION = 0.30
FLAG_CAP = 5.0
VITAL_DERANGEMENT_POINTS = 0.4
AGE_THRESHOLD = 75
AGE_POINTS = 0.5
COMORBIDITY_POINTS = 0.25
COMORBIDITY_CAP = 1.0
ACUTE_ONSET_POINTS = 0.6
RAPID_WORSENING_POINTS = 0.6
RAPID_WORSENING_WINDOW_HOURS = 72.0
NEUROLOGICAL_POINTS = 0.8
RESPIRATORY_POINTS = 0.6
CARDIOVASCULAR_POINTS = 0.6
TRAUMA_POINTS = 0.8
FUNCTIONAL_POINTS = 0.8
CONTRADICTION_POINTS = 0.3
CONTRADICTION_CAP = 0.9
INCOMPLETE_POINTS = 0.4
INCOMPLETE_THRESHOLD = 0.5

NEUROLOGICAL_WARNING_SYMPTOMS = frozenset(
    {"FOCAL_DEFICIT", "MOTOR_WEAKNESS", "CONFUSION", "SADDLE_ANAESTHESIA", "URINARY_RETENTION"}
)
RESPIRATORY_WARNING_SYMPTOMS = frozenset({"DYSPNOEA", "HAEMOPTYSIS"})
CARDIOVASCULAR_WARNING_SYMPTOMS = frozenset({"CHEST_PRESSURE", "SYNCOPE", "PALPITATIONS"})

PRIORITY_DISCLAIMER = (
    "The clinical priority score is a decision-support indicator built from the recorded "
    "findings. It is not a diagnosis, and it does not predict mortality, survival or the "
    "probability of an emergency."
)

PRIORITY_LEVELS = (
    (2.0, "LOW", "Low"),
    (4.0, "MILD", "Mild"),
    (6.0, "MODERATE", "Moderate"),
    (8.0, "HIGH", "High"),
    (10.01, "VERY_HIGH", "Very high"),
)

# The adult band, kept under its original name because it is what a caller with no
# patient in hand gets. Anything that has a patient reads the band through
# profiles.normal_ranges, which picks by age and state. One table, in reference_ranges.
VITAL_NORMAL_RANGES = reference_ranges.normal(reference_ranges.ADULT_BAND)


def priority_level(score: float) -> tuple[str, str]:
    for upper, code, label in PRIORITY_LEVELS:
        if score < upper:
            return code, label
    return PRIORITY_LEVELS[-1][1], PRIORITY_LEVELS[-1][2]


@dataclass
class PriorityFactor:
    label: str
    points: float

    code: str = ""


@dataclass
class Priority:
    score: float
    factors: list[PriorityFactor]

    @property
    def level(self) -> str:
        return priority_level(self.score)[0]

    @property
    def level_label(self) -> str:
        return priority_level(self.score)[1]


def deranged_vitals(
    vitals: dict[str, float], ranges: dict[str, tuple[float, float]] | None = None
) -> list[str]:
    """Which recorded vitals sit outside their resting range. The ranges come from the
    patient's profile band where there is one; without them this falls back to the adult
    band, which is the only safe default when no patient is in hand."""
    bands = VITAL_NORMAL_RANGES if ranges is None else ranges
    out = []
    for name, (low, high) in bands.items():
        value = vitals.get(name)
        if value is not None and not low <= value <= high:
            out.append(name)
    return out


def deranged_for(ctx: ClinicalContext) -> list[str]:
    return deranged_vitals(ctx.vitals, profiles.normal_ranges(ctx))


def _acute(ctx: ClinicalContext) -> bool:
    return ctx.onset == "SUDDEN" and ctx.onset_speed in ("SECONDS", "MINUTES")


def _rapidly_worsening(ctx: ClinicalContext) -> bool:
    return (
        ctx.course in ("WORSENING", "PROGRESSIVE")
        and ctx.duration_hours is not None
        and ctx.duration_hours <= RAPID_WORSENING_WINDOW_HOURS
    )


def _major_trauma(ctx: ClinicalContext) -> bool:
    return ctx.recent_trauma and bool(
        {"HEAD", "NECK", "BACK", "CHEST", "ABDOMEN", "PELVIS"} & ctx.regions
        or ctx.symptoms & NEUROLOGICAL_WARNING_SYMPTOMS
    )


def _severe_functional_impairment(ctx: ClinicalContext) -> bool:
    scores = list(ctx.functional_impact.values())
    return bool(scores) and (max(scores) >= 4 or sum(scores) / len(scores) >= 3)


def priority(
    ctx: ClinicalContext,
    estimated_pain: float | None,
    alerts: list[Alert],
    *,
    contradictions: int = 0,
    completeness: float | None = None,
) -> Priority:
    factors = []

    def add(code: str, label: str, points: float) -> None:
        if points > 0:
            factors.append(PriorityFactor(label, round(points, 2), code))

    if estimated_pain is not None:
        add(
            "PAIN",
            f"Estimated pain {estimated_pain:.1f} / 10",
            estimated_pain * PAIN_CONTRIBUTION,
        )

    flag_points = min(sum(alert.points for alert in alerts), FLAG_CAP)
    if flag_points:
        high = sum(1 for alert in alerts if alert.severity == HIGH)
        label = f"{len(alerts)} red flag rule(s) triggered"
        if high:
            label += f", {high} of higher severity"
        add("RED_FLAGS", label, flag_points)

    deranged = deranged_for(ctx)
    if deranged:
        add(
            "VITALS",
            f"Vital signs outside the configured range: {', '.join(deranged)}",
            len(deranged) * VITAL_DERANGEMENT_POINTS,
        )

    if _acute(ctx):
        add(
            "ACUTE_ONSET",
            "Sudden onset reaching full intensity within minutes",
            ACUTE_ONSET_POINTS,
        )
    if _rapidly_worsening(ctx):
        add(
            "RAPID_WORSENING",
            "Worsening course within the first three days",
            RAPID_WORSENING_POINTS,
        )

    neuro = ctx.symptoms & NEUROLOGICAL_WARNING_SYMPTOMS
    if neuro:
        add(
            "NEUROLOGICAL",
            f"Neurological warning feature(s): {', '.join(sorted(neuro))}",
            NEUROLOGICAL_POINTS,
        )
    if ctx.symptoms & RESPIRATORY_WARNING_SYMPTOMS or "resp_rate" in deranged:
        add("RESPIRATORY", "Respiratory warning feature", RESPIRATORY_POINTS)
    if ctx.symptoms & CARDIOVASCULAR_WARNING_SYMPTOMS and "CHEST" in ctx.regions:
        add(
            "CARDIOVASCULAR",
            "Chest pain with a cardiovascular warning feature",
            CARDIOVASCULAR_POINTS,
        )
    if _major_trauma(ctx):
        add("TRAUMA", "Recent trauma to the trunk, head or spine", TRAUMA_POINTS)
    if _severe_functional_impairment(ctx):
        add("FUNCTIONAL", "Severe functional impairment", FUNCTIONAL_POINTS)

    if ctx.age is not None and ctx.age >= AGE_THRESHOLD:
        add("AGE", f"Age {ctx.age}", AGE_POINTS)

    from knowledge.diseases import PAIN_RELEVANT

    relevant = ctx.conditions & PAIN_RELEVANT
    if relevant:
        add(
            "COMORBIDITY",
            f"{len(relevant)} pain-relevant chronic condition(s)",
            min(len(relevant) * COMORBIDITY_POINTS, COMORBIDITY_CAP),
        )

    if contradictions:
        add(
            "CONTRADICTIONS",
            f"{contradictions} inconsistenc{'y' if contradictions == 1 else 'ies'} in the record",
            min(contradictions * CONTRADICTION_POINTS, CONTRADICTION_CAP),
        )
    if completeness is not None and completeness < INCOMPLETE_THRESHOLD:
        add(
            "INCOMPLETE",
            f"Record only {int(completeness * 100)} per cent complete",
            INCOMPLETE_POINTS,
        )

    total = min(sum(factor.points for factor in factors), 10.0)
    return Priority(score=round(total, 1), factors=factors)
