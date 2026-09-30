"""Symptoms that can accompany the pain.

`systemic` marks the ones that point away from a purely local problem; `alarm` marks the
ones the red-flag rules in rules.py read. Neither flag is a diagnosis: they only decide
which questions are offered and which rules are evaluated.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Symptom:
    code: str
    label: str
    group: str
    systemic: bool = False
    alarm: bool = False


SYMPTOMS = (
    Symptom("FEVER", "Fever", "GENERAL", systemic=True, alarm=True),
    Symptom("CHILLS", "Chills", "GENERAL", systemic=True),
    Symptom("SWEATING", "Sweating", "GENERAL", systemic=True),
    Symptom("WEIGHT_LOSS", "Unintentional weight loss", "GENERAL", systemic=True, alarm=True),
    Symptom("FATIGUE", "Fatigue", "GENERAL", systemic=True),
    Symptom("NAUSEA", "Nausea", "DIGESTIVE"),
    Symptom("VOMITING", "Vomiting", "DIGESTIVE"),
    Symptom("DIARRHOEA", "Diarrhoea", "DIGESTIVE"),
    Symptom("CONSTIPATION", "Constipation", "DIGESTIVE"),
    Symptom("ABDOMINAL_DISTENSION", "Abdominal distension", "DIGESTIVE", alarm=True),
    Symptom("DYSPNOEA", "Shortness of breath", "RESPIRATORY", alarm=True),
    Symptom("COUGH", "Cough", "RESPIRATORY"),
    Symptom("HAEMOPTYSIS", "Coughing up blood", "RESPIRATORY", alarm=True),
    Symptom("PALPITATIONS", "Palpitations", "CARDIAC"),
    Symptom("CHEST_PRESSURE", "Chest pressure", "CARDIAC", alarm=True),
    Symptom("SYNCOPE", "Loss of consciousness", "NEUROLOGICAL", systemic=True, alarm=True),
    Symptom("DIZZINESS", "Dizziness", "NEUROLOGICAL"),
    Symptom("HEADACHE", "Headache", "NEUROLOGICAL"),
    Symptom("FOCAL_DEFICIT", "Sudden focal neurological deficit", "NEUROLOGICAL", alarm=True),
    Symptom("VISION_CHANGE", "Vision changes", "NEUROLOGICAL", alarm=True),
    Symptom("NUMBNESS", "Numbness", "NEUROLOGICAL"),
    Symptom("TINGLING", "Tingling", "NEUROLOGICAL"),
    Symptom("MOTOR_WEAKNESS", "Muscle weakness", "NEUROLOGICAL", alarm=True),
    Symptom("SADDLE_ANAESTHESIA", "Saddle anaesthesia", "NEUROLOGICAL", alarm=True),
    Symptom("URINARY_SYMPTOMS", "Urinary symptoms", "UROGENITAL"),
    Symptom("URINARY_RETENTION", "Urinary retention or incontinence", "UROGENITAL", alarm=True),
    Symptom("BLEEDING", "Bleeding", "OTHER", alarm=True),
    Symptom("SWELLING", "Swelling", "OTHER"),
    Symptom("SKIN_CHANGE", "Skin changes", "OTHER"),
    Symptom("RASH", "Rash", "OTHER"),
    Symptom("JOINT_STIFFNESS", "Joint stiffness", "OTHER"),
    Symptom("OTHER_SYMPTOM", "Other", "OTHER"),
)

BY_CODE = {symptom.code: symptom for symptom in SYMPTOMS}
ALARM_SYMPTOMS = frozenset(s.code for s in SYMPTOMS if s.alarm)
SYSTEMIC_SYMPTOMS = frozenset(s.code for s in SYMPTOMS if s.systemic)
GROUPS = (
    "GENERAL",
    "DIGESTIVE",
    "RESPIRATORY",
    "CARDIAC",
    "NEUROLOGICAL",
    "UROGENITAL",
    "OTHER",
)
