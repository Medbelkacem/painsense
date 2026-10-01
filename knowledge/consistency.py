"""Cross-checks over what was recorded, raised as warnings rather than refusals.

A diabetic with no antidiabetic on the chart is usually a gap in the record, not a fact
about the patient, and the right response is to ask, not to block the save. The one
exception is the urgent pattern at the bottom: it still saves, but it comes back flagged
so the interface can put a banner over the whole assessment.
"""

from dataclasses import dataclass

from knowledge import locations
from knowledge.wards import ADULT_WARDS, PAEDIATRIC_AGE_LIMIT, PAEDIATRIC_WARD

WARNING = "WARNING"
URGENT = "URGENT"

FEVER_TEMPERATURE = 38.0


@dataclass(frozen=True)
class Finding:
    code: str
    level: str
    message: str


# Conditions that are nearly always treated, with the medication class and the drug names
# that would show the treatment is on the chart. Names are matched as substrings of what
# the clinician typed, so "Insuline lente" and "metformine 850" both count.
TREATED_CONDITIONS = {
    "DIABETES_T1": ("Type 1 diabetes", "ANTIDIABETIC", ("insulin",)),
    "DIABETES_T2": (
        "Type 2 diabetes",
        "ANTIDIABETIC",
        ("insulin", "metformin", "glicl", "glib", "glim", "gliptin", "flozin", "glitazone"),
    ),
    "HYPERTENSION": (
        "Hypertension",
        "ANTIHYPERTENSIVE",
        (
            "amlodipin", "nifedipin", "ramipril", "enalapril", "perindopril", "captopril",
            "losartan", "valsartan", "candesartan", "irbesartan", "bisoprolol", "atenolol",
            "nebivolol", "thiazide", "indapamid", "furosemid", "spironolacton",
        ),
    ),
    "EPILEPSY": (
        "Epilepsy",
        "ANTICONVULSANT",
        ("valpro", "carbamazepin", "levetiracetam", "lamotrigin", "phenytoin", "topiramat"),
    ),
    "ASTHMA": (
        "Asthma",
        None,
        ("salbutamol", "ventolin", "budesonid", "fluticason", "beclometason", "formoterol",
         "salmeterol", "montelukast"),
    ),
}


def _treated(class_code, names, medication_classes, medication_names) -> bool:
    if class_code and class_code in medication_classes:
        return True
    lowered = [name.lower() for name in medication_names]
    return any(fragment in name for name in lowered for fragment in names)


def patient_findings(
    *,
    age: int | None,
    ward: str | None,
    conditions,
    medication_names,
    medication_classes=(),
) -> list[Finding]:
    found = []
    for code in sorted(conditions):
        entry = TREATED_CONDITIONS.get(code)
        if entry is None:
            continue
        label, class_code, names = entry
        if not _treated(class_code, names, set(medication_classes), medication_names):
            found.append(
                Finding(
                    f"UNTREATED_{code}",
                    WARNING,
                    f"{label} is recorded with no treatment on the medication list. "
                    "Confirm the current medication.",
                )
            )
    if age is not None and ward:
        if ward == PAEDIATRIC_WARD and age >= PAEDIATRIC_AGE_LIMIT:
            found.append(
                Finding(
                    "ADULT_IN_PAEDIATRICS",
                    WARNING,
                    f"A patient aged {age} is recorded in {PAEDIATRIC_WARD}. "
                    "Check the age or the ward.",
                )
            )
        elif ward in ADULT_WARDS and age < PAEDIATRIC_AGE_LIMIT:
            found.append(
                Finding(
                    "CHILD_IN_ADULT_WARD",
                    WARNING,
                    f"A patient aged {age} is recorded in {ward}, an adult ward. "
                    "Check the age or the ward.",
                )
            )
    return found


def assessment_findings(
    *,
    symptoms,
    location_codes,
    onset: str | None,
    temperature_c: float | None = None,
) -> list[Finding]:
    fever = "FEVER" in symptoms or (
        temperature_c is not None and temperature_c >= FEVER_TEMPERATURE
    )
    chest = any(
        code in locations.BY_CODE and locations.BY_CODE[code].region == "CHEST"
        for code in location_codes
    )
    if fever and chest and onset == "SUDDEN":
        return [
            Finding(
                "FEVER_CHEST_SUDDEN",
                URGENT,
                "Fever with chest pain of sudden onset. Requires urgent clinical review.",
            )
        ]
    return []
