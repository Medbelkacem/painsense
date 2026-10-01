from fastapi import APIRouter
from sqlalchemy import select

from backend.api import schemas
from backend.dependencies import CurrentUser, DbSession
from database.models import (
    Confounder,
    Disease,
    MedicationClass,
    PainCause,
    PainFactor,
    PainLocation,
    PainQuality,
    PainType,
    Patient,
    Symptom,
)
from knowledge import (
    causes,
    medications,
    profiles,
    questions,
    reference_ranges,
    rules,
    scales,
)
from knowledge.context import ClinicalContext, MedicationContext

router = APIRouter(prefix="/api", tags=["catalogue"])

_QUESTION_GROUP_LABELS = dict(questions.GROUPS)


@router.get("/pain-locations", response_model=list[schemas.LocationOut])
def pain_locations(db: DbSession, user: CurrentUser) -> list[schemas.LocationOut]:
    rows = db.scalars(select(PainLocation).order_by(PainLocation.region, PainLocation.label))
    return [schemas.LocationOut.model_validate(row) for row in rows]


@router.get("/pain-qualities", response_model=list[schemas.QualityOut])
def pain_qualities(db: DbSession, user: CurrentUser) -> list[schemas.QualityOut]:
    rows = db.scalars(select(PainQuality).order_by(PainQuality.label))
    return [schemas.QualityOut.model_validate(row) for row in rows]


@router.get("/pain-types", response_model=list[schemas.PainTypeOut])
def pain_types(db: DbSession, user: CurrentUser) -> list[schemas.PainTypeOut]:
    rows = db.scalars(select(PainType).order_by(PainType.group, PainType.label))
    return [schemas.PainTypeOut.model_validate(row) for row in rows]


@router.get("/symptoms", response_model=list[schemas.SymptomOut])
def symptoms(db: DbSession, user: CurrentUser) -> list[schemas.SymptomOut]:
    rows = db.scalars(select(Symptom).order_by(Symptom.group, Symptom.label))
    return [schemas.SymptomOut.model_validate(row) for row in rows]


@router.get("/diseases", response_model=list[schemas.DiseaseOut])
def diseases(db: DbSession, user: CurrentUser) -> list[schemas.DiseaseOut]:
    """The comorbidity list a clinician is offered when recording a patient's history.

    Curated entries only. `app.sync` adds diseases to this table when an external
    publisher turns out to hold data for one the platform had not heard of, and those
    belong on the dataset dashboard rather than in a clinical form until someone has
    reviewed them. `/api/external-datasets/overview` returns the full set.
    """
    rows = db.scalars(
        select(Disease)
        .where(Disease.curated.is_(True))
        .order_by(Disease.category, Disease.label)
    )
    return [schemas.DiseaseOut.model_validate(row) for row in rows]


@router.get("/pain-factors", response_model=list[schemas.FactorOut])
def pain_factors(db: DbSession, user: CurrentUser) -> list[schemas.FactorOut]:
    rows = db.scalars(select(PainFactor).order_by(PainFactor.kind, PainFactor.label))
    return [schemas.FactorOut.model_validate(row) for row in rows]


@router.get("/confounders", response_model=list[schemas.ConfounderOut])
def confounders(db: DbSession, user: CurrentUser) -> list[schemas.ConfounderOut]:
    rows = db.scalars(select(Confounder).order_by(Confounder.label))
    return [schemas.ConfounderOut.model_validate(row) for row in rows]


@router.get("/medication-classes", response_model=list[schemas.MedicationClassOut])
def medication_classes(db: DbSession, user: CurrentUser) -> list[schemas.MedicationClassOut]:
    rows = db.scalars(select(MedicationClass))
    ordered = {row.code: row for row in rows}
    return [
        schemas.MedicationClassOut.model_validate(ordered[entry.code])
        for entry in medications.MEDICATION_CLASSES
        if entry.code in ordered
    ]


@router.get("/medication-vocabulary", response_model=dict)
def medication_vocabulary(user: CurrentUser) -> dict:
    return {
        "dose_categories": [{"value": v, "label": l} for v, l in medications.DOSE_CATEGORIES],
        "frequencies": [{"value": v, "label": l} for v, l in medications.FREQUENCIES],
        "pain_effects": [{"value": v, "label": l} for v, l in medications.PAIN_EFFECTS],
        "sedation_effects": [{"value": v, "label": l} for v, l in medications.SEDATION_EFFECTS],
    }


@router.get("/pain-causes", response_model=list[dict])
def pain_causes(db: DbSession, user: CurrentUser) -> list[dict]:
    rows = db.scalars(select(PainCause).order_by(PainCause.group, PainCause.label))
    return [
        {
            "code": row.code,
            "label": row.label,
            "group": row.group,
            "pain_types": row.pain_types,
            "note": row.note,
            "signals": [signal.label for signal in causes.BY_CODE[row.code].signals]
            if row.code in causes.BY_CODE
            else [],
        }
        for row in rows
    ]


@router.get("/clinical-rules", response_model=list[dict])
def clinical_rules(user: CurrentUser) -> list[dict]:
    return [
        {
            "code": rule.code,
            "label": rule.label,
            "severity": rule.severity,
            "points": rule.points,
            "advice": rule.advice,
            "vitals_used": list(rule.vitals_used),
        }
        for rule in rules.RED_FLAGS
    ]


@router.get("/pain-bands", response_model=list[schemas.BandOut])
def pain_bands(user: CurrentUser) -> list[schemas.BandOut]:
    return [
        schemas.BandOut(code=code, label=label, upper_bound=upper)
        for upper, code, label in rules.PAIN_BANDS
    ]


def _question_out(question: questions.Question) -> schemas.QuestionOut:
    return schemas.QuestionOut(
        code=question.code,
        prompt=question.prompt,
        kind=question.kind,
        group=question.group,
        group_label=_QUESTION_GROUP_LABELS.get(question.group, question.group),
        options=[{"value": value, "label": label} for value, label in question.options],
        unit=question.unit,
        minimum=question.minimum,
        maximum=question.maximum,
        help_text=question.help_text,
        order=question.order,
    )


@router.get("/clinical-questions", response_model=list[schemas.QuestionOut])
def clinical_questions(user: CurrentUser) -> list[schemas.QuestionOut]:
    return [_question_out(question) for question in questions.QUESTIONS]


def _context_from(payload: schemas.QuestionContext, db) -> ClinicalContext:
    conditions = set(payload.condition_codes)
    age, sex = payload.age, payload.sex.value if payload.sex else None
    if payload.patient_id is not None:
        patient = db.get(Patient, payload.patient_id)
        if patient is not None:
            conditions.update(row.disease_code for row in patient.conditions)
            age = age if age is not None else patient.age_on(patient.updated_at.date())
            sex = sex or (patient.sex.value if patient.sex else None)

    return ClinicalContext(
        age=age,
        sex=sex,
        pain_locations=frozenset(payload.locations),
        qualities=frozenset(payload.quality_codes),
        symptoms=frozenset(payload.symptom_codes),
        conditions=frozenset(conditions),
        factors=frozenset(payload.factor_codes),
        confounders=frozenset(payload.confounder_codes),
        onset=payload.onset.value if payload.onset else None,
        pattern=payload.pattern.value if payload.pattern else None,
        course=payload.course.value if payload.course else None,
        duration_hours=payload.duration_hours,
        radiates=payload.radiates,
        recent_trauma=payload.recent_trauma,
        recent_surgery=payload.recent_surgery,
        medications=tuple(
            MedicationContext(class_code=code) for code in payload.medication_classes
        ),
        functional_impact={
            domain: score
            for domain, score in payload.functional_impact.model_dump().items()
            if score is not None
        },
        answers=dict(payload.answers),
    )


@router.post("/clinical-questions/applicable", response_model=list[schemas.QuestionOut])
def applicable_questions(
    payload: schemas.QuestionContext, db: DbSession, user: CurrentUser
) -> list[schemas.QuestionOut]:
    return [
        _question_out(question) for question in questions.applicable(_context_from(payload, db))
    ]


@router.get("/patient-profiles", response_model=schemas.ProfileCatalogue)
def patient_profiles(user: CurrentUser) -> schemas.ProfileCatalogue:
    """Everything the interface needs to let a clinician choose a profile: the populations,
    the scales each one is compared against, and the physiological bands behind them."""
    return schemas.ProfileCatalogue(
        primary=[_profile_out(entry) for entry in profiles.PRIMARY_PROFILES],
        modifiers=[_profile_out(entry) for entry in profiles.MODIFIER_PROFILES],
        scales=[_scale_out(entry) for entry in scales.SCALES],
        bands=[
            schemas.ReferenceBandOut(
                code=band.code,
                label=band.label,
                min_age=band.min_age,
                max_age=band.max_age,
                source=band.source,
                normal={name: list(span) for name, span in sorted(band.normal.items())},
                unverified=list(band.unverified),
                note=band.note,
            )
            for band in reference_ranges.BANDS
        ],
        notice=(
            "A profile decides which physiological band a reading is compared against and "
            "which scale the estimate is checked against. It carries no diagnosis and no "
            "treatment recommendation. Values marked unverified could not be traced to a "
            "named source and are reported as such rather than as established."
        ),
    )


def _profile_out(entry: profiles.Profile) -> schemas.PatientProfileOut:
    return schemas.PatientProfileOut(
        code=entry.code,
        label=entry.label,
        kind=entry.kind,
        min_age=entry.min_age,
        max_age=entry.max_age,
        can_self_report=entry.can_self_report,
        reference_scale=entry.reference_scale,
        alternative_scales=list(entry.alternative_scales),
        priority_signals=list(entry.priority_signals),
        signals_not_available=list(entry.signals_not_available),
        confounders=list(entry.confounders),
        confidence_penalty=entry.confidence_penalty,
        requires_trimester=entry.requires_trimester,
        prefers_own_history=entry.prefers_own_history,
        interpretation=entry.interpretation,
        note=entry.note,
    )


def _scale_out(entry: scales.Scale) -> schemas.ScaleOut:
    return schemas.ScaleOut(
        code=entry.code,
        label=entry.label,
        kind=entry.kind,
        minimum=entry.minimum,
        maximum=entry.maximum,
        steps=list(entry.steps),
        population=entry.population,
        note=entry.note,
        items=[
            schemas.ScaleItemOut(
                code=item.code,
                label=item.label,
                minimum=item.minimum,
                maximum=item.maximum,
                anchors=list(item.anchors),
            )
            for item in entry.items
        ],
    )
