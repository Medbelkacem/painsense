import pathlib
import re
import uuid

import numpy as np
import pytest

from app.ai import features, inputs
from app.database.models import AssessmentAnatomicalSite, PainAssessment
from app.knowledge import anatomy, locations
from app.knowledge.context import ClinicalContext
from tests.test_api import CHEST_CASE, make_assessment, make_patient

KNEE_CASE = {
    "anatomical_sites": [
        {"structure_code": "JOINT_KNEE", "side": "LEFT", "intensity": 7, "is_primary": True},
        {"structure_code": "TEN_KNEE_MENISCUS", "side": "LEFT", "intensity": 4},
    ]
}


# --- the ontology ------------------------------------------------------------------


def test_every_structure_resolves_through_the_three_levels():
    codes = [structure.code for structure in anatomy.STRUCTURES]
    assert len(codes) == len(set(codes))
    for structure in anatomy.STRUCTURES:
        assert structure.type in anatomy.TYPE_BY_CODE
        assert structure.laterality in anatomy.LATERALITIES
        assert structure.location in locations.BY_CODE
        assert structure.region in dict(anatomy.REGIONS)


def test_a_side_specific_location_belongs_only_to_a_paired_structure():
    for structure in anatomy.STRUCTURES:
        for sided in (structure.location_left, structure.location_right):
            if sided:
                assert sided in locations.BY_CODE
                assert structure.laterality == anatomy.PAIRED, structure.code


def test_the_tree_holds_every_structure_exactly_once():
    listed = [
        code
        for region in anatomy.tree()
        for group in region["types"]
        for code in group["structures"]
    ]
    assert sorted(listed) == sorted(structure.code for structure in anatomy.STRUCTURES)


def test_a_surface_zone_exists_for_every_site_a_record_can_name():
    """The fallback has to cover the taxonomy, or a site would have nowhere to be recorded.

    The parent codes are containers for their children and the sided chest codes are
    reached through the paired chest wall, so neither needs a zone of its own.
    """
    zones = {zone.location for zone in anatomy.of_type(anatomy.REGION)}
    zones.update(
        sided
        for zone in anatomy.of_type(anatomy.REGION)
        for sided in (zone.location_left, zone.location_right)
        if sided
    )
    containers = {"HEAD", "CHEST", "BACK", "ABDOMEN", "PELVIS"}
    structural = {structure.location for structure in anatomy.STRUCTURES}
    for code in locations.BY_CODE:
        if code in containers or locations.children(code):
            continue
        assert code in zones or code in structural, code


def test_a_structure_records_the_pain_location_it_projects_onto():
    assert anatomy.projected_locations("JOINT_KNEE", "LEFT") == (("KNEE", "LEFT"),)
    assert anatomy.projected_locations("ORG_LIVER", "RIGHT") == (("ABD_RUQ", "RIGHT"),)
    # The taxonomy names the two flanks separately, so both sides reach their own code.
    assert anatomy.projected_locations("ORG_KIDNEY", "BILATERAL") == (
        ("ABD_LUQ", "LEFT"),
        ("ABD_RUQ", "RIGHT"),
    )
    assert anatomy.projected_locations("NOT_A_STRUCTURE", "LEFT") == ()


def test_two_sites_on_one_location_combine_their_sides():
    assert anatomy.combine_sides("LEFT", "RIGHT") == "BILATERAL"
    assert anatomy.combine_sides("MIDLINE", "LEFT") == "LEFT"
    assert anatomy.combine_sides("LEFT", "LEFT") == "LEFT"
    assert anatomy.combine_sides("BILATERAL", "LEFT") == "BILATERAL"


def test_laterality_decides_which_sides_a_structure_accepts():
    assert anatomy.BY_CODE["JOINT_KNEE"].accepts("LEFT")
    assert not anatomy.BY_CODE["JOINT_KNEE"].accepts("MIDLINE")
    assert anatomy.BY_CODE["ORG_HEART"].accepts("MIDLINE")
    assert not anatomy.BY_CODE["ORG_HEART"].accepts("LEFT")
    # The liver is unpaired and on the right; it is not recordable on the left.
    assert anatomy.BY_CODE["ORG_LIVER"].accepts("RIGHT")
    assert not anatomy.BY_CODE["ORG_LIVER"].accepts("LEFT")


# --- the feature pipeline ----------------------------------------------------------


def test_the_structure_type_reaches_the_feature_vector():
    names = list(features.NAMES)
    without = features.vector(ClinicalContext(pain_locations=frozenset({"KNEE"})))
    with_nerve = features.vector(
        ClinicalContext(
            pain_locations=frozenset({"THIGH"}),
            anatomical_structures=frozenset({"NRV_SCIATIC"}),
        )
    )
    assert without[names.index("structure_localised")] == 0.0
    assert without[names.index("structure_nerve")] == 0.0
    assert with_nerve[names.index("structure_localised")] == 1.0
    assert with_nerve[names.index("structure_nerve")] == 1.0
    assert with_nerve[names.index("n_structures")] == 1.0


def test_a_surface_zone_is_a_site_but_not_localised_anatomy():
    names = list(features.NAMES)
    vector = features.vector(
        ClinicalContext(
            pain_locations=frozenset({"BACK_LUMBAR"}),
            anatomical_structures=frozenset({"REG_LOWER_BACK"}),
        )
    )
    assert vector[names.index("n_structures")] == 1.0
    assert vector[names.index("structure_localised")] == 0.0


def test_both_sides_are_visible_to_the_model_however_the_site_was_recorded():
    names = list(features.NAMES)
    one = ClinicalContext(pain_locations=frozenset({"KNEE"}), sides=frozenset({"LEFT"}))
    both = ClinicalContext(
        pain_locations=frozenset({"KNEE"}), sides=frozenset({"LEFT", "RIGHT"})
    )
    declared = ClinicalContext(
        pain_locations=frozenset({"KNEE"}), sides=frozenset({"BILATERAL"})
    )
    assert features.vector(one)[names.index("sites_bilateral")] == 0.0
    assert features.vector(both)[names.index("sites_bilateral")] == 1.0
    assert features.vector(declared)[names.index("sites_bilateral")] == 1.0


def test_no_feature_reads_a_per_site_intensity():
    """The counterpart of the self-report separation, for the intensity of each site.

    ClinicalContext has nowhere to put an intensity, so the assembled vector cannot depend
    on one however the sites were recorded.
    """
    assert not [name for name in features.NAMES if "intensity" in name]
    assert not hasattr(ClinicalContext(), "intensity")


# --- storage and the write path ----------------------------------------------------


def test_a_structure_selected_on_the_model_records_its_pain_location(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client, doctor_headers, patient["id"], locations=[], **KNEE_CASE
    )

    assert {site["structure_code"] for site in assessment["anatomical_sites"]} == {
        "JOINT_KNEE",
        "TEN_KNEE_MENISCUS",
    }
    # Nothing was ticked on the flat diagram, so the site came entirely from the model.
    assert assessment["locations"] == [{"code": "KNEE", "side": "LEFT", "is_primary": True}]
    primary = next(site for site in assessment["anatomical_sites"] if site["is_primary"])
    assert primary["structure_code"] == "JOINT_KNEE"
    assert primary["intensity"] == 7
    assert primary["label"] == "Knee joint"
    assert primary["latin"] == "Articulatio genus"
    assert primary["structure_type"] == "JOINT"


def test_identifiers_are_stored_rather_than_labels(client, doctor_headers, db):
    patient = make_patient(client, doctor_headers)
    make_assessment(client, doctor_headers, patient["id"], **KNEE_CASE)

    rows = db.query(AssessmentAnatomicalSite).all()
    assert {row.structure_code for row in rows} == {"JOINT_KNEE", "TEN_KNEE_MENISCUS"}
    assert all(row.side == "LEFT" for row in rows)
    assert sorted(row.intensity for row in rows) == [4.0, 7.0]


def test_a_site_and_a_hand_picked_location_can_disagree_about_the_side(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        locations=[{"code": "KNEE", "side": "RIGHT"}],
        anatomical_sites=[{"structure_code": "JOINT_KNEE", "side": "LEFT"}],
    )
    knee = next(row for row in assessment["locations"] if row["code"] == "KNEE")
    assert knee["side"] == "BILATERAL"


def test_a_structure_cannot_be_recorded_on_a_side_it_does_not_have(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={
            "patient_id": patient["id"],
            **CHEST_CASE,
            "anatomical_sites": [{"structure_code": "ORG_LIVER", "side": "LEFT"}],
        },
    )
    assert response.status_code == 422
    assert "Liver" in response.json()["detail"]


def test_an_unknown_structure_is_refused(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={
            "patient_id": patient["id"],
            **CHEST_CASE,
            "anatomical_sites": [{"structure_code": "ORG_SPLEEN_LEFT", "side": "LEFT"}],
        },
    )
    assert response.status_code == 422
    assert "ORG_SPLEEN_LEFT" in response.json()["detail"]


def test_removing_a_structure_takes_its_location_with_it(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        locations=[{"code": "BACK_LUMBAR", "side": "MIDLINE", "is_primary": True}],
        anatomical_sites=[{"structure_code": "JOINT_KNEE", "side": "LEFT"}],
    )
    assert {row["code"] for row in assessment["locations"]} == {"BACK_LUMBAR", "KNEE"}

    # Only the sites are sent. The lumbar pick was made by hand, so it stays; the knee
    # existed only because of the structure, so it goes with it.
    response = client.patch(
        f"/api/assessments/{assessment['id']}",
        headers=doctor_headers,
        json={"anatomical_sites": []},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["anatomical_sites"] == []
    assert {row["code"] for row in updated["locations"]} == {"BACK_LUMBAR"}


def test_the_same_structure_is_two_sites_when_both_sides_hurt(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        locations=[],
        anatomical_sites=[
            {"structure_code": "JOINT_KNEE", "side": "LEFT", "intensity": 8},
            {"structure_code": "JOINT_KNEE", "side": "RIGHT", "intensity": 3},
        ],
    )
    assert len(assessment["anatomical_sites"]) == 2
    assert next(row for row in assessment["locations"] if row["code"] == "KNEE")["side"] == (
        "BILATERAL"
    )


def test_the_estimate_sees_the_structures_and_not_their_intensities(client, doctor_headers, db):
    patient = make_patient(client, doctor_headers)
    created = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        anatomical_sites=[
            {
                "structure_code": "ORG_HEART",
                "side": "MIDLINE",
                "intensity": 9,
                "is_primary": True,
            }
        ],
    )
    assessment = db.get(PainAssessment, uuid.UUID(created["id"]))
    ctx = inputs.context_for(assessment)
    assert "ORG_HEART" in ctx.anatomical_structures
    assert ctx.structure_types == {"ORGAN"}
    before = features.vector(ctx)

    # Rewriting the intensity cannot move the vector, because nothing carries it across.
    response = client.patch(
        f"/api/assessments/{created['id']}",
        headers=doctor_headers,
        json={
            "anatomical_sites": [
                {
                    "structure_code": "ORG_HEART",
                    "side": "MIDLINE",
                    "intensity": 1,
                    "is_primary": True,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    reloaded = db.get(PainAssessment, uuid.UUID(created["id"]))
    after = features.vector(inputs.context_for(reloaded))
    assert np.array_equal(before, after, equal_nan=True)


# --- the 3D model against the ontology ---------------------------------------------

MODEL_SPEC = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "anatomy" / "model.ts"
)

# Sites a clinician records without pointing at anything: they are offered in the structure
# list and the model draws no geometry for them, which is the point of them.
WITHOUT_GEOMETRY = {
    "REG_CHEST_DIFFUSE",
    "REG_GENERALIZED",
    "REG_UNSPECIFIED",
    "ORG_PERITONEUM",
}


def _spec_codes() -> set[str]:
    return set(re.findall(r"code: '([A-Z][A-Z_]+)'", MODEL_SPEC.read_text()))


@pytest.mark.skipif(not MODEL_SPEC.exists(), reason="the frontend is not part of this checkout")
def test_the_3d_model_only_draws_structures_the_ontology_has():
    """Geometry that names a code the server would reject is geometry nobody can record."""
    unknown = sorted(_spec_codes() - set(anatomy.BY_CODE))
    assert unknown == []


@pytest.mark.skipif(not MODEL_SPEC.exists(), reason="the frontend is not part of this checkout")
def test_every_structure_is_drawn_unless_it_is_one_of_the_unlocalisable_ones():
    """The other direction: a new structure has to be given geometry or listed as having none.

    Otherwise it would quietly become selectable from the list and invisible on the model.
    """
    undrawn = set(anatomy.BY_CODE) - _spec_codes()
    assert undrawn == WITHOUT_GEOMETRY


# --- the catalogue endpoint --------------------------------------------------------


def test_the_ontology_is_served_as_regions_types_and_structures(client, doctor_headers):
    body = client.get("/api/anatomy", headers=doctor_headers).json()

    assert "does not interpret it" in body["notice"]
    assert [entry["code"] for entry in body["structure_types"]] == [
        entry.code for entry in anatomy.STRUCTURE_TYPES
    ]
    assert len(body["structures"]) == len(anatomy.STRUCTURES)

    knee = next(entry for entry in body["structures"] if entry["code"] == "JOINT_KNEE")
    assert knee["sides"] == ["LEFT", "RIGHT", "BILATERAL"]
    assert knee["location_code"] == "KNEE"
    assert knee["region"] == "LOWER_LIMB"

    heart = next(entry for entry in body["structures"] if entry["code"] == "ORG_HEART")
    assert heart["sides"] == ["MIDLINE"]

    uterus = next(entry for entry in body["structures"] if entry["code"] == "ORG_UTERUS")
    assert uterus["sex"] == "F"

    regions = {entry["region"] for entry in body["tree"]}
    assert {"HEAD", "CHEST", "ABDOMEN", "LOWER_LIMB"} <= regions


def test_the_ontology_needs_a_token(client):
    assert client.get("/api/anatomy").status_code == 401
