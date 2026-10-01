from dataclasses import dataclass


@dataclass(frozen=True)
class MedicationClass:
    code: str
    label: str
    analgesic: bool = False
    sedating: bool = False
    affects: tuple[str, ...] = ()
    note: str = ""


MEDICATION_CLASSES = (
    MedicationClass(
        "ACETAMINOPHEN",
        "Paracetamol (acetaminophen)",
        analgesic=True,
        note="Simple analgesic. Little effect on vital signs at therapeutic doses.",
    ),
    MedicationClass(
        "NSAID",
        "Non-steroidal anti-inflammatory",
        analgesic=True,
        affects=("temperature_c",),
        note="Analgesic and antipyretic, so a recorded temperature may be lower than the untreated one.",
    ),
    MedicationClass(
        "OPIOID",
        "Opioid",
        analgesic=True,
        sedating=True,
        affects=("resp_rate", "hr"),
        note="Lowers respiratory rate and heart rate, and changes how intensity is reported.",
    ),
    MedicationClass(
        "CORTICOSTEROID",
        "Corticosteroid",
        affects=("temperature_c", "glucose_mmol"),
        note="Can mask fever and raises blood glucose.",
    ),
    MedicationClass(
        "ANTIDEPRESSANT",
        "Antidepressant",
        analgesic=True,
        sedating=True,
        affects=("hr",),
        note="Tricyclics and SNRIs are used for neuropathic pain; several raise resting heart rate.",
    ),
    MedicationClass(
        "ANTICONVULSANT",
        "Anticonvulsant",
        analgesic=True,
        sedating=True,
        note="Gabapentinoids and others used for neuropathic pain. Sedation is common.",
    ),
    MedicationClass(
        "ANTIHYPERTENSIVE",
        "Antihypertensive",
        affects=("sbp", "dbp", "hr"),
        note="Lowers blood pressure; beta blockers also blunt the heart-rate response to pain.",
    ),
    MedicationClass(
        "ANTIDIABETIC",
        "Antidiabetic",
        affects=("glucose_mmol",),
        note="Moves blood glucose. Hypoglycaemia is a red flag in its own right.",
    ),
    MedicationClass(
        "SEDATIVE",
        "Sedative or hypnotic",
        sedating=True,
        affects=("resp_rate",),
        note="Benzodiazepines and related drugs. Lowers respiratory rate and blunts reporting.",
    ),
    MedicationClass(
        "MUSCLE_RELAXANT",
        "Muscle relaxant",
        sedating=True,
        note="Used for musculoskeletal pain; sedation is the usual side effect.",
    ),
    MedicationClass(
        "TRIPTAN",
        "Triptan",
        analgesic=True,
        affects=("sbp",),
        note="Migraine-specific. Can raise blood pressure.",
    ),
    MedicationClass(
        "LOCAL_ANAESTHETIC",
        "Local or regional anaesthetic",
        analgesic=True,
        note="A recent block removes pain at the site without changing anything systemic.",
    ),
    MedicationClass(
        "ANTIBIOTIC",
        "Antibiotic",
        note="Says an infection is being treated. No direct effect on the vital signs.",
    ),
    MedicationClass(
        "ANTICOAGULANT",
        "Anticoagulant or antiplatelet",
        note="Bleeding with instability is weighted more heavily when one is recorded.",
    ),
    MedicationClass("OTHER", "Other", note="A class not listed. Name it in the record."),
)

BY_CODE = {entry.code: entry for entry in MEDICATION_CLASSES}
ANALGESIC = frozenset(entry.code for entry in MEDICATION_CLASSES if entry.analgesic)
SEDATING = frozenset(entry.code for entry in MEDICATION_CLASSES if entry.sedating)

DOSE_CATEGORIES = (
    ("LOW", "Low"),
    ("STANDARD", "Standard"),
    ("HIGH", "High"),
    ("UNKNOWN", "Not known"),
)
FREQUENCIES = (
    ("SINGLE", "Single dose"),
    ("DAILY", "Once a day"),
    ("TWICE_DAILY", "Twice a day"),
    ("THREE_TIMES_DAILY", "Three times a day"),
    ("FOUR_TIMES_DAILY", "Four times a day"),
    ("AS_NEEDED", "As needed"),
    ("CONTINUOUS", "Continuous"),
    ("UNKNOWN", "Not known"),
)
PAIN_EFFECTS = (
    ("NONE", "No relief"),
    ("PARTIAL", "Partial relief"),
    ("GOOD", "Good relief"),
    ("UNKNOWN", "Too early to say"),
)
SEDATION_EFFECTS = (
    ("NONE", "Not sedated"),
    ("MILD", "Drowsy but rousable"),
    ("MARKED", "Markedly sedated"),
    ("UNKNOWN", "Not assessed"),
)

DOSE_CODES = frozenset(code for code, _ in DOSE_CATEGORIES)
FREQUENCY_CODES = frozenset(code for code, _ in FREQUENCIES)
PAIN_EFFECT_CODES = frozenset(code for code, _ in PAIN_EFFECTS)
SEDATION_CODES = frozenset(code for code, _ in SEDATION_EFFECTS)


def affecting(vital: str) -> tuple[str, ...]:
    return tuple(entry.code for entry in MEDICATION_CLASSES if vital in entry.affects)
