from sqlalchemy.orm import Session

from database import models
from knowledge import (
    anatomy,
    causes,
    confounders,
    diseases,
    factors,
    locations,
    medications,
    pain_types,
    qualities,
    questions,
    rules,
    symptoms,
)


def _upsert(db: Session, model, code: str, **values) -> None:
    row = db.get(model, code)
    if row is None:
        db.add(model(code=code, **values))
        return
    for field, value in values.items():
        setattr(row, field, value)


def _sync_relationships(db: Session) -> None:
    from sqlalchemy import delete, select

    existing = {
        (row.source_code, row.target_code, row.relation)
        for row in db.scalars(select(models.AnatomicalRelationship))
    }
    wanted = {(link.source, link.target, link.relation) for link in anatomy.RELATIONSHIPS}
    if existing == wanted:
        return
    db.execute(delete(models.AnatomicalRelationship))
    db.flush()
    for source, target, relation in sorted(wanted):
        db.add(
            models.AnatomicalRelationship(
                source_code=source, target_code=target, relation=relation
            )
        )


def seed_reference_data(db: Session) -> dict[str, int]:
    for entry in locations.LOCATIONS:
        _upsert(
            db,
            models.PainLocation,
            entry.code,
            label=entry.label,
            region=entry.region,
            parent_code=entry.parent,
        )
    for order, (code, label) in enumerate(anatomy.REGIONS, start=1):
        _upsert(db, models.AnatomicalRegion, code, label=label, display_order=10 * order)
    for entry in anatomy.STRUCTURE_TYPES:
        _upsert(
            db,
            models.AnatomicalStructureType,
            entry.code,
            label=entry.label,
            description=entry.description,
            display_order=entry.order,
        )
    for entry in anatomy.STRUCTURES:
        _upsert(
            db,
            models.AnatomicalStructure,
            entry.code,
            label=entry.label,
            latin=entry.latin,
            structure_type=entry.type,
            region=entry.region,
            location_code=entry.location,
            location_left=entry.location_left or None,
            location_right=entry.location_right or None,
            laterality=entry.laterality,
            subregion=anatomy.subregion_of(entry.code),
            parent_code=entry.parent,
            system=entry.system_code,
            synonyms=list(entry.synonyms),
            sex=entry.sex,
            has_mesh=entry.has_mesh,
            pain_selectable=entry.pain_selectable,
            description=entry.description,
            note=entry.note,
        )
    _sync_relationships(db)
    for entry in medications.MEDICATION_CLASSES:
        _upsert(
            db,
            models.MedicationClass,
            entry.code,
            label=entry.label,
            analgesic=entry.analgesic,
            sedating=entry.sedating,
            affects=list(entry.affects),
            note=entry.note,
        )
    for entry in qualities.QUALITIES:
        _upsert(
            db,
            models.PainQuality,
            entry.code,
            label=entry.label,
            neuropathic_hint=entry.neuropathic_hint,
        )
    for entry in pain_types.PAIN_TYPES:
        _upsert(
            db,
            models.PainType,
            entry.code,
            label=entry.label,
            group=entry.group,
            parent_code=entry.parent,
            description=entry.description,
        )
    for entry in symptoms.SYMPTOMS:
        _upsert(
            db,
            models.Symptom,
            entry.code,
            label=entry.label,
            group=entry.group,
            systemic=entry.systemic,
            alarm=entry.alarm,
        )
    for entry in diseases.DISEASES:
        # `curated` is set explicitly on every pass: an entry that `app.sync` created and
        # a clinician later added to the knowledge base must be promoted, not left
        # flagged as discovered.
        _upsert(
            db,
            models.Disease,
            entry.code,
            label=entry.label,
            category=entry.category,
            pain_relevant=entry.pain_relevant,
            curated=True,
            origin="knowledge_base",
        )
    for entry in factors.FACTORS:
        _upsert(db, models.PainFactor, entry.code, label=entry.label, kind=entry.kind)
    for entry in confounders.CONFOUNDERS:
        _upsert(
            db,
            models.Confounder,
            entry.code,
            label=entry.label,
            affects=list(entry.affects),
            note=entry.note,
        )
    for entry in questions.QUESTIONS:
        _upsert(
            db,
            models.ClinicalQuestion,
            entry.code,
            prompt=entry.prompt,
            kind=entry.kind,
            group=entry.group,
            options=[{"value": value, "label": label} for value, label in entry.options],
            unit=entry.unit,
            minimum=entry.minimum,
            maximum=entry.maximum,
            help_text=entry.help_text,
            display_order=entry.order,
        )
    for entry in rules.RED_FLAGS:
        _upsert(
            db,
            models.ClinicalRule,
            entry.code,
            label=entry.label,
            severity=entry.severity,
            points=entry.points,
            advice=entry.advice,
        )
    for entry in causes.CAUSES:
        _upsert(
            db,
            models.PainCause,
            entry.code,
            label=entry.label,
            group=entry.group,
            pain_types=list(entry.pain_types),
            note=entry.note,
        )
    db.commit()
    return {
        "pain_locations": len(locations.LOCATIONS),
        "anatomical_regions": len(anatomy.REGIONS),
        "anatomical_structure_types": len(anatomy.STRUCTURE_TYPES),
        "anatomical_structures": len(anatomy.STRUCTURES),
        "anatomical_relationships": len(anatomy.RELATIONSHIPS),
        "medication_classes": len(medications.MEDICATION_CLASSES),
        "pain_qualities": len(qualities.QUALITIES),
        "pain_types": len(pain_types.PAIN_TYPES),
        "symptoms": len(symptoms.SYMPTOMS),
        "diseases": len(diseases.DISEASES),
        "pain_factors": len(factors.FACTORS),
        "confounders": len(confounders.CONFOUNDERS),
        "clinical_questions": len(questions.QUESTIONS),
        "clinical_rules": len(rules.RED_FLAGS),
        "pain_causes": len(causes.CAUSES),
    }
