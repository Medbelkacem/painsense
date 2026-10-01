"""The Start Analysis -> Stop & Analyze workflow, and the honesty rules around it.

The rules worth testing hardest are the ones that are easy to break later: a recording
always declares its source, a pain score is never invented when no model exists, and the
patient's own score never becomes a model input.
"""

import uuid

import numpy as np
import pytest
from sqlalchemy import select

from database.models import (
    Patient,
    RecordingState,
    SignalAnalysis,
    SignalRecording,
    SignalSource,
)
from backend.signals import inference, schema

CHANNELS = [
    "EEG_FPZ",
    "EEG_CZ",
    "EMG_TRAPEZIUS_L",
    "PPG_FINGER",
    "GSR_PALMAR",
    "RESPIRATION_BELT",
]


@pytest.fixture
def patient(db):
    row = Patient(code=f"SIG-{uuid.uuid4().hex[:8]}", is_synthetic=True)
    db.add(row)
    db.flush()
    return row


def _stop(client, headers, recording_id):
    """Stop acquisition. Saves and validates; does not analyse."""
    return client.post(f"/api/signals/recordings/{recording_id}/stop", headers=headers)


def _analyse(client, headers, recording_id, **body):
    """The separate Analyze Recording step."""
    return client.post(
        f"/api/signals/recordings/{recording_id}/analyze", headers=headers, json=body
    )


def _record_and_analyse(client, headers, recording_id, **body):
    stopped = _stop(client, headers, recording_id)
    assert stopped.status_code == 200, stopped.text
    analysed = _analyse(client, headers, recording_id, **body)
    assert analysed.status_code == 200, analysed.text
    return analysed


def _simulated(client, headers, patient, **overrides):
    body = {
        "patient_id": str(patient.id),
        "channels": CHANNELS,
        "source": "SIMULATION",
        "simulate_seconds": 20,
        "simulate_seed": 11,
        **overrides,
    }
    response = client.post("/api/signals/recordings", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- reference -----------------------------------------------------------------------


def test_reference_tells_the_interface_up_front_that_no_model_exists(client, doctor_headers):
    body = client.get("/api/signals/reference", headers=doctor_headers).json()

    assert body["model_available"] is False
    assert body["model_message"] == inference.UNAVAILABLE_MESSAGE
    assert len(body["channels"]) == len(schema.CHANNELS)
    assert body["feature_schema_version"] == schema.FEATURE_SCHEMA_VERSION
    assert "none" in body["simulation_faults"]


def test_reference_marks_which_channels_the_analysis_is_of(client, doctor_headers):
    body = client.get("/api/signals/reference", headers=doctor_headers).json()
    primary = {row["code"] for row in body["channels"] if row["primary"]}
    supporting = {row["code"] for row in body["channels"] if not row["primary"]}
    assert "EEG_FPZ" in primary and "EMG_TRAPEZIUS_L" in primary
    assert supporting == {"PPG_FINGER", "GSR_PALMAR", "RESPIRATION_BELT"}


def test_reference_needs_a_signed_in_user(client):
    assert client.get("/api/signals/reference").status_code == 401


# --- the hardware workflow -------------------------------------------------------------


def test_the_full_start_stream_stop_workflow(client, doctor_headers, patient):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ", "EMG_TRAPEZIUS_L"],
            "sample_rate_hz": 512.0,
            "source": "HARDWARE",
            "device_label": "OpenBCI Cyton",
        },
    )
    assert started.status_code == 201, started.text
    recording = started.json()
    assert recording["state"] == RecordingState.RECORDING.value
    assert recording["source"] == SignalSource.HARDWARE.value

    rng = np.random.default_rng(0)
    rate, block_seconds = 512.0, 2.0
    for _ in range(10):
        n = int(rate * block_seconds)
        t = np.arange(n) / rate
        block = {
            "EEG_FPZ": (15 * np.sin(2 * np.pi * 10 * t) + rng.normal(0, 4, n)).tolist(),
            "EMG_TRAPEZIUS_L": rng.normal(0, 35, n).tolist(),
        }
        posted = client.post(
            f"/api/signals/recordings/{recording['id']}/samples",
            headers=doctor_headers,
            json={"samples": block},
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["accepted_samples"] == n
        assert posted.json()["elapsed_seconds"] >= 0

    stopped = _stop(client, doctor_headers, recording["id"])
    assert stopped.status_code == 200, stopped.text
    saved = stopped.json()
    assert saved["state"] == "SAVED", "stop saves and validates; it does not analyse"
    assert saved["validation"]["intact"] is True
    assert {entry["name"] for entry in saved["files"]} >= {"eeg.csv", "emg.csv", "metadata.json"}
    assert saved["analyses"] == []

    body = _analyse(client, doctor_headers, recording["id"], reported_nrs=6).json()

    assert body["state"] == RecordingState.ANALYSED.value
    assert body["samples"] == int(rate * block_seconds) * 10
    assert body["duration_seconds"] == pytest.approx(20.0, abs=0.1)
    assert body["sha256"]
    assert body["quality_verdict"] in ("GOOD", "ADEQUATE")

    analysis = body["analyses"][0]
    assert analysis["feature_count"] > 0
    assert "EEG_FPZ" in analysis["derived_from"]
    assert analysis["summary"]["eeg"]["alpha_relative"] > 0.3
    assert analysis["summary"]["emg"]["rms_uv"] > 0


def test_posting_to_a_stopped_recording_is_refused(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"])
    response = client.post(
        f"/api/signals/recordings/{recording['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_FPZ": [1.0, 2.0]}},
    )
    assert response.status_code == 409


def test_a_channel_not_opened_on_the_recording_is_refused(client, doctor_headers, patient):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    response = client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_CZ": [1.0, 2.0]}},
    )
    assert response.status_code == 422


def test_stopping_without_a_single_sample_stores_nothing(client, doctor_headers, patient):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    response = _stop(client, doctor_headers, started["id"])
    assert response.status_code == 422
    assert "without receiving any sample" in response.json()["detail"]

    after = client.get(
        f"/api/signals/recordings/{started['id']}", headers=doctor_headers
    ).json()
    assert after["state"] == RecordingState.DISCARDED.value
    assert after["sha256"] is None


def test_an_unknown_channel_is_refused_at_start(client, doctor_headers, patient):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={"patient_id": str(patient.id), "channels": ["EEG_FPZ", "NOPE"]},
    )
    assert response.status_code == 422


def test_a_recording_of_only_supporting_channels_is_refused(client, doctor_headers, patient):
    """This analysis is of EEG and EMG; a pulse-only recording is not one."""
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={"patient_id": str(patient.id), "channels": ["PPG_FINGER"]},
    )
    assert response.status_code == 422
    assert "EEG or EMG" in response.json()["detail"]


def test_an_unknown_patient_is_refused(client, doctor_headers):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": "00000000-0000-0000-0000-000000000000",
            "channels": ["EEG_FPZ"],
        },
    )
    assert response.status_code == 404


# --- the model boundary ------------------------------------------------------------------


def test_no_model_means_no_score_and_the_exact_message(client, doctor_headers, patient):
    """The rule this whole feature turns on."""
    recording = _simulated(client, doctor_headers, patient)
    body = _record_and_analyse(client, doctor_headers, recording["id"], reported_nrs=7).json()
    analysis = body["analyses"][0]

    assert analysis["estimate_available"] is False
    assert analysis["pain_score"] is None, "a score must not be invented"
    assert analysis["pain_category"] is None
    assert analysis["model_version"] is None
    assert analysis["uncertainty"] is None
    assert analysis["unavailable_reason"] == inference.UNAVAILABLE_MESSAGE

    # The signal work still completed, which is the point of recording at all.
    assert analysis["feature_count"] > 0
    assert body["quality_verdict"] in ("GOOD", "ADEQUATE")


def test_the_patients_own_score_is_stored_apart_from_any_estimate(
    client, doctor_headers, patient
):
    recording = _simulated(client, doctor_headers, patient)
    analysis = _record_and_analyse(
        client, doctor_headers, recording["id"], reported_nrs=8
    ).json()["analyses"][0]

    assert analysis["reported_nrs"] == 8
    assert analysis["pain_score"] is None
    assert not any("reported" in name for name in analysis["summary"])


def test_the_reported_score_never_reaches_the_feature_set(client, db, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"], reported_nrs=9)
    row = db.scalar(
        select(SignalAnalysis).where(
            SignalAnalysis.recording_id == uuid.UUID(recording["id"])
        )
    )
    assert row.reported_nrs == 9
    assert all("nrs" not in name.casefold() for name in row.features)
    assert all("report" not in name.casefold() for name in row.features)


def test_an_out_of_range_reported_score_is_refused(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _stop(client, doctor_headers, recording["id"])
    response = _analyse(client, doctor_headers, recording["id"], reported_nrs=11)
    assert response.status_code == 422


def test_an_unusable_recording_is_still_stored_with_its_quality(
    client, doctor_headers, patient
):
    """Knowing the electrodes were off is the useful output of that session."""
    recording = _simulated(
        client,
        doctor_headers,
        patient,
        channels=["EEG_FPZ", "EEG_CZ"],
        simulate_faults={"EEG_FPZ": "flatline", "EEG_CZ": "flatline"},
    )
    body = _record_and_analyse(client, doctor_headers, recording["id"]).json()

    assert body["state"] == RecordingState.ANALYSED.value
    assert body["quality_verdict"] == "UNUSABLE"
    assert body["sha256"], "the recording is kept even though it is unusable"
    analysis = body["analyses"][0]
    assert analysis["feature_count"] == 0
    assert analysis["estimate_available"] is False
    assert set(analysis["skipped_channels"]) == {"EEG_FPZ", "EEG_CZ"}


# --- simulation labelling ------------------------------------------------------------------


def test_a_simulated_recording_is_labelled_at_every_level(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    assert recording["source"] == SignalSource.SIMULATION.value
    assert recording["device_label"] == "Software simulator"

    saved = _record_and_analyse(client, doctor_headers, recording["id"])
    assert saved.json()["source"] == SignalSource.SIMULATION.value

    trace = client.get(
        f"/api/signals/recordings/{recording['id']}/waveform", headers=doctor_headers
    ).json()
    assert trace["source"] == SignalSource.SIMULATION.value


def test_simulation_options_are_refused_on_a_hardware_recording(
    client, doctor_headers, patient
):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
            "simulate_seconds": 10,
        },
    )
    assert response.status_code == 422


def test_real_and_simulated_recordings_are_separable_in_the_history(
    client, db, doctor_headers, patient
):
    _simulated(client, doctor_headers, patient)
    client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    )
    simulated = client.get(
        "/api/signals/recordings",
        params={"source": "SIMULATION", "patient_id": str(patient.id)},
        headers=doctor_headers,
    ).json()
    hardware = client.get(
        "/api/signals/recordings",
        params={"source": "HARDWARE", "patient_id": str(patient.id)},
        headers=doctor_headers,
    ).json()

    assert len(simulated) == 1
    assert len(hardware) == 1
    assert all(row["source"] == "SIMULATION" for row in simulated)
    assert all(row["source"] == "HARDWARE" for row in hardware)

    # Nothing in the table can exist without declaring which it is.
    for row in db.scalars(select(SignalRecording)):
        assert row.source in (SignalSource.HARDWARE, SignalSource.SIMULATION)


# --- history and waveform --------------------------------------------------------------------


def test_a_previous_report_can_be_reopened(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    first = _record_and_analyse(
        client, doctor_headers, recording["id"], reported_nrs=4
    ).json()

    reopened = client.get(
        f"/api/signals/recordings/{recording['id']}", headers=doctor_headers
    ).json()
    assert reopened["analyses"][0]["id"] == first["analyses"][0]["id"]
    assert reopened["analyses"][0]["reported_nrs"] == 4
    assert reopened["quality"]["channels"]


def test_the_history_carries_what_the_brief_asks_for(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"])
    row = client.get(
        "/api/signals/recordings",
        params={"patient_id": str(patient.id)},
        headers=doctor_headers,
    ).json()[0]

    for field in (
        "id",
        "patient_id",
        "started_at",
        "duration_seconds",
        "sensor_status",
        "quality_verdict",
        "state",
        "source",
    ):
        assert field in row, f"{field} missing from the history row"


def test_the_waveform_is_decimated_and_says_so(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"])
    trace = client.get(
        f"/api/signals/recordings/{recording['id']}/waveform",
        params={"points": 300},
        headers=doctor_headers,
    ).json()

    assert trace["decimation"] > 1
    assert "Decimated" in trace["notice"]
    assert set(trace["channels"]) == set(CHANNELS)
    assert len(trace["channels"]["EEG_FPZ"]) <= 320


def test_a_dropped_lead_travels_as_a_gap_not_a_zero(client, doctor_headers, patient):
    recording = _simulated(
        client,
        doctor_headers,
        patient,
        channels=["EEG_FPZ", "EEG_CZ"],
        simulate_faults={"EEG_CZ": "missing"},
    )
    _record_and_analyse(client, doctor_headers, recording["id"])
    trace = client.get(
        f"/api/signals/recordings/{recording['id']}/waveform", headers=doctor_headers
    ).json()
    assert any(value is None for value in trace["channels"]["EEG_CZ"])


def test_a_waveform_for_a_recording_with_no_samples_is_a_conflict(
    client, doctor_headers, patient
):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    response = client.get(
        f"/api/signals/recordings/{started['id']}/waveform", headers=doctor_headers
    )
    assert response.status_code == 409


def test_an_analysed_recording_cannot_be_discarded(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"])
    response = client.post(
        f"/api/signals/recordings/{recording['id']}/discard", headers=doctor_headers
    )
    assert response.status_code == 409


def test_an_abandoned_recording_is_swept_closed(client, db, doctor_headers, patient):
    from datetime import timedelta

    from backend.signals import service

    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    closed = service.sweep_stale(db, older_than=timedelta(seconds=-1))
    assert closed >= 1
    row = db.get(SignalRecording, uuid.UUID(started["id"]))
    assert row.state is RecordingState.DISCARDED


# --- access control ------------------------------------------------------------------------------


def test_recording_needs_a_clinical_account(client, patient):
    assert client.get("/api/signals/recordings").status_code == 401
    assert (
        client.post(
            "/api/signals/recordings",
            json={"patient_id": str(patient.id), "channels": ["EEG_FPZ"]},
        ).status_code
        == 401
    )


def test_analyses_are_research_scoped(client, doctor_headers, admin_headers):
    assert client.get("/api/signals/analyses").status_code == 401
    assert client.get("/api/signals/analyses", headers=doctor_headers).status_code == 403
    assert client.get("/api/signals/analyses", headers=admin_headers).status_code == 200


def test_a_recording_is_written_to_the_audit_trail(client, db, doctor_headers, patient):
    from database.models import AuditLog

    recording = _simulated(client, doctor_headers, patient)
    _record_and_analyse(client, doctor_headers, recording["id"])
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.resource == "signal_recording")
        .order_by(AuditLog.timestamp.desc())
    ).all()
    assert entries
    assert any(entry.meta.get("action") == "analysed" for entry in entries)


# --- per-modality sampling rates ---------------------------------------------------------


def test_eeg_and_emg_can_be_recorded_at_different_rates(client, doctor_headers, patient):
    """The case the brief names: EEG at 250 Hz beside surface EMG at 1 kHz."""
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ", "EMG_TRAPEZIUS_L"],
            "sample_rate_hz": 250.0,
            "channel_rates": {"EEG_FPZ": 250.0, "EMG_TRAPEZIUS_L": 1000.0},
            "source": "HARDWARE",
        },
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["channel_rates"] == {"EEG_FPZ": 250.0, "EMG_TRAPEZIUS_L": 1000.0}
    # The session's own rate is the EEG rate, because that is what the analysis is of.
    assert body["sample_rate_hz"] == 250.0


def test_a_rate_for_a_channel_not_being_recorded_is_refused(client, doctor_headers, patient):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "channel_rates": {"EMG_TRAPEZIUS_R": 1000.0},
        },
    )
    assert response.status_code == 422


def test_each_modality_is_analysed_at_its_own_rate(client, doctor_headers, patient):
    """An EMG median frequency computed under the EEG's rate would land in the wrong place."""
    import numpy as np

    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ", "EMG_TRAPEZIUS_L"],
            "channel_rates": {"EEG_FPZ": 250.0, "EMG_TRAPEZIUS_L": 1000.0},
            "source": "HARDWARE",
        },
    ).json()

    rng = np.random.default_rng(5)
    seconds = 20
    eeg_n, emg_n = 250 * seconds, 1000 * seconds
    eeg_t = np.arange(eeg_n) / 250.0
    client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={
            "samples": {
                "EEG_FPZ": (20 * np.sin(2 * np.pi * 10 * eeg_t) + rng.normal(0, 4, eeg_n)).tolist(),
                "EMG_TRAPEZIUS_L": rng.normal(0, 40, emg_n).tolist(),
            }
        },
    )
    body = _record_and_analyse(client, doctor_headers, started["id"]).json()
    analysis = body["analyses"][0]

    assert analysis["summary"]["eeg"]["alpha_relative"] > 0.3
    assert analysis["summary"]["emg"]["rms_uv"] > 0
    assert any("per sampling rate" in note for note in analysis["notes"])
    # Two rate groups, so both appear in the quality findings namespace.
    assert len(body["quality"]["channels"]) == 2


# --- validation as its own step ------------------------------------------------------------


def test_stop_validates_the_written_files(client, doctor_headers, patient):
    recording = _simulated(client, doctor_headers, patient)
    saved = _stop(client, doctor_headers, recording["id"]).json()

    validation = saved["validation"]
    assert validation["intact"] is True
    assert sorted(validation["channels_present"]) == sorted(recording["channels"])
    assert saved["validated_at"]
    assert saved["sha256"], "a digest over the written files"


def test_validation_reports_a_declared_channel_that_never_arrived(
    client, db, doctor_headers, patient
):
    import uuid as _uuid

    from database.models import SignalRecording

    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ", "EEG_CZ"],
            "source": "HARDWARE",
        },
    ).json()
    # Only one of the two declared channels is ever posted.
    client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_FPZ": [1.0, 2.0, 3.0, 4.0]}},
    )
    saved = _stop(client, doctor_headers, started["id"]).json()

    assert "EEG_CZ" in str(saved["validation"]["findings"])
    row = db.get(SignalRecording, _uuid.UUID(started["id"]))
    assert row.validation["intact"] is False


def test_analysis_is_refused_while_the_recording_is_open(client, doctor_headers, patient):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    response = _analyse(client, doctor_headers, started["id"])
    assert response.status_code == 409
    assert "stop it before analysing" in response.json()["detail"]


def test_a_recording_can_be_analysed_again(client, doctor_headers, patient):
    """A later model should be applicable to an existing recording."""
    recording = _simulated(client, doctor_headers, patient)
    _stop(client, doctor_headers, recording["id"])
    first = _analyse(client, doctor_headers, recording["id"], reported_nrs=3).json()
    second = _analyse(client, doctor_headers, recording["id"], reported_nrs=5).json()

    assert len(second["analyses"]) == 2, "a re-analysis adds, it does not overwrite"
    assert {a["reported_nrs"] for a in second["analyses"]} == {3.0, 5.0}
    assert first["analyses"][0]["id"] in {a["id"] for a in second["analyses"]}


# --- the files on disk ----------------------------------------------------------------------


def test_the_session_is_written_in_the_documented_layout(client, doctor_headers, patient):
    from backend.signals import storage

    recording = _simulated(client, doctor_headers, patient)
    saved = _stop(client, doctor_headers, recording["id"]).json()
    _analyse(client, doctor_headers, recording["id"])

    names = {entry["name"] for entry in saved["files"]}
    assert {"eeg.csv", "emg.csv", "metadata.json"} <= names
    assert saved["participant_ref"] and saved["participant_ref"] not in str(patient.code)

    directory = storage.resolve(storage.session_key(saved["participant_ref"], recording["id"].replace("-", "")))
    assert directory.is_dir()
    header = (directory / "eeg.csv").read_text().splitlines()[0]
    assert header.startswith("sample_index,timestamp_ns,")

    metadata = storage.read_metadata(storage.session_key(saved["participant_ref"], recording["id"].replace("-", "")))
    assert metadata["channel_rates"]
    assert metadata["units"]["EEG_FPZ"] == "uV"
    assert metadata["consent"]["scope"] == "PHYSIOLOGICAL_RECORDING"
    assert metadata["provenance"] == "synthetic simulation"


def test_samples_are_written_continuously_not_held_until_stop(
    client, doctor_headers, patient
):
    """An interrupted recording must keep what was posted before the interruption."""
    from backend.signals import service, storage

    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_FPZ": [1.0] * 100}},
    )

    # Nothing has been stopped, yet the rows are already on disk.
    key = storage.session_key(
        started["participant_ref"], started["id"].replace("-", "")
    )
    writer = service.writers.get(started["id"])
    assert writer is not None
    assert writer.rows_per_file()["eeg.csv"] == 100
    assert (storage.resolve(key) / "eeg.csv").read_text().count("\n") >= 100


def test_a_storage_failure_during_a_block_is_reported(client, doctor_headers, patient, monkeypatch):
    from backend.signals import service, storage

    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()

    def _refuse(*_args, **_kwargs):
        raise storage.StorageError("the volume is read-only")

    monkeypatch.setattr(storage.SessionWriter, "append", _refuse)
    response = client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_FPZ": [1.0, 2.0]}},
    )
    assert response.status_code == 507
    assert "read-only" in response.json()["detail"]
    service.writers.pop(started["id"])


def test_a_session_directory_that_cannot_be_created_fails_the_start(
    client, doctor_headers, patient, monkeypatch
):
    from backend.signals import storage

    def _refuse(self):
        raise storage.StorageError("no space left on device")

    monkeypatch.setattr(storage.SessionWriter, "open", _refuse)
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    )
    assert response.status_code == 507


# --- devices -----------------------------------------------------------------------------------


def test_device_discovery_reports_nothing_connected_on_a_bare_machine(
    client, doctor_headers
):
    body = client.get("/api/signals/devices", headers=doctor_headers).json()
    assert body["connected"] is False
    assert body["devices"] == []
    # The adapters are still described, so the interface can say what it supports.
    assert {a["code"] for a in body["adapters"]} == {
        "openbci_cyton",
        "serial_gateway",
        "ble_gateway",
    }
    assert all(a["protocol"] and a["transport"] for a in body["adapters"])


def test_an_unknown_adapter_is_refused_at_start(client, doctor_headers, patient):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "adapter": "telepathy",
            "device_identifier": "/dev/null",
        },
    )
    assert response.status_code == 404


def test_a_device_that_cannot_be_opened_is_a_conflict_not_a_bad_request(
    client, doctor_headers, patient
):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "adapter": "openbci_cyton",
            "device_identifier": "/dev/definitely-not-a-port",
        },
    )
    assert response.status_code == 409
    assert "could not be opened" in response.json()["detail"]


def test_an_adapter_without_an_identifier_is_refused(client, doctor_headers, patient):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "adapter": "openbci_cyton",
        },
    )
    assert response.status_code == 422


def test_a_simulated_recording_cannot_name_a_device(client, doctor_headers, patient):
    response = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "SIMULATION",
            "adapter": "openbci_cyton",
            "device_identifier": "/dev/fake",
        },
    )
    assert response.status_code == 422


def test_the_live_view_reports_progress_for_a_relayed_recording(
    client, doctor_headers, patient
):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    client.post(
        f"/api/signals/recordings/{started['id']}/samples",
        headers=doctor_headers,
        json={"samples": {"EEG_FPZ": [1.0] * 50}},
    )
    body = client.get(
        f"/api/signals/recordings/{started['id']}/live", headers=doctor_headers
    ).json()

    assert body["channels"] is None, "the client holds the samples, not the server"
    assert body["progress"]["samples"] == 50
    assert "relayed by a client" in body["notice"]


def test_the_waveform_route_refuses_a_running_recording(client, doctor_headers, patient):
    started = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": ["EEG_FPZ"],
            "source": "HARDWARE",
        },
    ).json()
    response = client.get(
        f"/api/signals/recordings/{started['id']}/waveform", headers=doctor_headers
    )
    assert response.status_code == 409
    assert "/live" in response.json()["detail"]
