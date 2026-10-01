from dataclasses import dataclass

CATEGORIES = (
    ("CARDIOVASCULAR", "Cardiovascular"),
    ("ENDOCRINE", "Endocrine and metabolic"),
    ("RESPIRATORY", "Respiratory"),
    ("NEUROLOGICAL", "Neurological"),
    ("MUSCULOSKELETAL", "Musculoskeletal"),
    ("RENAL", "Renal"),
    ("HEPATIC", "Hepatic"),
    ("GASTROINTESTINAL", "Gastrointestinal"),
    ("ONCOLOGICAL", "Oncological"),
    ("PSYCHIATRIC", "Psychiatric"),
    # Carried for diseases discovered by `app.sync` in external publishers'
    # catalogues. No seeded comorbidity uses it.
    ("INFECTIOUS", "Infectious and parasitic"),
    ("OTHER", "Other"),
)


@dataclass(frozen=True)
class Disease:
    code: str
    label: str
    category: str
    pain_relevant: bool = False


DISEASES = (
    Disease("HYPERTENSION", "Hypertension", "CARDIOVASCULAR"),
    Disease("CAD", "Coronary artery disease", "CARDIOVASCULAR", pain_relevant=True),
    Disease("HEART_FAILURE", "Heart failure", "CARDIOVASCULAR"),
    Disease("ARRHYTHMIA", "Arrhythmia", "CARDIOVASCULAR"),
    Disease("PVD", "Peripheral vascular disease", "CARDIOVASCULAR", pain_relevant=True),
    Disease("DIABETES_T1", "Type 1 diabetes", "ENDOCRINE", pain_relevant=True),
    Disease("DIABETES_T2", "Type 2 diabetes", "ENDOCRINE", pain_relevant=True),
    Disease("THYROID", "Thyroid disorder", "ENDOCRINE"),
    Disease("OBESITY", "Obesity", "ENDOCRINE", pain_relevant=True),
    Disease("DYSLIPIDAEMIA", "Dyslipidaemia", "ENDOCRINE"),
    Disease("ASTHMA", "Asthma", "RESPIRATORY"),
    Disease("COPD", "COPD", "RESPIRATORY"),
    Disease("EPILEPSY", "Epilepsy", "NEUROLOGICAL"),
    Disease("MULTIPLE_SCLEROSIS", "Multiple sclerosis", "NEUROLOGICAL", pain_relevant=True),
    Disease("PARKINSONISM", "Parkinsonian disorder", "NEUROLOGICAL", pain_relevant=True),
    Disease("NEUROPATHY", "Peripheral neuropathy", "NEUROLOGICAL", pain_relevant=True),
    Disease("MIGRAINE", "Migraine", "NEUROLOGICAL", pain_relevant=True),
    Disease("OSTEOARTHRITIS", "Osteoarthritis", "MUSCULOSKELETAL", pain_relevant=True),
    Disease(
        "RHEUMATOID_ARTHRITIS", "Rheumatoid arthritis", "MUSCULOSKELETAL", pain_relevant=True
    ),
    Disease("OSTEOPOROSIS", "Osteoporosis", "MUSCULOSKELETAL", pain_relevant=True),
    Disease(
        "CHRONIC_BACK_DISORDER", "Chronic back disorder", "MUSCULOSKELETAL", pain_relevant=True
    ),
    Disease("FIBROMYALGIA", "Fibromyalgia", "MUSCULOSKELETAL", pain_relevant=True),
    Disease("CKD", "Chronic kidney disease", "RENAL"),
    Disease("NEPHROLITHIASIS", "Recurrent kidney stones", "RENAL", pain_relevant=True),
    Disease("CHRONIC_LIVER_DISEASE", "Chronic liver disease", "HEPATIC"),
    Disease("IBD", "Inflammatory bowel disease", "GASTROINTESTINAL", pain_relevant=True),
    Disease(
        "GORD", "Gastro-oesophageal reflux disease", "GASTROINTESTINAL", pain_relevant=True
    ),
    Disease("PEPTIC_ULCER", "Peptic ulcer disease", "GASTROINTESTINAL", pain_relevant=True),
    Disease("IBS", "Irritable bowel syndrome", "GASTROINTESTINAL", pain_relevant=True),
    Disease("CANCER_ACTIVE", "Active cancer", "ONCOLOGICAL", pain_relevant=True),
    Disease("CANCER_HISTORY", "Cancer in remission", "ONCOLOGICAL", pain_relevant=True),
    Disease("CANCER_TREATMENT", "Ongoing cancer treatment", "ONCOLOGICAL", pain_relevant=True),
    Disease("DEPRESSION", "Depression", "PSYCHIATRIC", pain_relevant=True),
    Disease("ANXIETY_DISORDER", "Anxiety disorder", "PSYCHIATRIC", pain_relevant=True),
    Disease("OTHER_CHRONIC", "Other chronic condition", "OTHER"),
)

BY_CODE = {disease.code: disease for disease in DISEASES}
PAIN_RELEVANT = frozenset(d.code for d in DISEASES if d.pain_relevant)
