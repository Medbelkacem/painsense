"""Transparent rule layer: red flags, the clinical priority indicator, and pain bands.

Every rule is data. Nothing here trains, fits or learns, so a clinician can read exactly
why an alert fired and an administrator can change a threshold without touching code that
runs the model.

A red flag says the recorded information contains a feature that usually warrants prompt
review. It is not a diagnosis and it does not say the feature is present because of a
particular disease.
"""

from dataclasses import dataclass

from app.knowledge import confounders as confounder_kb
from app.knowledge.context import ClinicalContext, Criteria

HIGH = "HIGH"
MODERATE = "MODERATE"

# Visualisation bands only. Thresholds sit on the half-point so that an estimate rounds
# into the band the challenge statement describes: 0 none, 1-3 mild, 4-6 moderate,
# 7-9 severe, 10 extreme. Change the table to change the mapping.
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
    # Vitals this rule reads. Used to annotate the alert when the clinician has recorded
    # context that can move the same value, so a rule fired by tachycardia alone is not
    # presented as if pain were the only explanation.
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
    # Recorded context that could move the same vital sign. Empty for rules that do not
    # read vitals.
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


# Priority weights. All of them are meant to be edited: the indicator is a documented
# arithmetic of recorded findings, not a fitted risk model.
PAIN_CONTRIBUTION = 0.30
FLAG_CAP = 5.0
VITAL_DERANGEMENT_POINTS = 0.4
AGE_THRESHOLD = 75
AGE_POINTS = 0.5
COMORBIDITY_POINTS = 0.25
COMORBIDITY_CAP = 1.0

VITAL_NORMAL_RANGES = {
    "hr": (50.0, 100.0),
    "resp_rate": (10.0, 20.0),
    "sbp": (95.0, 145.0),
    "dbp": (55.0, 95.0),
    "spo2": (95.0, 100.0),
    "temperature_c": (36.0, 37.9),
    "glucose_mmol": (3.9, 11.0),
}


@dataclass
class PriorityFactor:
    label: str
    points: float


@dataclass
class Priority:
    score: float
    factors: list[PriorityFactor]


def deranged_vitals(vitals: dict[str, float]) -> list[str]:
    out = []
    for name, (low, high) in VITAL_NORMAL_RANGES.items():
        value = vitals.get(name)
        if value is not None and not low <= value <= high:
            out.append(name)
    return out


def priority(
    ctx: ClinicalContext, estimated_pain: float | None, alerts: list[Alert]
) -> Priority:
    """A 0-10 indicator of how soon this patient should be looked at again.

    It is not a probability of anything: not of death, not of an emergency, not of a
    diagnosis. It is the sum of the contributions listed in the returned factors.
    """
    factors = []

    if estimated_pain is not None:
        points = round(estimated_pain * PAIN_CONTRIBUTION, 2)
        factors.append(PriorityFactor(f"Estimated pain {estimated_pain:.1f} / 10", points))

    flag_points = min(sum(alert.points for alert in alerts), FLAG_CAP)
    if flag_points:
        high = sum(1 for alert in alerts if alert.severity == HIGH)
        label = f"{len(alerts)} red flag rule(s) triggered"
        if high:
            label += f", {high} of higher severity"
        factors.append(PriorityFactor(label, round(flag_points, 2)))

    deranged = deranged_vitals(ctx.vitals)
    if deranged:
        factors.append(
            PriorityFactor(
                f"Vital signs outside the configured range: {', '.join(deranged)}",
                round(len(deranged) * VITAL_DERANGEMENT_POINTS, 2),
            )
        )

    if ctx.age is not None and ctx.age >= AGE_THRESHOLD:
        factors.append(PriorityFactor(f"Age {ctx.age}", AGE_POINTS))

    from app.knowledge.diseases import PAIN_RELEVANT

    relevant = ctx.conditions & PAIN_RELEVANT
    if relevant:
        points = min(len(relevant) * COMORBIDITY_POINTS, COMORBIDITY_CAP)
        factors.append(
            PriorityFactor(
                f"{len(relevant)} pain-relevant chronic condition(s)", round(points, 2)
            )
        )

    total = min(sum(factor.points for factor in factors), 10.0)
    return Priority(score=round(total, 1), factors=factors)
