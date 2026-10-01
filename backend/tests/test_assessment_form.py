"""The patient form, the consistency checks, deletion and who may do what."""

import io

import pytest
from pypdf import PdfReader

from backend.api.serializers import duration_label
from backend.tests.test_api import CHEST_CASE, make_assessment, make_patient
from knowledge import consistency

ACCOUNT_PASSWORD = "Garde-de-nuit-2026"


def _account(client, admin_headers, email, role, **extra):
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": ACCOUNT_PASSWORD,
            "role": role,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/login", json={"email": email, "password": ACCOUNT_PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def nurse_headers(client, admin_headers):
    return _account(client, admin_headers, "k.ziani@chu-batna.dz", "NURSE", profession="NURSE")


# --- the patient block -------------------------------------------------------------------


def test_age_and_sex_are_required(client, doctor_headers):
    base = {"identity": {"given_name": "Amel", "family_name": "Cherif"}}
    assert client.post("/api/patients", headers=doctor_headers, json=base).status_code == 422
    too_old = client.post(
        "/api/patients", headers=doctor_headers, json={**base, "sex": "F", "age_years": 121}
    )
    assert too_old.status_code == 422
    undisclosed = client.post(
        "/api/patients", headers=doctor_headers, json={**base, "sex": "UNDISCLOSED", "age_years": 40}
    )
    assert undisclosed.status_code == 422
    assert "F or M" in str(undisclosed.json()["detail"])


def test_the_typed_age_stands_in_for_a_missing_date_of_birth(client, doctor_headers):
    patient = make_patient(client, doctor_headers, birth_date=None, age_years=73)
    assert patient["age"] == 73
    assert patient["age_years"] == 73


def test_the_ward_comes_from_the_list(client, doctor_headers):
    refused = client.post(
        "/api/patients",
        headers=doctor_headers,
        json={
            "identity": {"given_name": "Amel", "family_name": "Cherif"},
            "sex": "F",
            "age_years": 58,
            "ward": "ward",
        },
    )
    assert refused.status_code == 422
    assert make_patient(client, doctor_headers, ward="Intensive care")["ward"] == "Intensive care"


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("05 51 23 45 67", "0551234567"),
        ("+213 661 22 08 41", "0661220841"),
        ("00213 7 70 11 22 33", "0770112233"),
        ("033 12 34 56", "033123456"),
    ],
)
def test_algerian_telephone_numbers_are_accepted_and_normalised(client, doctor_headers, typed, stored):
    patient = make_patient(
        client, doctor_headers, identity={"given_name": "Amel", "family_name": "Cherif", "phone": typed}
    )
    assert patient["identity"]["phone"] == stored


@pytest.mark.parametrize("typed", ["12345", "+33 6 12 34 56 78", "0851234567", "055123456"])
def test_a_foreign_or_malformed_telephone_number_is_refused(client, doctor_headers, typed):
    response = client.post(
        "/api/patients",
        headers=doctor_headers,
        json={
            "identity": {"given_name": "Amel", "family_name": "Cherif", "phone": typed},
            "sex": "F",
            "age_years": 58,
        },
    )
    assert response.status_code == 422
    assert "Algerian" in str(response.json()["detail"])


# --- duration --------------------------------------------------------------------------


def test_a_duration_is_kept_as_entered_and_read_in_hours(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client, doctor_headers, patient["id"], duration_value=2, duration_unit="days"
    )
    assert assessment["duration_value"] == 2
    assert assessment["duration_unit"] == "days"
    assert assessment["duration_hours"] == 48
    assert assessment["duration_label"] == "2 days"


def test_a_duration_needs_both_halves(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={"patient_id": patient["id"], **CHEST_CASE, "duration_unit": None},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("value", "unit", "label"),
    [(1, "hours", "1 hour"), (3, "hours", "3 hours"), (1, "days", "1 day"), (0.5, "months", "0.5 months"), (None, None, "Not recorded")],
)
def test_the_duration_label_agrees_in_number(value, unit, label):
    assert duration_label(value, unit) == label


# --- consistency checks ----------------------------------------------------------------


def test_a_diabetic_with_no_antidiabetic_is_flagged_not_blocked(client, doctor_headers):
    patient = make_patient(client, doctor_headers, medications=[])
    codes = {warning["code"] for warning in patient["warnings"]}
    assert "UNTREATED_DIABETES_T2" in codes
    assert "UNTREATED_HYPERTENSION" in codes

    treated = make_patient(client, doctor_headers)
    assert "UNTREATED_DIABETES_T2" not in {w["code"] for w in treated["warnings"]}


def test_an_antidiabetic_given_during_the_assessment_counts_as_treatment(client, doctor_headers):
    patient = make_patient(client, doctor_headers, medications=[], condition_codes=["DIABETES_T2"])
    assessment = make_assessment(
        client,
        doctor_headers,
        patient["id"],
        medications=[{"class_code": "ANTIDIABETIC", "name": "Metformine 850"}],
    )
    assert not [w for w in assessment["warnings"] if w["code"].startswith("UNTREATED")]


def test_an_adult_in_paediatrics_is_flagged(client, doctor_headers):
    patient = make_patient(client, doctor_headers, ward="Paediatrics", medications=[], condition_codes=[])
    assert [w["code"] for w in patient["warnings"]] == ["ADULT_IN_PAEDIATRICS"]
    child = make_patient(
        client, doctor_headers, ward="Surgery", age_years=6, birth_date=None, condition_codes=[]
    )
    assert [w["code"] for w in child["warnings"]] == ["CHILD_IN_ADULT_WARD"]


def test_fever_with_sudden_chest_pain_demands_urgent_review(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(
        client, doctor_headers, patient["id"], symptom_codes=["FEVER", "DYSPNOEA"]
    )
    assert assessment["urgent_review"]
    assert any(w["level"] == "URGENT" for w in assessment["warnings"])

    gradual = make_assessment(
        client, doctor_headers, patient["id"], symptom_codes=["FEVER"], onset="GRADUAL"
    )
    assert not gradual["urgent_review"]


def test_a_measured_fever_counts_without_the_symptom():
    found = consistency.assessment_findings(
        symptoms=set(), location_codes=["CHEST_LEFT"], onset="SUDDEN", temperature_c=38.6
    )
    assert [f.level for f in found] == ["URGENT"]


# --- deletion --------------------------------------------------------------------------


def test_an_assessment_can_be_deleted_after_validation(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)
    client.post(f"/api/assessments/{assessment['id']}/validate", headers=doctor_headers)

    assert client.delete(f"/api/assessments/{assessment['id']}", headers=doctor_headers).status_code == 204
    assert client.get(f"/api/assessments/{assessment['id']}", headers=doctor_headers).status_code == 404
    history = client.get(f"/api/patients/{patient['id']}/history", headers=doctor_headers).json()
    assert history["points"] == []


def test_deleting_a_patient_takes_the_record_with_it(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)

    assert client.delete(f"/api/patients/{patient['id']}", headers=doctor_headers).status_code == 204
    assert client.get(f"/api/patients/{patient['id']}", headers=doctor_headers).status_code == 404
    assert client.get(f"/api/assessments/{assessment['id']}", headers=doctor_headers).status_code == 404
    codes = [item["code"] for item in client.get("/api/patients", headers=doctor_headers).json()["items"]]
    assert patient["code"] not in codes


# --- who may do what -------------------------------------------------------------------


def test_a_nurse_records_but_does_not_validate_or_delete(client, doctor_headers, nurse_headers):
    patient = make_patient(client, nurse_headers)
    assessment = make_assessment(client, nurse_headers, patient["id"])
    estimated = client.post(f"/api/assessments/{assessment['id']}/predict", headers=nurse_headers)
    assert estimated.status_code == 200

    refused = client.post(f"/api/assessments/{assessment['id']}/validate", headers=nurse_headers)
    assert refused.status_code == 403
    assert "doctor" in refused.json()["detail"]
    assert client.delete(f"/api/assessments/{assessment['id']}", headers=nurse_headers).status_code == 403
    assert client.delete(f"/api/patients/{patient['id']}", headers=nurse_headers).status_code == 403


def test_an_administrator_does_not_validate_either(client, admin_headers):
    patient = make_patient(client, admin_headers)
    assessment = make_assessment(client, admin_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=admin_headers)
    assert client.post(f"/api/assessments/{assessment['id']}/validate", headers=admin_headers).status_code == 403


def test_validation_records_who_and_when(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)
    validated = client.post(f"/api/assessments/{assessment['id']}/validate", headers=doctor_headers).json()
    me = client.get("/api/auth/me", headers=doctor_headers).json()
    assert validated["validated_at"]
    pdf = client.post(f"/api/reports/{assessment['id']}/generate", headers=doctor_headers)
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert f"Validated by {me['display_name']}" in text


def test_a_patient_account_reads_its_own_record_only(client, doctor_headers, admin_headers):
    mine = make_patient(client, doctor_headers)
    other = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, mine["id"])
    headers = _account(
        client, admin_headers, "a.cherif@gmail.com", "PATIENT", patient_id=mine["id"]
    )

    assert client.get(f"/api/patients/{mine['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/patients/{other['id']}", headers=headers).status_code == 403
    assert client.get("/api/patients", headers=headers).status_code == 403
    assert client.get(f"/api/assessments/{assessment['id']}", headers=headers).status_code == 200
    listed = client.get(f"/api/assessments?patient_id={other['id']}", headers=headers).json()
    assert {row["patient_id"] for row in listed["items"]} <= {mine["id"]}
    assert client.post(f"/api/reports/{assessment['id']}/generate", headers=headers).status_code == 200
    assert client.post("/api/assessments", headers=headers, json={"patient_id": mine["id"]}).status_code == 403
    assert client.get("/api/analytics", headers=headers).status_code == 403


def test_a_patient_account_must_name_a_record(client, admin_headers):
    response = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "nobody@gmail.com",
            "display_name": "Nobody",
            "password": ACCOUNT_PASSWORD,
            "role": "PATIENT",
        },
    )
    assert response.status_code == 422


def test_registering_as_a_nurse_gives_the_nurse_role(client):
    body = client.post(
        "/api/auth/register",
        json={
            "email": "s.rahal@clinique-ennour.dz",
            "password": "Consultation-Ennour-2026",
            "display_name": "S. Rahal",
            "clinic_name": "Clinique Ennour",
            "phone": "+213 661 22 08 41",
            "profession": "NURSE",
        },
    ).json()
    assert body["user"]["role"] == "NURSE"


# --- the report ------------------------------------------------------------------------


def test_the_report_keeps_labels_apart_and_numbers_its_pages(client, doctor_headers):
    patient = make_patient(client, doctor_headers, identity={"given_name": "Amel", "family_name": "Cherif"})
    assessment = make_assessment(client, doctor_headers, patient["id"], duration_value=1, duration_unit="hours")
    client.post(f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers)

    pdf = client.post(f"/api/reports/{assessment['id']}/generate", headers=doctor_headers)
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    first = pages[0].extract_text()
    assert first.startswith("Pain assessment report")
    assert first.rstrip().endswith(f"Page 1 of {len(pages)}")
    assert "1 hour\n" in first
    assert "1 hours" not in first
    assert "None recorded" in first
    # Each label sits on its own line in the extracted text, with its value on the next.
    assert "Name\nAmel Cherif\n" in first
    assert "Ward\nMedicine\n" in first
    for number, page in enumerate(pages, start=1):
        assert "AI-assisted prototype" in page.extract_text()
        assert f"Page {number} of {len(pages)}" in page.extract_text()
