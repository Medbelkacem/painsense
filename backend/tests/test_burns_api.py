"""The burn API, and the separations it exists to hold.

The ones worth testing hardest are the boundaries: a model suggestion must not become an
assessment finding, a confirmed assessment must not change silently, and a clinician's
own surface area figure must not erase the computed one.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database.models import (
    Attribution,
    BurnAssessment,
    BurnDepth,
    BurnRegion,
    Patient,
    ReviewState,
)


def _utc(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


@pytest.fixture
def patient(db):
    """A synthetic patient, flagged as such. Born four years ago, so the Lund-Browder
    column in play is young_child and not the adult one."""
    from datetime import date

    today = datetime.now(timezone.utc).date()
    row = Patient(
        code=f"BURN-{uuid.uuid4().hex[:8]}",
        birth_date=date(today.year - 4, today.month, 1),
        is_synthetic=True,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def incident(client, admin_headers, patient):
    response = client.post(
        "/api/burns/incidents",
        headers=admin_headers,
        json={
            "patient_id": str(patient.id),
            "occurred_at": _utc(hours=3),
            "cause": "SCALD",
            "enclosed_space": False,
            "symptoms": ["blistering"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def assessment(client, admin_headers, incident):
    response = client.post(
        f"/api/burns/incidents/{incident['id']}/assessments", headers=admin_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- reference data -------------------------------------------------------------------


def test_reference_serves_the_charts_so_a_client_need_not_hard_code_them(
    client, doctor_headers
):
    body = client.get("/api/burns/reference", headers=doctor_headers).json()

    assert len(body["depths"]) == 5
    assert len(body["regions"]) == 19
    head = next(row for row in body["regions"] if row["code"] == "HEAD")
    assert head["share_by_band"]["infant"] == 19.0
    assert head["share_by_band"]["adult"] == 7.0
    assert head["high_risk"] is True
    assert body["palm_percent"] == 1.0


def test_reference_marks_which_depths_count_towards_the_total(client, doctor_headers):
    body = client.get("/api/burns/reference", headers=doctor_headers).json()
    superficial = next(
        row for row in body["depths"] if row["code"] == "SUPERFICIAL_EPIDERMAL"
    )
    assert superficial["counts_towards_tbsa"] is False
    assert superficial["legacy_label"] == "First degree"


def test_reference_needs_a_signed_in_user(client):
    assert client.get("/api/burns/reference").status_code == 401


# --- incidents -------------------------------------------------------------------------


def test_an_incident_in_the_future_is_refused(client, admin_headers, patient):
    response = client.post(
        "/api/burns/incidents",
        headers=admin_headers,
        json={
            "patient_id": str(patient.id),
            "occurred_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "cause": "FLAME",
        },
    )
    assert response.status_code == 422


def test_an_unknown_cause_is_refused(client, admin_headers, patient):
    response = client.post(
        "/api/burns/incidents",
        headers=admin_headers,
        json={
            "patient_id": str(patient.id),
            "occurred_at": _utc(hours=1),
            "cause": "DRAGON",
        },
    )
    assert response.status_code == 422


def test_an_incident_reports_how_long_ago_it_happened(client, admin_headers, incident):
    body = client.get(
        f"/api/burns/incidents/{incident['id']}", headers=admin_headers
    ).json()
    assert 2.5 <= body["incident"]["hours_since"] <= 3.5


# --- regions and surface area --------------------------------------------------------------


def test_adding_a_region_costs_it_against_the_patients_own_age_band(
    client, admin_headers, assessment
):
    body = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HEAD", "depth": "DEEP_PARTIAL"},
    ).json()

    assert body["latest_tbsa"]["age_band"] == "young_child"
    # A four-year-old's head is 17% of the body surface, not an adult's 7%.
    assert body["latest_tbsa"]["total_percent"] == 17.0


def test_the_breakdown_shows_its_working(client, admin_headers, assessment):
    body = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "DEEP_PARTIAL", "fraction": 0.5},
    ).json()

    line = body["latest_tbsa"]["breakdown"][0]
    assert line["region_percent_of_body"] == 3.0
    assert line["fraction_of_region"] == 0.5
    assert line["contribution_percent"] == 1.5
    assert body["latest_tbsa"]["formula"]


def test_the_rule_of_nines_is_refused_for_this_child(client, admin_headers, assessment):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HEAD", "depth": "DEEP_PARTIAL"},
    )
    response = client.post(
        f"/api/burns/assessments/{assessment['id']}/tbsa",
        headers=admin_headers,
        json={"method": "RULE_OF_NINES"},
    )
    assert response.status_code == 422
    assert "Lund-Browder" in response.json()["detail"]


def test_comparing_methods_returns_the_refusal_rather_than_failing(
    client, admin_headers, assessment
):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HEAD", "depth": "DEEP_PARTIAL"},
    )
    body = client.get(
        f"/api/burns/assessments/{assessment['id']}/tbsa/compare", headers=admin_headers
    ).json()
    assert isinstance(body["LUND_BROWDER"], dict)
    assert isinstance(body["RULE_OF_NINES"], str)


def test_removing_a_region_recalculates(client, admin_headers, assessment):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HEAD", "depth": "DEEP_PARTIAL"},
    )
    body = client.delete(
        f"/api/burns/assessments/{assessment['id']}/regions/HEAD", headers=admin_headers
    ).json()
    assert body["regions"] == []
    assert body["latest_tbsa"]["total_percent"] == 0.0


def test_an_unknown_region_code_is_refused(client, admin_headers, assessment):
    response = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "LEFT_WING", "depth": "DEEP_PARTIAL"},
    )
    assert response.status_code == 422


def test_a_clinician_figure_sits_beside_the_computed_one(client, admin_headers, assessment):
    body = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HEAD", "depth": "DEEP_PARTIAL"},
    ).json()
    calculation_id = body["latest_tbsa"]["id"]

    overridden = client.post(
        f"/api/burns/tbsa/{calculation_id}/override",
        headers=admin_headers,
        json={"percent": 12.0, "note": "charted at the bedside against the child's palm"},
    ).json()

    assert overridden["total_percent"] == 17.0, "the computed figure must survive"
    assert overridden["clinician_percent"] == 12.0
    assert overridden["effective_percent"] == 12.0


# --- the model boundary ------------------------------------------------------------------------


def test_a_model_suggestion_does_not_become_the_assessment(client, db, admin_headers, assessment):
    """The separation the whole module rests on."""
    from backend.burns import service

    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "UNCERTAIN"},
    )
    region = db.scalar(
        select(BurnRegion).where(BurnRegion.assessment_id == uuid.UUID(assessment["id"]))
    )
    service.suggest_depth(db, region, depth=BurnDepth.FULL_THICKNESS, confidence=0.93)
    db.commit()

    body = client.get(
        f"/api/burns/assessments/{assessment['id']}", headers=admin_headers
    ).json()
    recorded = body["regions"][0]
    assert recorded["suggested_depth"] == "FULL_THICKNESS"
    assert recorded["depth"] == "UNCERTAIN", "a suggestion must not be adopted"
    assert recorded["confirmed_at"] is None


def test_confirming_a_depth_records_who_decided_and_what_the_model_had_said(
    client, db, admin_headers, assessment
):
    from backend.burns import service

    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "UNCERTAIN"},
    )
    region = db.scalar(
        select(BurnRegion).where(BurnRegion.assessment_id == uuid.UUID(assessment["id"]))
    )
    service.suggest_depth(db, region, depth=BurnDepth.FULL_THICKNESS, confidence=0.93)
    db.commit()

    body = client.post(
        f"/api/burns/assessments/{assessment['id']}/regions/FOREARM_LEFT/confirm-depth",
        headers=admin_headers,
        json={"depth": "DEEP_PARTIAL"},
    ).json()

    recorded = body["regions"][0]
    assert recorded["depth"] == "DEEP_PARTIAL"
    assert recorded["depth_attribution"] == Attribution.CLINICIAN.value
    assert recorded["confirmed_by"] is not None
    assert recorded["suggested_depth"] == "FULL_THICKNESS", "the suggestion stays on file"


def test_disagreement_with_the_model_reaches_the_audit_trail(
    client, db, admin_headers, assessment
):
    from backend.burns import service
    from database.models import AuditLog

    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "UNCERTAIN"},
    )
    region = db.scalar(
        select(BurnRegion).where(BurnRegion.assessment_id == uuid.UUID(assessment["id"]))
    )
    service.suggest_depth(db, region, depth=BurnDepth.FULL_THICKNESS, confidence=0.9)
    db.commit()

    client.post(
        f"/api/burns/assessments/{assessment['id']}/regions/FOREARM_LEFT/confirm-depth",
        headers=admin_headers,
        json={"depth": "SUPERFICIAL_PARTIAL"},
    )
    entry = db.scalar(
        select(AuditLog)
        .where(AuditLog.resource == "burn_region")
        .order_by(AuditLog.timestamp.desc())
    )
    assert entry.meta["model_suggested"] == "FULL_THICKNESS"
    assert entry.meta["confirmed_depth"] == "SUPERFICIAL_PARTIAL"
    assert entry.meta["agreed_with_model"] is False


# --- review lifecycle -----------------------------------------------------------------------------


def test_an_empty_assessment_cannot_be_submitted(client, admin_headers, assessment):
    response = client.post(
        f"/api/burns/assessments/{assessment['id']}/submit", headers=admin_headers
    )
    assert response.status_code == 422


def test_an_assessment_with_an_undecided_depth_cannot_be_confirmed(
    client, admin_headers, assessment
):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "UNCERTAIN"},
    )
    client.post(f"/api/burns/assessments/{assessment['id']}/submit", headers=admin_headers)
    response = client.post(
        f"/api/burns/assessments/{assessment['id']}/confirm", headers=admin_headers, json={}
    )
    assert response.status_code == 422
    assert "FOREARM_LEFT" in response.json()["detail"]


def test_a_confirmed_assessment_will_not_take_a_silent_change(
    client, admin_headers, assessment
):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "DEEP_PARTIAL"},
    )
    client.post(f"/api/burns/assessments/{assessment['id']}/submit", headers=admin_headers)
    confirmed = client.post(
        f"/api/burns/assessments/{assessment['id']}/confirm",
        headers=admin_headers,
        json={"note": "reviewed at the bedside"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == ReviewState.CONFIRMED.value

    blocked = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HAND_LEFT", "depth": "DEEP_PARTIAL"},
    )
    assert blocked.status_code == 409


def test_amending_reopens_a_confirmed_assessment_and_records_why(
    client, db, admin_headers, assessment
):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "DEEP_PARTIAL"},
    )
    client.post(f"/api/burns/assessments/{assessment['id']}/submit", headers=admin_headers)
    client.post(
        f"/api/burns/assessments/{assessment['id']}/confirm", headers=admin_headers, json={}
    )
    amended = client.post(
        f"/api/burns/assessments/{assessment['id']}/amend",
        headers=admin_headers,
        json={"note": "deeper than first thought at the second dressing"},
    ).json()

    assert amended["state"] == ReviewState.AMENDED.value
    assert "deeper" in amended["review_note"]
    row = db.get(BurnAssessment, uuid.UUID(assessment["id"]))
    assert row.reviewed_by is not None


# --- alerts ----------------------------------------------------------------------------------------


def test_a_high_risk_site_raises_an_alert_on_the_assessment(client, admin_headers, assessment):
    body = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HAND_LEFT", "depth": "DEEP_PARTIAL", "fraction": 0.2},
    ).json()
    codes = {alert["code"] for alert in body["alerts"]}
    assert "HIGH_RISK_SITE" in codes


def test_an_alert_clears_when_its_finding_goes(client, admin_headers, assessment):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HAND_LEFT", "depth": "DEEP_PARTIAL"},
    )
    body = client.delete(
        f"/api/burns/assessments/{assessment['id']}/regions/HAND_LEFT", headers=admin_headers
    ).json()
    assert "HIGH_RISK_SITE" not in {alert["code"] for alert in body["alerts"]}


def test_an_acknowledged_alert_survives_recalculation(client, admin_headers, assessment):
    body = client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "HAND_LEFT", "depth": "DEEP_PARTIAL"},
    ).json()
    alert_id = next(a["id"] for a in body["alerts"] if a["code"] == "HIGH_RISK_SITE")
    acknowledged = client.post(
        f"/api/burns/alerts/{alert_id}/acknowledge", headers=admin_headers
    ).json()
    assert acknowledged["acknowledged_at"] is not None

    after = client.delete(
        f"/api/burns/assessments/{assessment['id']}/regions/HAND_LEFT", headers=admin_headers
    ).json()
    assert alert_id in {a["id"] for a in after["alerts"]}


# --- pain ---------------------------------------------------------------------------------------------


def test_pain_can_be_recorded_separately_for_rest_movement_and_care(
    client, admin_headers, patient, incident
):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={
            "incident_id": incident["id"],
            "at_rest_nrs": 3,
            "on_movement_nrs": 7,
            "during_care_nrs": 9,
            "qualities": ["burning", "stinging"],
            "disturbs_sleep": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["at_rest_nrs"] == 3
    assert body["during_care_nrs"] == 9
    assert body["attribution"] == Attribution.PATIENT.value


def test_a_pain_report_with_no_score_at_all_is_refused(client, admin_headers, patient):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"qualities": ["burning"]},
    )
    assert response.status_code == 422


def test_a_score_outside_zero_to_ten_is_refused(client, admin_headers, patient):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"current_nrs": 11},
    )
    assert response.status_code == 422


def test_a_self_report_scale_cannot_be_recorded_as_an_observation(
    client, admin_headers, patient
):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"current_nrs": 5, "scale_code": "NRS", "observed": True},
    )
    assert response.status_code == 422


def test_an_observational_scale_is_attributed_to_the_clinician(
    client, admin_headers, patient
):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"current_nrs": 4, "scale_code": "FLACC", "observed": True},
    )
    assert response.status_code == 201, response.text
    assert response.json()["attribution"] == Attribution.CLINICIAN.value


def test_an_unknown_scale_is_refused(client, admin_headers, patient):
    response = client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"current_nrs": 5, "scale_code": "MADEUP"},
    )
    assert response.status_code == 422


# --- wound care, follow-up and the timeline -----------------------------------------------------------------


def test_wound_care_is_recorded_as_entered(client, admin_headers, incident):
    response = client.post(
        "/api/burns/wound-care",
        headers=admin_headers,
        json={
            "incident_id": incident["id"],
            "region_codes": ["FOREARM_LEFT"],
            "cleaning": "irrigated with warmed saline",
            "dressing": "silicone contact layer",
            "tolerance": "tolerated well",
            "next_review_on": "2026-10-08",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["dressing"] == "silicone contact layer"


def test_the_timeline_gathers_everything_in_time_order(
    client, admin_headers, patient, incident, assessment
):
    client.put(
        f"/api/burns/assessments/{assessment['id']}/regions",
        headers=admin_headers,
        json={"region_code": "FOREARM_LEFT", "depth": "DEEP_PARTIAL"},
    )
    client.post(
        "/api/burns/pain",
        headers=admin_headers,
        params={"patient_id": str(patient.id)},
        json={"incident_id": incident["id"], "current_nrs": 6},
    )
    client.post(
        "/api/burns/wound-care",
        headers=admin_headers,
        json={"incident_id": incident["id"], "cleaning": "saline"},
    )
    client.post(
        "/api/burns/follow-ups",
        headers=admin_headers,
        json={"incident_id": incident["id"], "scheduled_for": "2026-10-08"},
    )

    body = client.get(
        f"/api/burns/incidents/{incident['id']}", headers=admin_headers
    ).json()
    assert len(body["assessments"]) == 1
    assert len(body["pain_reports"]) == 1
    assert len(body["care_events"]) == 1
    assert len(body["follow_ups"]) == 1
    assert body["notice"]


# --- access control ---------------------------------------------------------------------------------------


def test_the_burn_api_needs_a_clinical_account(client, patient):
    assert client.get("/api/burns/incidents").status_code == 401
    assert (
        client.post(
            "/api/burns/incidents",
            json={
                "patient_id": str(patient.id),
                "occurred_at": _utc(hours=1),
                "cause": "FLAME",
            },
        ).status_code
        == 401
    )


def test_consent_is_recorded_and_withdrawal_keeps_the_row(client, admin_headers, patient):
    granted = client.put(
        f"/api/burns/patients/{patient.id}/consents",
        headers=admin_headers,
        json={"scope": "WOUND_PHOTOGRAPHY", "granted": True},
    ).json()
    assert granted["active"] is True

    withdrawn = client.put(
        f"/api/burns/patients/{patient.id}/consents",
        headers=admin_headers,
        json={"scope": "WOUND_PHOTOGRAPHY", "granted": False},
    ).json()
    assert withdrawn["active"] is False
    assert withdrawn["granted_at"] is not None, "the record that it was once granted stays"
    assert withdrawn["withdrawn_at"] is not None


def test_the_dashboard_carries_no_patient_identifying_content(client, admin_headers, incident):
    body = client.get("/api/burns/dashboard", headers=admin_headers).json()
    assert body["incidents"] >= 1
    assert all(not key.startswith("patient_") for key in body)
