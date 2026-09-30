"""Reference data and the dynamic questionnaire.

The taxonomies are served from the database so a client can cache them, and the applicable
questions are computed from the draft assessment the client sends. That is what keeps the
questionnaire out of the interface code: the client renders whatever comes back and knows
nothing about why a question appears.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api import schemas
from app.database.models import (
    Confounder,
    Disease,
    PainCause,
    PainFactor,
    PainLocation,
    PainQuality,
    PainType,
    Patient,
    Symptom,
)
from app.dependencies import CurrentUser, DbSession
from app.knowledge import causes, questions, rules
from app.knowledge.context import ClinicalContext

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
    rows = db.scalars(select(Disease).order_by(Disease.category, Disease.label))
    return [schemas.DiseaseOut.model_validate(row) for row in rows]


@router.get("/pain-factors", response_model=list[schemas.FactorOut])
def pain_factors(db: DbSession, user: CurrentUser) -> list[schemas.FactorOut]:
    rows = db.scalars(select(PainFactor).order_by(PainFactor.kind, PainFactor.label))
    return [schemas.FactorOut.model_validate(row) for row in rows]


@router.get("/confounders", response_model=list[schemas.ConfounderOut])
def confounders(db: DbSession, user: CurrentUser) -> list[schemas.ConfounderOut]:
    rows = db.scalars(select(Confounder).order_by(Confounder.label))
    return [schemas.ConfounderOut.model_validate(row) for row in rows]


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
    """The whole question bank, for reference and for offline caching."""
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
        answers=dict(payload.answers),
    )


@router.post("/clinical-questions/applicable", response_model=list[schemas.QuestionOut])
def applicable_questions(
    payload: schemas.QuestionContext, db: DbSession, user: CurrentUser
) -> list[schemas.QuestionOut]:
    """The questions worth asking for this draft, in the order they should be shown."""
    return [
        _question_out(question) for question in questions.applicable(_context_from(payload, db))
    ]
