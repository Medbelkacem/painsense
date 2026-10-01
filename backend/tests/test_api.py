from security import pqc
from backend.tests.conftest import DOCTOR_EMAIL, PASSWORD

CHEST_CASE = {
    "onset": "SUDDEN",
    "onset_speed": "MINUTES",
    "duration_hours": 3.0,
    "pattern": "INTERMITTENT",
    "course": "WORSENING",
    "radiates": True,
    "radiation_description": "To the left arm and jaw.",
    "locations": [{"code": "CHEST_CENTRAL", "is_primary": True}],
    "quality_codes": ["PRESSURE", "TIGHTNESS"],
    "symptom_codes": ["SWEATING", "DYSPNOEA", "NAUSEA"],
    "factor_codes": ["EXERCISE", "REST"],
    "confounder_codes": ["ANXIETY"],
    "functional_impact": {
        "mobility": 3,
        "sleep": 3,
        "work": 4,
        "daily_activity": 3,
        "self_care": 2,
    },
    "medications": [
        {
            "class_code": "ACETAMINOPHEN",
            "name": "Paracetamol",
            "dose_category": "STANDARD",
            "frequency": "AS_NEEDED",
            "hours_since_last_dose": 5.0,
            "pain_effect": "PARTIAL",
            "sedation_effect": "NONE",
        }
    ],
    "answers": {
        "FIRST_EPISODE": True,
        "REGULAR_MEDICATION": True,
        "CHEST_EXERTIONAL": True,
        "CHEST_RELIEVED_BY_REST": True,
        "ECG_RESULT": "ABNORMAL",
    },
    "measurement": {
        "hr": 112,
        "resp_rate": 22,
        "sbp": 156,
        "dbp": 92,
        "spo2": 94,
        "temperature_c": 37.1,
        "weight_kg": 82,
        "height_cm": 176,
    },
    "self_report": {"nrs": 4, "note": "Describes pressure rather than pain."},
}


def make_patient(client, headers, **overrides):
    payload = {
        "identity": {
            "given_name": "Amel",
            "family_name": "Cherif",
            "phone": "+213 555 01 02 03",
        },
        "sex": "F",
        "birth_date": "1968-04-12",
        "ward": "Cardiology",
        "smoking_status": "FORMER",
        "condition_codes": ["HYPERTENSION", "DIABETES_T2"],
        "medications": [{"name": "Metformin", "dose": "1000 mg", "frequency": "twice daily"}],
    }
    payload.update(overrides)
    response = client.post("/api/patients", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_assessment(client, headers, patient_id, **overrides):
    payload = {"patient_id": patient_id, **CHEST_CASE, **overrides}
    response = client.post("/api/assessments", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_is_open_and_carries_the_disclaimer(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "does not constitute a medical diagnosis" in body["disclaimer"]


def test_clinical_endpoints_need_a_token(client):
    assert client.get("/api/patients").status_code == 401
    assert client.get("/api/analytics").status_code == 401


def test_a_wrong_password_says_nothing_about_the_account(client):
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@chu-batna.dz", "password": "x" * 14}
    )
    wrong = client.post("/api/auth/login", json={"email": DOCTOR_EMAIL, "password": "x" * 14})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_login_sets_an_http_only_refresh_cookie(client):
    response = client.post(
        "/api/auth/login", json={"email": DOCTOR_EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    header = " ".join(response.headers.get_list("set-cookie"))
    assert "painscore_refresh" in header and "HttpOnly" in header


def test_refresh_requires_the_csrf_header(client):
    body = client.post(
        "/api/auth/login", json={"email": DOCTOR_EMAIL, "password": PASSWORD}
    ).json()
    assert client.post("/api/auth/refresh").status_code == 403
    assert (
        client.post(
            "/api/auth/refresh", headers={"X-CSRF-Token": body["csrf_token"]}
        ).status_code
        == 200
    )


def test_responses_carry_the_security_headers(client):
    headers = client.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_patient_codes_are_issued_in_sequence(client, doctor_headers):
    first = make_patient(client, doctor_headers)
    second = make_patient(client, doctor_headers)
    assert first["code"].startswith("PS-")
    assert int(second["code"].split("-")[-1]) == int(first["code"].split("-")[-1]) + 1


def test_the_stored_patient_row_does_not_hold_the_name(client, doctor_headers, db):
    from database.models import Patient

    created = make_patient(client, doctor_headers)
    row = db.get(Patient, __import__("uuid").UUID(created["id"]))
    assert b"Cherif" not in (row.identity_blob or b"")
    assert created["display_name"] == "Amel Cherif"


def test_a_patient_can_be_found_by_code_and_by_name(client, doctor_headers):
    created = make_patient(client, doctor_headers)
    by_code = client.get(
        f"/api/patients?search={created['code']}", headers=doctor_headers
    ).json()
    by_name = client.get("/api/patients?search=cherif", headers=doctor_headers).json()
    assert created["code"] in [item["code"] for item in by_code["items"]]
    assert created["code"] in [item["code"] for item in by_name["items"]]


def test_an_unknown_condition_code_is_refused(client, doctor_headers):
    response = client.post(
        "/api/patients",
        headers=doctor_headers,
        json={
            "identity": {"given_name": "Amel", "family_name": "Cherif"},
            "condition_codes": ["NOT_A_REAL_CODE"],
        },
    )
    assert response.status_code == 422
    assert "NOT_A_REAL_CODE" in response.json()["detail"]


def test_an_archived_patient_takes_no_new_assessment(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    client.post(f"/api/patients/{patient['id']}/archive", headers=doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={"patient_id": patient["id"], **CHEST_CASE},
    )
    assert response.status_code == 409


def test_the_question_set_narrows_to_the_case(client, doctor_headers):
    chest = client.post(
        "/api/clinical-questions/applicable",
        headers=doctor_headers,
        json={"age": 58, "sex": "M", "locations": ["CHEST_CENTRAL"], "radiates": True},
    ).json()
    back = client.post(
        "/api/clinical-questions/applicable",
        headers=doctor_headers,
        json={"age": 58, "sex": "M", "locations": ["BACK_LUMBAR"]},
    ).json()
    codes = {q["code"] for q in chest}
    assert "CHEST_EXERTIONAL" in codes
    assert "BACK_STRAIGHT_LEG_RAISE" not in codes
    assert "BACK_STRAIGHT_LEG_RAISE" in {q["code"] for q in back}
    assert len(client.get("/api/clinical-questions", headers=doctor_headers).json()) > len(
        chest
    )


def test_an_impossible_measurement_is_refused_with_a_message(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={"patient_id": patient["id"], **CHEST_CASE, "measurement": {"hr": 480}},
    )
    assert response.status_code == 422
    assert "less than or equal to 300" in str(response.json()["detail"])


def test_an_abnormal_but_possible_measurement_is_stored_as_entered(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client, doctor_headers, patient["id"], measurement={"hr": 148, "spo2": 91}
    )
    assert assessment["measurement"]["hr"] == 148
    assert assessment["measurement"]["spo2"] == 91


def test_the_full_workflow_produces_an_explained_estimate(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    assert assessment["status"] == "DRAFT"
    assert assessment["measurement"]["bmi"] == 26.5

    estimated = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()
    prediction = estimated["prediction"]
    assert estimated["status"] == "ESTIMATED"
    assert not prediction["refused"]
    assert 0 <= prediction["estimated_pain"] <= 10
    assert (
        prediction["interval_low"]
        <= prediction["estimated_pain"]
        <= prediction["interval_high"]
    )
    assert prediction["contributions"]
    assert prediction["categories"]
    assert prediction["priority_score"] is not None
    assert prediction["model_version"]

    validated = client.post(
        f"/api/assessments/{assessment['id']}/validate", headers=doctor_headers
    ).json()
    assert validated["status"] == "VALIDATED"
    assert validated["validated_at"]


def test_the_self_reported_score_is_kept_beside_the_estimate(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    estimated = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()
    assert estimated["self_report"] == 4
    assert estimated["prediction"]["estimated_pain"] != estimated["self_report"]
    assert "self_report" not in estimated["prediction"]["features"]


def test_a_validated_assessment_cannot_be_edited(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)
    client.post(f"/api/assessments/{assessment['id']}/validate", headers=doctor_headers)
    response = client.patch(
        f"/api/assessments/{assessment['id']}",
        headers=doctor_headers,
        json={"night_pain": True},
    )
    assert response.status_code == 409


def test_validation_needs_an_estimate_first(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    assert (
        client.post(
            f"/api/assessments/{assessment['id']}/validate", headers=doctor_headers
        ).status_code
        == 409
    )


def test_a_thin_record_is_refused_rather_than_guessed(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={"patient_id": patient["id"], "locations": [{"code": "KNEE"}]},
    )
    assessment = response.json()
    estimated = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()
    assert estimated["status"] == "DRAFT"
    assert estimated["prediction"]["refused"]
    assert estimated["prediction"]["estimated_pain"] is None
    assert estimated["prediction"]["missing_fields"]


def test_history_and_trend_follow_the_assessments(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    for _ in range(2):
        assessment = make_assessment(client, doctor_headers, patient["id"])
        client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)

    history = client.get(
        f"/api/patients/{patient['id']}/history", headers=doctor_headers
    ).json()
    assert len(history["points"]) == 2
    assert history["trend"] in ("RISING", "FALLING", "STABLE")


def test_two_assessments_can_be_compared(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    first = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{first['id']}/predict", headers=doctor_headers)
    second = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        symptom_codes=["SWEATING", "FEVER"],
        measurement={"hr": 90, "spo2": 98},
    )
    client.post(f"/api/assessments/{second['id']}/predict", headers=doctor_headers)

    comparison = client.get(
        f"/api/assessments/{second['id']}/compare/{first['id']}", headers=doctor_headers
    ).json()
    assert comparison["previous_id"] == first["id"]
    assert "Fever" in comparison["symptoms_added"]
    assert any(field["field"] == "estimated_pain" for field in comparison["fields"])


def test_a_report_is_produced_as_a_pdf(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)

    response = client.post(f"/api/reports/{assessment['id']}/generate", headers=doctor_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 3000


def test_the_dashboard_counts_what_was_recorded(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)

    analytics = client.get("/api/analytics", headers=doctor_headers).json()
    assert analytics["patients_total"] >= 1
    assert analytics["assessments_total"] >= 1
    assert analytics["recent_assessments"]


def test_integrity_reports_both_chains(client, doctor_headers):
    make_patient(client, doctor_headers)
    status = client.post("/api/integrity/verify", headers=doctor_headers).json()
    assert status["ledger_valid"]
    assert status["audit_valid"]
    assert status["blocks"] >= 1
    assert status["problems"] == []
    assert "ML-DSA" in status["signature_scheme"]


def test_the_security_page_probes_the_primitives(client, admin_headers):
    body = client.get("/api/security", headers=admin_headers).json()
    named = {entry["name"]: entry["status"] for entry in body["algorithms"]}
    assert named["AES-256-GCM"] == "ACTIVE"
    assert named[pqc.kem_scheme()] == "ACTIVE"
    assert named[pqc.sign_scheme()] == "ACTIVE"
    assert named["TLS"] == "DEPLOYMENT"
    assert body["keys"]


def test_the_model_page_reports_measured_metrics(client, admin_headers):
    body = client.get("/api/model", headers=admin_headers).json()
    assert body["trained"]
    assert 0 <= body["active"]["mae"] <= 10
    assert body["active"]["n_test"] > 0
    assert body["feature_count"] == len(body["active"]["features"])
    assert any("synthetic" in limitation.lower() for limitation in body["limitations"])


def test_training_and_dataset_generation_are_restricted_to_administrators(
    client, doctor_headers
):
    assert client.post("/api/model/train", headers=doctor_headers, json={}).status_code == 403
    assert (
        client.post("/api/datasets/generate", headers=doctor_headers, json={}).status_code
        == 403
    )


def test_a_doctor_sees_only_their_own_audit_entries(client, doctor_headers, admin_headers):
    make_patient(client, doctor_headers)
    mine = client.get("/api/audit", headers=doctor_headers).json()
    everything = client.get("/api/audit", headers=admin_headers).json()
    assert mine["total"] >= 1
    assert everything["total"] >= mine["total"]
    assert {entry["actor_label"] for entry in mine["items"]} == {DOCTOR_EMAIL}


def test_repeated_failed_logins_are_rate_limited(client):
    statuses = [
        client.post(
            "/api/auth/login", json={"email": DOCTOR_EMAIL, "password": "x" * 14}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in statuses


def test_successful_sign_ins_are_not_rate_limited(client):
    statuses = [
        client.post(
            "/api/auth/login", json={"email": DOCTOR_EMAIL, "password": PASSWORD}
        ).status_code
        for _ in range(15)
    ]
    assert set(statuses) == {200}


REGISTRATION = {
    "email": "n.haddad@clinique-ennour.dz",
    "password": "Consultation-Ennour-2026",
    "display_name": "Dr N. Haddad",
    "clinic_name": "Clinique Ennour",
    "phone": "+213 661 22 08 41",
    "profession": "DOCTOR",
    "speciality": "Rheumatology",
}


def test_a_clinician_can_create_their_own_account(client):
    response = client.post("/api/auth/register", json=REGISTRATION)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["clinic_name"] == "Clinique Ennour"
    assert body["user"]["profession"] == "DOCTOR"
    assert body["access_token"]


def test_registration_never_grants_administrator_rights(client):
    body = client.post("/api/auth/register", json={**REGISTRATION, "role": "ADMIN"}).json()
    assert body["user"]["role"] == "DOCTOR"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.post("/api/model/train", headers=headers, json={}).status_code == 403


def test_a_doctor_must_give_a_speciality(client):
    response = client.post("/api/auth/register", json={**REGISTRATION, "speciality": None})
    assert response.status_code == 422
    assert "speciality" in str(response.json()["detail"])


def test_a_nurse_needs_no_speciality(client):
    response = client.post(
        "/api/auth/register",
        json={**REGISTRATION, "profession": "NURSE", "speciality": None},
    )
    assert response.status_code == 201
    assert response.json()["user"]["profession"] == "NURSE"


def test_the_clinic_and_telephone_are_required(client):
    for field in ("clinic_name", "phone"):
        response = client.post("/api/auth/register", json={**REGISTRATION, field: ""})
        assert response.status_code == 422, field


def test_a_short_password_is_refused(client):
    response = client.post("/api/auth/register", json={**REGISTRATION, "password": "short"})
    assert response.status_code == 422


def test_an_address_can_only_be_registered_once(client):
    assert client.post("/api/auth/register", json=REGISTRATION).status_code == 201
    second = client.post("/api/auth/register", json=REGISTRATION)
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


def test_registering_signs_the_clinician_in(client):
    body = client.post("/api/auth/register", json=REGISTRATION).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).json()["email"] == REGISTRATION["email"]
