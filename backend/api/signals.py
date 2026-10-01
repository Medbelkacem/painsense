"""The EEG and EMG analysis API.

The workflow the brief describes, as four calls: start a recording, post sample blocks
while it runs, stop and analyse, read the report. A simulated recording collapses the first
three into one, because a simulator has no reason to stream.

`/reference` tells the interface up front whether a pain model exists. That matters for
honesty in the interface rather than only in the report: the button should not promise an
estimate the platform cannot produce, and the client should not have to infer that from a
failed analysis.
"""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.api import schemas
from backend.dependencies import ClinicalUser, CurrentUser, DbSession, ResearchUser, client_ip
from backend.signals import inference, schema, service, simulate, storage
from backend.signals.devices.base import DeviceUnavailable
from database.models import (
    Patient,
    RecordingState,
    SignalAnalysis,
    SignalRecording,
    SignalSource,
)
from security import audit

router = APIRouter(prefix="/api/signals", tags=["eeg and emg"])

#: Points per channel returned for display. Enough to see the shape of a trace in a browser
#: without shipping a quarter of a million floats to draw a few hundred pixels.
WAVEFORM_POINTS = 1200

NOTICE = (
    "EEG and EMG are recorded, quality-checked and reduced to standard spectral and "
    "amplitude features. Those features are not a pain measure: they move with arousal, "
    "attention, movement and electrode placement as well as with pain. The patient's own "
    "score is shown separately and is never an input to any estimate."
)


def _recording(db, recording_id: uuid.UUID) -> SignalRecording:
    row = db.scalar(
        select(SignalRecording)
        .where(SignalRecording.id == recording_id)
        .options(selectinload(SignalRecording.analyses))
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recording not found")
    return row


def _detail(recording: SignalRecording) -> schemas.SignalRecordingDetail:
    out = schemas.SignalRecordingDetail.model_validate(recording)
    out.quality = recording.quality or {}
    out.validation = recording.validation or {}
    out.files = recording.files or []
    out.analyses = [
        schemas.SignalAnalysisOut.model_validate(row) for row in recording.analyses
    ]
    return out


@router.get("/reference", response_model=schemas.SignalReferenceOut)
def reference(db: DbSession, user: CurrentUser) -> schemas.SignalReferenceOut:
    model = inference.find_model(db)
    return schemas.SignalReferenceOut(
        channels=[
            schemas.SignalChannelOut(
                code=entry.code,
                label=entry.label,
                modality=entry.modality,
                unit=entry.unit,
                saturation=entry.saturation,
                minimum_rate_hz=entry.minimum_rate_hz,
                primary=entry.modality in schema.PRIMARY_MODALITIES,
                note=entry.note,
            )
            for entry in schema.CHANNELS
        ],
        eeg_bands=[
            {"name": name, "low_hz": low, "high_hz": high}
            for name, low, high in schema.EEG_BANDS
        ],
        emg_band=list(schema.EMG_BAND),
        default_sample_rate_hz=schema.DEFAULT_SAMPLE_RATE_HZ,
        minimum_duration_seconds=schema.MINIMUM_DURATION_SECONDS,
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
        simulation_faults=list(simulate.FAULTS),
        model_available=model is not None,
        model_message=(
            f"Experimental model {model.version} is registered and active."
            if model
            else inference.UNAVAILABLE_MESSAGE
        ),
        notice=NOTICE,
    )


@router.get("/devices", response_model=schemas.DeviceScanOut)
def scan_devices(db: DbSession, user: ClinicalUser) -> schemas.DeviceScanOut:
    """Acquisition devices this server can currently see.

    Enumerating a serial bus is cheap; a BLE scan is not, and takes a few seconds. An empty
    list is the honest answer when nothing is attached, and the interface shows "Device not
    connected" on it rather than inferring that from a failed recording.
    """
    from backend.signals import devices

    found = devices.discover()
    return schemas.DeviceScanOut(
        adapters=[schemas.AdapterOut(**adapter.describe()) for adapter in devices.ADAPTERS],
        devices=[schemas.DeviceOut(**info.as_dict()) for info in found],
        connected=bool(found),
        notice=(
            "A device listed here was seen on a bus or advertised over BLE. Whether it is "
            "the amplifier it looks like, and whether electrodes are attached, is only "
            "known once a recording starts and the signal quality is measured."
        ),
    )


@router.post("/recordings", response_model=schemas.SignalRecordingDetail, status_code=201)
def start_recording(
    payload: schemas.RecordingStart,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.SignalRecordingDetail:
    """Start a recording. A simulated one is generated, stored and analysed immediately.

    Hardware recordings stay open and take sample blocks; there is no device protocol here
    because the browser or gateway that owns the device relays the samples.
    """
    if db.get(Patient, payload.patient_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")

    patient = db.get(Patient, payload.patient_id)
    try:
        started = service.start(
            db,
            patient=patient,
            source=payload.source,
            channels=payload.channels,
            channel_rates=payload.channel_rates,
            sample_rate_hz=payload.sample_rate_hz,
            device_label=payload.device_label
            or ("Software simulator" if payload.source is SignalSource.SIMULATION else None),
            sensor_status=payload.sensor_status,
            adapter=payload.adapter,
            device_identifier=payload.device_identifier,
            device_options=payload.device_options,
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc).strip("\"'")) from exc
    except DeviceUnavailable as exc:
        # The device was named and could not be opened. 409 rather than 422: the request was
        # well formed and the hardware is the problem.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)
        ) from exc
    recording = started.recording

    audit.record(
        db,
        event_type=audit.ASSESSMENT_CREATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="signal_recording",
        resource_id=str(recording.id),
        client_ip=client_ip(request),
        meta={
            "source": recording.source.value,
            "channels": recording.channels,
            "adapter": recording.adapter,
            "device": recording.device_identifier,
        },
    )

    if payload.source is SignalSource.SIMULATION:
        try:
            generated = simulate.generate(
                channels=list(payload.channels),
                rate=payload.sample_rate_hz,
                seconds=payload.simulate_seconds or 30.0,
                seed=payload.simulate_seed,
                faults=payload.simulate_faults,
            )
        except ValueError as exc:
            service.discard(db, recording, reason=str(exc))
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        service.append(db, recording, {code: list(values) for code, values in generated.items()})

    db.refresh(recording)
    return _detail(recording)


@router.post("/recordings/{recording_id}/samples", response_model=dict)
def append_samples(
    recording_id: uuid.UUID,
    payload: schemas.SampleBlock,
    db: DbSession,
    user: ClinicalUser,
) -> dict:
    recording = _recording(db, recording_id)
    try:
        added = service.append(db, recording, payload.samples)
    except service.RecordingClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except storage.StorageError as exc:
        # The block did not reach disk. Reported rather than swallowed: a client that keeps
        # streaming into a full volume would end with a recording whose sample count its
        # files cannot support.
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)
        ) from exc
    # Samples are written to the session files as they arrive rather than buffered, so what
    # is reported is what is on disk. There is no buffered count any more because there is
    # no buffer: an interrupted recording keeps everything posted up to that point.
    return {
        "recording_id": str(recording.id),
        "accepted_samples": added,
        "samples_written": recording.samples,
        "elapsed_seconds": round(
            (service.now() - recording.started_at).total_seconds(), 2
        ),
        "state": recording.state.value,
    }


@router.get("/recordings/{recording_id}/live", response_model=schemas.LiveViewOut)
def live_view(
    recording_id: uuid.UUID,
    db: DbSession,
    user: ClinicalUser,
    points: Annotated[int, Query(ge=50, le=2000)] = 600,
) -> schemas.LiveViewOut:
    """The most recent samples and the device's counters, while recording.

    Polled by the interface. Only a server-side acquisition has a live window here: a
    client-relayed recording holds its samples until it posts them, so `channels` is null and
    the progress counters are what the server knows.
    """
    recording = _recording(db, recording_id)
    window = service.live(recording, points=points)
    return schemas.LiveViewOut(
        recording_id=recording.id,
        source=recording.source,
        state=recording.state,
        channels=window["channels"] if window else None,
        decimation=window["decimation"] if window else None,
        rates=window["rates"] if window else (recording.channel_rates or {}),
        device=window["device"] if window else {"connected": False},
        progress=window["progress"] if window else service.progress(recording),
        notice=(
            window["notice"]
            if window
            else "This recording is relayed by a client; the server holds no live window."
        ),
    )


@router.post(
    "/recordings/{recording_id}/stop", response_model=schemas.SignalRecordingDetail
)
def stop_recording(
    recording_id: uuid.UUID,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.SignalRecordingDetail:
    """Stop acquisition, flush the files, write the metadata and validate.

    Does not analyse. The recording is left `SAVED`, and `POST .../analyze` runs the
    signal processing — separately, so a session can be recorded at the bedside and analysed
    later, and so a failed analysis does not put the recording itself in doubt.
    """
    recording = _recording(db, recording_id)
    try:
        service.stop(db, recording)
    except service.NoSamples as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except service.RecordingClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)
        ) from exc

    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="signal_recording",
        resource_id=str(recording.id),
        client_ip=client_ip(request),
        meta={
            "action": "stopped",
            "samples": recording.samples,
            "dropped": recording.dropped_samples,
            "intact": (recording.validation or {}).get("intact"),
        },
    )
    db.refresh(recording)
    return _detail(recording)


@router.post(
    "/recordings/{recording_id}/analyze", response_model=schemas.SignalRecordingDetail
)
def analyse_recording(
    recording_id: uuid.UUID,
    payload: schemas.AnalyseRequest,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.SignalRecordingDetail:
    """Read the saved recording back, assess quality, extract features, ask a model.

    Re-runnable: analysing the same recording again adds another analysis rather than
    replacing the first, so a later model can be applied to an existing recording without
    re-recording the patient.
    """
    recording = _recording(db, recording_id)
    try:
        analysis = service.analyse(
            db, recording, reported_nrs=payload.reported_nrs, actor_id=user.id
        )
    except service.NotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    audit.record(
        db,
        event_type=audit.ASSESSMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="signal_recording",
        resource_id=str(recording.id),
        client_ip=client_ip(request),
        meta={
            "action": "analysed",
            "quality": recording.quality_verdict,
            "features": analysis.feature_count,
            "estimate_available": analysis.estimate_available,
        },
    )
    db.refresh(recording)
    return _detail(recording)


@router.post(
    "/recordings/{recording_id}/discard", response_model=schemas.SignalRecordingOut
)
def discard_recording(
    recording_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.SignalRecordingOut:
    recording = _recording(db, recording_id)
    if recording.state is RecordingState.ANALYSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This recording has been analysed and is part of the history",
        )
    service.discard(db, recording, reason="discarded by the operator")
    return schemas.SignalRecordingOut.model_validate(recording)


@router.get("/recordings", response_model=list[schemas.SignalRecordingOut])
def list_recordings(
    db: DbSession,
    user: ClinicalUser,
    patient_id: uuid.UUID | None = None,
    source: SignalSource | None = None,
    state: RecordingState | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[schemas.SignalRecordingOut]:
    filters = []
    if patient_id:
        filters.append(SignalRecording.patient_id == patient_id)
    if source:
        filters.append(SignalRecording.source == source)
    if state:
        filters.append(SignalRecording.state == state)
    rows = db.scalars(
        select(SignalRecording)
        .where(*filters)
        .order_by(SignalRecording.started_at.desc())
        .limit(limit)
    )
    return [schemas.SignalRecordingOut.model_validate(row) for row in rows]


@router.get("/recordings/{recording_id}", response_model=schemas.SignalRecordingDetail)
def read_recording(
    recording_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.SignalRecordingDetail:
    return _detail(_recording(db, recording_id))


@router.get(
    "/recordings/{recording_id}/waveform", response_model=schemas.SignalWaveformOut
)
def waveform(
    recording_id: uuid.UUID,
    db: DbSession,
    user: ClinicalUser,
    points: Annotated[int, Query(ge=50, le=5000)] = WAVEFORM_POINTS,
) -> schemas.SignalWaveformOut:
    """Decimated traces for display.

    Decimated by striding, and the factor is returned. A reader of the trace should know it
    is not sample-accurate: a stride of 200 over a 512 Hz EMG hides most of its content, and
    the features were computed from the stored samples, not from this.
    """
    recording = _recording(db, recording_id)
    if recording.state is RecordingState.RECORDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "This recording is still running. Use /live for the trace while recording; "
                "this route reads the stored files, which are still being written."
            ),
        )
    if not recording.storage_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="No samples are stored for this recording"
        )
    stored, _rates = storage.read_samples(recording.storage_key)
    length = max((len(values) for values in stored.values()), default=0)
    if length == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This recording's files hold no sample",
        )
    stride = max(1, length // points)
    return schemas.SignalWaveformOut(
        recording_id=recording.id,
        source=recording.source,
        sample_rate_hz=recording.sample_rate_hz,
        points_per_channel=len(next(iter(stored.values()))[::stride]) if stored else 0,
        decimation=stride,
        channels={
            # A gap travels as null rather than as a number. Sending 0 for a dropped-out
            # lead would draw a flat line that looks like a measurement.
            code: [
                None if math.isnan(float(value)) else round(float(value), 4)
                for value in values[::stride]
            ]
            for code, values in stored.items()
        },
        notice=(
            f"Decimated by {stride}x for display. Features were computed from the stored "
            "samples, not from this trace."
        ),
    )


@router.get("/analyses", response_model=list[schemas.SignalAnalysisOut])
def list_analyses(
    db: DbSession,
    user: ResearchUser,
    patient_id: uuid.UUID | None = None,
    estimate_available: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[schemas.SignalAnalysisOut]:
    query = select(SignalAnalysis).join(SignalRecording)
    if patient_id:
        query = query.where(SignalRecording.patient_id == patient_id)
    if estimate_available is not None:
        query = query.where(SignalAnalysis.estimate_available.is_(estimate_available))
    rows = db.scalars(query.order_by(SignalAnalysis.analysed_at.desc()).limit(limit))
    return [schemas.SignalAnalysisOut.model_validate(row) for row in rows]
