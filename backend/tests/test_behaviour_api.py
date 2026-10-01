"""The camera-and-microphone API, and the promises it has to keep.

Three of these tests are about measurement and the rest are about restraint: that nothing
is decoded without consent, that the clip is gone once the numbers are out of it unless
somebody asked for it to be kept, and that the patient's own score never becomes an input.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.exceptions import InvalidTag

from backend.behaviour import service, storage
from database.models import BehaviourObservation, Patient, PatientConsent
from backend.tests import synthetic_clip


@pytest.fixture
def patient(db):
    row = Patient(code=f"OBS-{uuid.uuid4().hex[:8]}", is_synthetic=True)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def consented(db, patient):
    db.add(
        PatientConsent(
            patient_id=patient.id,
            scope=service.CONSENT_SCOPE,
            granted=True,
            granted_at=service.now(),
        )
    )
    db.flush()
    return patient


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """One clip, rendered once: encoding twenty seconds of video per test is not free."""
    directory = tmp_path_factory.mktemp("api-clips")
    return {
        "resting": synthetic_clip.clip(
            directory / "resting.webm", aperture=1.0, pupil=0.34, blinks_per_min=15
        ).read_bytes(),
        "strained": synthetic_clip.clip(
            directory / "strained.webm",
            aperture=0.42, pupil=0.60, brow_drop=0.9, blinks_per_min=34,
            pitch=196, jitter=0.028,
        ).read_bytes(),
    }


def _post(client, headers, patient, data, **fields):
    return client.post(
        f"/api/behaviour/patients/{patient.id}/observations",
        headers=headers,
        files={"clip": ("clip.webm", data, "video/webm")},
        data={key: str(value).lower() for key, value in fields.items()},
    )


def test_the_reference_says_what_will_be_measured(client, doctor_headers):
    body = client.get("/api/behaviour/reference", headers=doctor_headers).json()
    codes = {entry["code"] for entry in body["measures"]}
    assert {"eye_squint_index", "pupil_diameter_mm", "blink_rate_per_min", "jitter_percent"} <= codes
    assert body["iris_diameter_mm"] == 11.7
    assert "eyes open" in body["instruction"]
    assert "None of those is a pain measure" in body["notice"]
    # Every measure carries the sentence that keeps it from being read as a pain reading.
    assert all(entry["note"] for entry in body["measures"])


def test_nothing_is_decoded_without_consent(client, doctor_headers, patient, recorded):
    response = _post(client, doctor_headers, patient, recorded["resting"])
    assert response.status_code == 403
    assert service.CONSENT_SCOPE in response.json()["detail"]


def test_a_format_this_module_does_not_decode_is_refused(client, doctor_headers, consented):
    response = client.post(
        f"/api/behaviour/patients/{consented.id}/observations",
        headers=doctor_headers,
        files={"clip": ("x.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "text/plain" in response.json()["detail"]


def test_a_clip_is_measured_and_the_measures_come_back(
    client, doctor_headers, consented, recorded
):
    response = _post(client, doctor_headers, consented, recorded["strained"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["has_video"] and body["has_audio"]
    assert body["quality_verdict"] in ("GOOD", "ADEQUATE")
    assert "EYE" in body["usable_modalities"]
    assert body["measures"]["eye_aperture_ratio"] == pytest.approx(0.42, abs=0.15)
    assert body["measures"]["blink_rate_per_min"] == pytest.approx(34, abs=8)
    assert body["measures"]["pupil_diameter_mm"] > 0
    assert body["summary"]["eye"]["pupil_diameter_mm"] is not None
    # Every modality's verdict is reported with the figures it was reached on.
    assert {entry["modality"] for entry in body["modalities"]} == {"EYE", "FACE", "VOICE"}
    assert all("evidence" in entry for entry in body["modalities"])


def test_the_clip_is_deleted_unless_it_was_asked_for(
    client, db, doctor_headers, consented, recorded
):
    # Counted either side of the post rather than checked for an empty directory: the
    # store is shared with every other test in the suite, and one of them keeps a clip on
    # purpose. What this test is about is that *this* observation left nothing behind.
    before = len(list(storage.root().glob("*")))
    body = _post(client, doctor_headers, consented, recorded["resting"]).json()
    assert body["media_retained"] is False
    assert body["media_sha256"], "the digest is kept even when the clip is not"

    row = db.get(BehaviourObservation, uuid.UUID(body["id"]))
    assert row.storage_key is None
    assert row.wrapped_key is None
    assert len(list(storage.root().glob("*"))) == before
    assert any("deleted once these measures were taken" in note for note in body["notes"])


def test_a_retained_clip_is_encrypted_and_can_be_discarded_afterwards(
    client, db, doctor_headers, consented, recorded
):
    body = _post(
        client, doctor_headers, consented, recorded["resting"], retain_media=True
    ).json()
    assert body["media_retained"] is True

    observation = db.get(BehaviourObservation, uuid.UUID(body["id"]))
    stored = storage.root() / observation.storage_key
    assert stored.exists()
    assert stored.read_bytes() != recorded["resting"], "a clip is not stored in the clear"
    assert (
        storage.read(observation.id, observation.storage_key, observation.wrapped_key)
        == recorded["resting"]
    )

    discarded = client.delete(
        f"/api/behaviour/observations/{body['id']}/media", headers=doctor_headers
    )
    assert discarded.status_code == 204
    assert not stored.exists()
    again = client.get(f"/api/behaviour/observations/{body['id']}", headers=doctor_headers)
    assert again.json()["media_retained"] is False
    # The measures survive the recording.
    assert again.json()["measures"]["eye_aperture_ratio"] > 0


def test_a_clip_cannot_be_decrypted_against_another_observation(
    client, db, doctor_headers, consented, recorded
):
    """The ciphertext is bound to the row that owns it, so a key and a file from two
    different observations do not combine into somebody else's recording."""
    body = _post(
        client, doctor_headers, consented, recorded["resting"], retain_media=True
    ).json()
    row = db.get(BehaviourObservation, uuid.UUID(body["id"]))
    with pytest.raises(InvalidTag):
        storage.read(uuid.uuid4(), row.storage_key, row.wrapped_key)


def test_a_resting_clip_becomes_the_patients_baseline(
    client, db, doctor_headers, consented, recorded
):
    first = _post(client, doctor_headers, consented, recorded["resting"], at_rest=True)
    assert first.status_code == 201
    assert first.json()["at_rest"] is True

    resting = client.get(
        f"/api/behaviour/patients/{consented.id}/resting", headers=doctor_headers
    ).json()
    assert resting["recorded_at"] is not None
    assert resting["measures"]["eye_aperture_ratio"] > 0.8

    # A later clip is then read against it rather than against its own widest moment.
    second = _post(client, doctor_headers, consented, recorded["strained"]).json()
    assert second["reference"]["eye_squint_index"] == "CALIBRATION"
    assert second["measures"]["eye_squint_index"] > 0.3
    assert second["deltas"]["eye_aperture_ratio"] < -0.3


def test_eyes_that_were_never_open_are_refused_with_a_reason(
    client, doctor_headers, consented, tmp_path
):
    path = synthetic_clip.clip(
        tmp_path / "shut.webm", aperture=0.0, blinks_per_min=0, seconds=10
    )
    body = _post(client, doctor_headers, consented, path.read_bytes()).json()

    assert "EYE" not in body["usable_modalities"]
    assert "eye_aperture_ratio" not in body["measures"]
    eye = next(entry for entry in body["modalities"] if entry["modality"] == "EYE")
    assert eye["usable"] is False
    assert "eyes open" in " ".join(eye["findings"])


def test_an_observation_is_listed_against_the_patient(
    client, doctor_headers, consented, recorded
):
    _post(client, doctor_headers, consented, recorded["resting"], at_rest=True)
    _post(client, doctor_headers, consented, recorded["strained"])
    history = client.get(
        f"/api/behaviour/patients/{consented.id}/observations", headers=doctor_headers
    ).json()
    assert len(history) == 2
    assert [row["at_rest"] for row in history] == [False, True], "newest first"


def test_no_voice_model_means_a_level_of_none_and_a_reason(
    client, doctor_headers, consented, recorded
):
    """No voice model is registered in the test platform, and the absence has to be said
    rather than shown as a level of zero."""
    body = _post(client, doctor_headers, consented, recorded["resting"]).json()
    estimate = body["voice_estimate"]
    assert estimate["available"] is False
    assert estimate["level"] is None
    assert "voice-pain" in estimate["message"] or "unavailable" in estimate["message"].lower()
    assert any("not a 0-10 score" in line for line in estimate["limitations"])


def test_the_measures_hold_no_patient_identity(client, doctor_headers, consented, recorded):
    """A stored observation is a table of numbers. Nothing in it is a face."""
    body = _post(client, doctor_headers, consented, recorded["strained"]).json()
    assert all(isinstance(value, (int, float)) for value in body["measures"].values())
    assert all(isinstance(value, (int, float)) for value in body["deltas"].values())


def test_an_observation_reaches_the_clinical_estimate(
    client, doctor_headers, db, recorded
):
    """The last link in the chain.

    A clip measured against an assessment has to arrive in the feature vector the estimator
    reads, under the names the model was trained on. Everything upstream of this can be
    right and the channel still contribute nothing.
    """
    from backend.tests.test_api import make_assessment, make_patient

    patient = make_patient(client, doctor_headers)
    db.add(
        PatientConsent(
            patient_id=uuid.UUID(patient["id"]),
            scope=service.CONSENT_SCOPE,
            granted=True,
            granted_at=service.now(),
        )
    )
    db.flush()
    assessment = make_assessment(client, doctor_headers, patient["id"])

    before = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()["prediction"]
    assert before["features"]["eye_squint_index"] is None, (
        "no clip was recorded, so the behavioural features must be absent rather than zero"
    )

    posted = client.post(
        f"/api/behaviour/patients/{patient['id']}/observations",
        headers=doctor_headers,
        files={"clip": ("clip.webm", recorded["strained"], "video/webm")},
        data={"assessment_id": assessment["id"]},
    )
    assert posted.status_code == 201, posted.text

    after = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()["prediction"]
    features = after["features"]
    assert features["eye_aperture_ratio"] is not None
    assert features["blink_rate_per_min"] is not None
    assert features["facial_action_index"] is not None
    assert features["voice_jitter_percent"] is not None
    # And the figures are the ones the observation reported, not a re-derivation.
    measures = posted.json()["measures"]
    assert features["eye_aperture_ratio"] == pytest.approx(
        measures["eye_aperture_ratio"], abs=0.01
    )


def test_a_resting_observation_is_not_read_as_a_reading(
    client, doctor_headers, db, recorded
):
    """An at-rest clip is the reference, so it must not also become the observation the
    estimate is taken from — that would compare the patient against themselves and find no
    change by construction."""
    from backend.tests.test_api import make_assessment, make_patient

    patient = make_patient(client, doctor_headers)
    db.add(
        PatientConsent(
            patient_id=uuid.UUID(patient["id"]),
            scope=service.CONSENT_SCOPE,
            granted=True,
            granted_at=service.now(),
        )
    )
    db.flush()
    assessment = make_assessment(client, doctor_headers, patient["id"])

    client.post(
        f"/api/behaviour/patients/{patient['id']}/observations",
        headers=doctor_headers,
        files={"clip": ("clip.webm", recorded["resting"], "video/webm")},
        data={"assessment_id": assessment["id"], "at_rest": "true"},
    )
    prediction = client.post(
        f"/api/assessments/{assessment['id']}/predict", headers=doctor_headers
    ).json()["prediction"]
    assert prediction["features"]["eye_aperture_ratio"] is None
