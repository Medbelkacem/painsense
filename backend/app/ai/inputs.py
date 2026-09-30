"""Assembling model inputs from stored records.

The only place that turns a PainAssessment into a ClinicalContext. Keeping it in one
function means there is a single answer to "what did the model see", and the self-reported
score is absent from that answer because ClinicalContext has nowhere to put it. The same
holds for the per-site intensities recorded against anatomical structures: the structures
themselves are read, the intensities are not.
"""

from app.database.models import PainAssessment
from app.knowledge.context import ClinicalContext


def context_for(assessment: PainAssessment) -> ClinicalContext:
    measurement = assessment.measurement
    vitals: dict[str, float] = {}
    if measurement is not None:
        for name in (
            "hr",
            "resp_rate",
            "sbp",
            "dbp",
            "spo2",
            "temperature_c",
            "glucose_mmol",
        ):
            value = getattr(measurement, name)
            if value is not None:
                vitals[name] = float(value)
        if measurement.bmi is not None:
            vitals["bmi"] = float(measurement.bmi)

    # Both kinds of site contribute their side, so laterality reads the same whether it was
    # recorded on the 3D model or on the flat diagram.
    sides = {row.side for row in assessment.locations}
    sides.update(row.side for row in assessment.anatomical_sites)

    return ClinicalContext(
        age=assessment.patient_age_years,
        sex=assessment.patient.sex.value if assessment.patient.sex else None,
        pain_locations=frozenset(row.location_code for row in assessment.locations),
        anatomical_structures=frozenset(
            row.structure_code for row in assessment.anatomical_sites
        ),
        sides=frozenset(sides),
        qualities=frozenset(row.quality_code for row in assessment.qualities),
        symptoms=frozenset(row.symptom_code for row in assessment.symptoms),
        conditions=frozenset(row.disease_code for row in assessment.patient.conditions),
        factors=frozenset(row.factor_code for row in assessment.factors),
        confounders=frozenset(row.confounder_code for row in assessment.confounders),
        onset=assessment.onset.value,
        pattern=assessment.pattern.value,
        course=assessment.course.value,
        duration_hours=assessment.duration_hours,
        episodes_per_day=assessment.episodes_per_day,
        episode_minutes=assessment.episode_minutes,
        radiates=assessment.radiates,
        recent_trauma=assessment.recent_trauma,
        recent_surgery=assessment.recent_surgery,
        vitals=vitals,
        answers={row.question_code: row.value for row in assessment.answers},
    )
