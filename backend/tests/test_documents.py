import hashlib
import uuid
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas

from app.config import get_settings
from app.database.models import MedicalDocument
from tests.test_api import make_assessment, make_patient

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic radiograph placeholder" * 8
REPORT_TEXT = "Chest radiograph: no focal consolidation, no pneumothorax."


def build_pdf(text: str = REPORT_TEXT) -> bytes:
    buffer = BytesIO()
    page = pdf_canvas.Canvas(buffer, pagesize=A4)
    page.drawString(72, 720, text)
    page.save()
    return buffer.getvalue()


def upload(client, headers, patient_id, data, filename, media_type, **extra):
    return client.post(
        "/api/documents",
        headers=headers,
        data={"patient_id": patient_id, "kind": "XRAY", **extra},
        files={"file": (filename, data, media_type)},
    )


def test_an_unsupported_file_type_is_refused(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = upload(
        client, doctor_headers, patient["id"], b"MZ\x90\x00", "report.exe", "application/pdf"
    )
    assert response.status_code == 415


def test_the_declared_type_does_not_override_the_bytes(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = upload(
        client, doctor_headers, patient["id"], b"plain text", "scan.png", "image/png"
    )
    assert response.status_code == 415


def test_an_empty_file_is_refused(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assert (
        upload(client, doctor_headers, patient["id"], b"", "scan.png", "image/png").status_code
        == 422
    )


def test_an_image_is_stored_with_its_digest(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = upload(
        client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["media_type"] == "image/png"
    assert body["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert body["size_bytes"] == len(PNG_BYTES)


def test_the_file_on_disk_is_not_the_file_that_was_uploaded(client, doctor_headers, db):
    patient = make_patient(client, doctor_headers)
    body = upload(
        client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png"
    ).json()

    row = db.get(MedicalDocument, uuid.UUID(body["id"]))
    stored = (get_settings().document_store_path / row.storage_name).read_bytes()
    assert stored != PNG_BYTES
    assert b"radiograph" not in stored
    assert row.wrapped_key


def test_a_stored_document_comes_back_byte_for_byte(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    body = upload(
        client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png"
    ).json()

    response = client.get(f"/api/documents/{body['id']}/content", headers=doctor_headers)
    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["cache-control"] == "no-store"


def test_text_already_in_a_pdf_is_extracted(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    body = upload(
        client, doctor_headers, patient["id"], build_pdf(), "report.pdf", "application/pdf"
    ).json()
    assert body["extracted_text"] is not None
    assert "no focal consolidation" in body["extracted_text"]


def test_an_image_gets_no_extracted_text(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    body = upload(
        client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png"
    ).json()
    assert body["extracted_text"] is None


def test_findings_are_entered_by_the_clinician(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    body = upload(
        client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png"
    ).json()
    assert body["findings"] is None

    updated = client.patch(
        f"/api/documents/{body['id']}",
        headers=doctor_headers,
        json={"findings": "No acute cardiopulmonary abnormality."},
    ).json()
    assert updated["findings"] == "No acute cardiopulmonary abnormality."


def test_a_document_can_be_attached_to_an_assessment(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, patient["id"])
    body = upload(
        client,
        doctor_headers,
        patient["id"],
        PNG_BYTES,
        "chest.png",
        "image/png",
        assessment_id=assessment["id"],
    ).json()

    listed = client.get(
        f"/api/documents?assessment_id={assessment['id']}", headers=doctor_headers
    ).json()
    assert [item["id"] for item in listed] == [body["id"]]


def test_a_document_cannot_be_attached_to_another_patients_assessment(client, doctor_headers):
    first = make_patient(client, doctor_headers)
    second = make_patient(client, doctor_headers)
    assessment = make_assessment(client, doctor_headers, first["id"])
    response = upload(
        client,
        doctor_headers,
        second["id"],
        PNG_BYTES,
        "chest.png",
        "image/png",
        assessment_id=assessment["id"],
    )
    assert response.status_code == 422


def test_uploading_a_document_is_written_to_the_ledger(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    before = client.get("/api/integrity/status", headers=doctor_headers).json()["blocks"]
    upload(client, doctor_headers, patient["id"], PNG_BYTES, "chest.png", "image/png")
    after = client.get("/api/integrity/status", headers=doctor_headers).json()
    assert after["blocks"] > before
    assert after["ledger_valid"]
