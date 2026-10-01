from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from backend.api import schemas
from database.models import (
    AnatomicalRegion,
    AnatomicalStructure,
    AnatomicalStructureType,
)
from backend.dependencies import CurrentUser, DbSession
from knowledge import anatomy

router = APIRouter(prefix="/api/anatomy", tags=["anatomy"])

NOTICE = (
    "The 3D model is a tool for recording where the pain is. It localises anatomy; it "
    "does not interpret it, and selecting a structure is not a statement that the "
    "structure is the cause."
)

TYPE_ROUTES = {
    "regions": anatomy.REGION,
    "muscles": anatomy.MUSCLE,
    "tendons": anatomy.TENDON,
    "ligaments": anatomy.LIGAMENT,
    "bones": anatomy.BONE,
    "joints": anatomy.JOINT,
    "organs": anatomy.ORGAN,
    "nerves": anatomy.NERVE,
    "vessels": anatomy.VESSEL,
}


def _structure_out(structure: anatomy.Structure) -> schemas.AnatomicalStructureOut:
    return schemas.AnatomicalStructureOut(
        code=structure.code,
        label=structure.label,
        latin=structure.latin,
        structure_type=structure.type,
        region=structure.region,
        location_code=structure.location,
        location_left=structure.location_left or None,
        location_right=structure.location_right or None,
        laterality=structure.laterality,
        sides=list(anatomy.SIDES_FOR_LATERALITY[structure.laterality]),
        synonyms=list(structure.synonyms),
        sex=structure.sex,
        parent_code=structure.parent,
        subregion=anatomy.subregion_of(structure.code),
        system=structure.system_code,
        has_mesh=structure.has_mesh,
        pain_selectable=structure.pain_selectable,
        description=structure.description,
        note=structure.note,
    )


def _hit(structure: anatomy.Structure) -> schemas.AnatomySearchHit:
    return schemas.AnatomySearchHit(
        code=structure.code,
        label=structure.label,
        latin=structure.latin,
        structure_type=structure.type,
        region=structure.region,
        subregion=anatomy.subregion_of(structure.code),
        sides=list(anatomy.SIDES_FOR_LATERALITY[structure.laterality]),
        breadcrumb=[label for _, label in anatomy.breadcrumb(structure.code)],
    )


@router.get("", response_model=schemas.AnatomyOntology)
def ontology(db: DbSession, user: CurrentUser) -> schemas.AnatomyOntology:
    regions = db.scalars(select(AnatomicalRegion).order_by(AnatomicalRegion.display_order))
    types = db.scalars(
        select(AnatomicalStructureType).order_by(AnatomicalStructureType.display_order)
    )

    codes = set(db.scalars(select(AnatomicalStructure.code)))
    structures = sorted(
        (anatomy.BY_CODE[code] for code in codes if code in anatomy.BY_CODE),
        key=lambda item: (item.region, item.type, item.label),
    )
    return schemas.AnatomyOntology(
        notice=NOTICE,
        regions=[schemas.AnatomicalRegionOut.model_validate(row) for row in regions],
        structure_types=[
            schemas.AnatomicalStructureTypeOut.model_validate(row) for row in types
        ],
        systems=[{"code": code, "label": label} for code, label in anatomy.SYSTEMS],
        structures=[_structure_out(item) for item in structures],
        tree=[schemas.AnatomicalRegionGroup(**group) for group in anatomy.tree()],
        counts=anatomy.counts(),
    )


@router.get("/search", response_model=list[schemas.AnatomySearchHit])
def search(
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    sex: Annotated[str | None, Query(max_length=1)] = None,
) -> list[schemas.AnatomySearchHit]:
    return [_hit(item) for item in anatomy.search(q, limit=limit, sex=sex)]


@router.get("/structures/{code}", response_model=schemas.AnatomicalStructureDetail)
def structure_detail(code: str, user: CurrentUser) -> schemas.AnatomicalStructureDetail:
    structure = anatomy.BY_CODE.get(code.upper())
    if structure is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Structure not found")
    related = []
    for relation, other in anatomy.related(structure.code):
        target = anatomy.BY_CODE.get(other)
        if target is None:
            continue
        related.append(
            schemas.AnatomicalRelationOut(
                relation=relation,
                code=target.code,
                label=target.label,
                structure_type=target.type,
            )
        )
    return schemas.AnatomicalStructureDetail(
        **_structure_out(structure).model_dump(),
        breadcrumb=[{"code": c, "label": lbl} for c, lbl in anatomy.breadcrumb(structure.code)],
        related=related,
        children=[child.code for child in anatomy.children(structure.code)],
    )


def _by_type(type_code: str):
    def handler(user: CurrentUser) -> list[schemas.AnatomicalStructureOut]:
        return [_structure_out(item) for item in anatomy.of_type(type_code)]

    return handler


for _route, _type in TYPE_ROUTES.items():
    router.add_api_route(
        f"/{_route}",
        _by_type(_type),
        methods=["GET"],
        response_model=list[schemas.AnatomicalStructureOut],
        name=f"anatomy_{_route}",
    )
