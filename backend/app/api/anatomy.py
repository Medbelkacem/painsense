"""The anatomy ontology behind the 3D localisation module.

Served from the database rather than from the taxonomy module so a client can cache the
whole thing for the session, the same arrangement the rest of the catalogue uses. The
`sides` on each structure are computed from its laterality, so an interface does not have
to know that a liver has no left and a knee does.

The notice is served with the ontology on purpose. Whatever a client chooses to render, it
is given the sentence that says what the model is for.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api import schemas
from app.database.models import (
    AnatomicalRegion,
    AnatomicalStructure,
    AnatomicalStructureType,
)
from app.dependencies import CurrentUser, DbSession
from app.knowledge import anatomy

router = APIRouter(prefix="/api/anatomy", tags=["anatomy"])

NOTICE = (
    "The 3D model is a tool for recording where the pain is. It localises anatomy; it "
    "does not interpret it, and selecting a structure is not a statement that the "
    "structure is the cause."
)


def _structure_out(row: AnatomicalStructure) -> schemas.AnatomicalStructureOut:
    return schemas.AnatomicalStructureOut(
        code=row.code,
        label=row.label,
        latin=row.latin,
        structure_type=row.structure_type,
        region=row.region,
        location_code=row.location_code,
        location_left=row.location_left,
        location_right=row.location_right,
        laterality=row.laterality,
        sides=list(anatomy.SIDES_FOR_LATERALITY[row.laterality]),
        synonyms=list(row.synonyms or []),
        sex=row.sex,
        note=row.note,
    )


@router.get("", response_model=schemas.AnatomyOntology)
def ontology(db: DbSession, user: CurrentUser) -> schemas.AnatomyOntology:
    regions = db.scalars(select(AnatomicalRegion).order_by(AnatomicalRegion.display_order))
    types = db.scalars(
        select(AnatomicalStructureType).order_by(AnatomicalStructureType.display_order)
    )
    structures = db.scalars(
        select(AnatomicalStructure).order_by(
            AnatomicalStructure.region,
            AnatomicalStructure.structure_type,
            AnatomicalStructure.label,
        )
    )
    return schemas.AnatomyOntology(
        notice=NOTICE,
        regions=[schemas.AnatomicalRegionOut.model_validate(row) for row in regions],
        structure_types=[
            schemas.AnatomicalStructureTypeOut.model_validate(row) for row in types
        ],
        structures=[_structure_out(row) for row in structures],
        tree=[schemas.AnatomicalRegionGroup(**group) for group in anatomy.tree()],
    )
