"""The recording lifecycle: connect, record, stop, validate, analyse.

The workflow is five steps and they are deliberately separate calls:

*Start* opens the session files and, for a hardware recording, opens the device and starts
an acquisition thread. For a client that owns the device itself — a browser over Web Serial —
no thread is started and the client posts blocks instead.

*Stop* stops acquisition, closes the files, measures what is on disk and writes the metadata.
It does not analyse. A session can be recorded at the bedside and analysed later, and a
failed analysis should not put the recording in doubt.

*Validate* checks the files are intact: every declared channel present, the sample indices
monotonic, the row counts matching the metadata, the digests recomputable. This is about the
recording, not the signal.

*Analyse* reads the files back, assesses signal quality per rate group, extracts features and
offers them to a model. Separate from stop so it can be re-run — a later model should be able
to analyse an existing recording without re-recording the patient.

Rates are per channel throughout. EEG at 250 Hz beside surface EMG at 1 kHz is the normal
case, so quality and features are computed per rate group and merged, never by resampling one
onto the other's clock.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from database.models import (
    Patient,
    PatientConsent,
    RecordingState,
    SignalAnalysis,
    SignalRecording,
    SignalSource,
)
from backend.signals import acquisition, inference, integrity, schema, storage
from backend.signals import features as feature_module
from backend.signals import quality as quality_module
from backend.signals.devices.base import DeviceUnavailable

logger = logging.getLogger("painsense.signals")

STALE_AFTER = timedelta(minutes=30)

#: The consent a recording of face-free physiological signals needs. Named so the same scope
#: is asked for everywhere rather than spelled differently per call site.
CONSENT_SCOPE = "PHYSIOLOGICAL_RECORDING"

#: Blocks posted by a client are buffered only between arriving and being written, so this is
#: a guard against one absurd request rather than a session budget.
MAX_BLOCK_SAMPLES = 500_000


class RecordingClosed(RuntimeError):
    """The recording is no longer accepting samples."""


class NoSamples(RuntimeError):
    """Stop was called on a recording that never received a sample."""


class NotReady(RuntimeError):
    """The recording is not in a state this step can act on."""


def now() -> datetime:
    return datetime.now(timezone.utc)


# --- writers for client-relayed recordings --------------------------------------------------


class _Writers:
    """Open writers for recordings whose samples arrive by API rather than from a device."""

    def __init__(self) -> None:
        self._writers: dict[str, storage.SessionWriter] = {}
        self._lock = threading.Lock()

    def add(self, recording_id, writer: storage.SessionWriter) -> None:
        with self._lock:
            self._writers[str(recording_id)] = writer

    def get(self, recording_id) -> storage.SessionWriter | None:
        with self._lock:
            return self._writers.get(str(recording_id))

    def pop(self, recording_id) -> storage.SessionWriter | None:
        with self._lock:
            return self._writers.pop(str(recording_id), None)


writers = _Writers()


# --- starting ---------------------------------------------------------------------------------


def participant_ref(patient: Patient) -> str:
    """The pseudonymous directory name for a patient.

    The patient's id, which carries no name and is already the platform's internal handle.
    The code is deliberately not used: it is an MRN-shaped value a site may consider
    identifying, and a directory listing should not be a patient index.
    """
    return patient.id.hex


def consent_for(db: DbSession, patient_id, scope: str = CONSENT_SCOPE) -> PatientConsent | None:
    row = db.scalar(
        select(PatientConsent).where(
            PatientConsent.patient_id == patient_id, PatientConsent.scope == scope
        )
    )
    return row if row is not None and row.active else None


def resolve_rates(channels: list[str], rates: dict[str, float] | None, fallback: float) -> dict:
    """A rate for every channel, from what the caller gave and the channel's own minimum.

    A caller that supplies one rate for everything gets it applied to everything, which is
    right for a single amplifier. A caller that supplies per-channel rates gets those. A
    channel with neither falls back, and the quality check later flags it if the fallback is
    below what the channel needs.
    """
    rates = rates or {}
    return {code: float(rates.get(code, fallback)) for code in channels}


@dataclass(frozen=True)
class Started:
    recording: SignalRecording
    runner: acquisition.Runner | None


def start(
    db: DbSession,
    *,
    patient: Patient,
    source: SignalSource,
    channels: list[str],
    channel_rates: dict[str, float] | None = None,
    sample_rate_hz: float = schema.DEFAULT_SAMPLE_RATE_HZ,
    device_label: str | None = None,
    sensor_status: dict | None = None,
    adapter: str | None = None,
    device_identifier: str | None = None,
    device_options: dict | None = None,
    actor_id=None,
) -> Started:
    """Open a recording, and the device behind it where this process owns one."""
    unknown = [code for code in channels if code not in schema.CHANNEL_BY_CODE]
    if unknown:
        raise ValueError(f"unknown channel(s): {', '.join(unknown)}")
    if not channels:
        raise ValueError("a recording needs at least one channel")

    primary = [
        code
        for code in channels
        if schema.CHANNEL_BY_CODE[code].modality in schema.PRIMARY_MODALITIES
    ]
    if not primary:
        raise ValueError(
            "a recording needs at least one EEG or EMG channel; this analysis is of those "
            "and the other channels are supporting information"
        )

    rates = resolve_rates(channels, channel_rates, sample_rate_hz)
    if any(rate <= 0 for rate in rates.values()):
        raise ValueError("every channel needs a positive sampling rate")

    consent = consent_for(db, patient.id)
    recording = SignalRecording(
        patient_id=patient.id,
        source=source,
        state=RecordingState.RECORDING,
        device_label=device_label,
        adapter=adapter,
        device_identifier=device_identifier,
        sample_rate_hz=acquisition.primary_rate(rates),
        channel_rates=rates,
        channels=list(channels),
        sensor_status=sensor_status or {code: "declared" for code in channels},
        participant_ref=participant_ref(patient),
        consent_id=consent.id if consent else None,
        recorded_by=actor_id,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)

    key = storage.session_key(recording.participant_ref, recording.id.hex)
    recording.storage_key = key
    db.commit()

    try:
        writer = storage.SessionWriter(
            key=key, channels=list(channels), channel_rates=rates
        ).open()
    except storage.StorageError as exc:
        recording.state = RecordingState.FAILED
        recording.error = f"the session files could not be opened: {exc}"
        db.commit()
        raise

    runner = None
    if adapter and device_identifier:
        from backend.signals import devices

        try:
            device = devices.get(adapter).open(device_identifier, **(device_options or {}))
        except (DeviceUnavailable, KeyError) as exc:
            writer.close()
            storage.discard(key)
            recording.state = RecordingState.FAILED
            recording.error = str(exc)
            db.commit()
            raise
        recording.device_label = recording.device_label or device.info.label
        db.commit()
        runner = acquisition.Runner(session=device, writer=writer, channel_rates=rates)
        acquisition.runners.add(recording.id, runner)
    else:
        writers.add(recording.id, writer)

    return Started(recording=recording, runner=runner)


# --- samples relayed by a client -----------------------------------------------------------------


def append(
    db: DbSession, recording: SignalRecording, block: dict[str, list[float]]
) -> int:
    """Write one block of client-relayed samples straight to the session files."""
    if recording.state is not RecordingState.RECORDING:
        raise RecordingClosed(
            f"this recording is {recording.state.value.lower()} and takes no more samples"
        )
    if acquisition.runners.get(recording.id) is not None:
        raise RecordingClosed(
            "this recording is acquiring from a device on the server; it does not accept "
            "relayed samples as well, because the two sample streams could not be ordered"
        )
    unknown = [code for code in block if code not in recording.channels]
    if unknown:
        raise ValueError(f"channel(s) not opened on this recording: {', '.join(unknown)}")

    writer = writers.get(recording.id)
    if writer is None:
        raise RecordingClosed(
            "this recording is not open on this server. A recording has to be started, "
            "streamed and stopped against the same process."
        )

    total = sum(len(values) for values in block.values())
    if total > MAX_BLOCK_SAMPLES:
        raise ValueError(f"{total} samples in one block; post smaller blocks as they arrive")

    samples = {code: np.asarray(values, dtype=float) for code, values in block.items()}
    length = max((len(values) for values in samples.values()), default=0)
    if length == 0:
        return 0

    start_index = recording.samples
    indices = np.arange(start_index, start_index + length, dtype=np.int64)
    rate = acquisition.primary_rate(recording.channel_rates or {})
    anchor = recording.started_at.timestamp()
    timestamps = (
        np.rint(anchor * 1e9 + indices * (1e9 / rate)).astype(np.int64)
        if rate > 0
        else np.full(length, round(anchor * 1e9), dtype=np.int64)
    )

    writer.append(samples, indices=indices, timestamps=timestamps)
    recording.samples += length
    db.commit()
    return length


def progress(recording: SignalRecording) -> dict:
    runner = acquisition.runners.get(recording.id)
    if runner is not None:
        return runner.progress.as_dict()
    return {
        "samples": recording.samples,
        "rows_written": recording.samples,
        "dropped_samples": recording.dropped_samples,
        "invalid_packets": recording.invalid_packets,
        "reconnects": recording.reconnects,
        "elapsed_seconds": round((now() - recording.started_at).total_seconds(), 2),
        "stalled_for_seconds": None,
        "error": recording.error,
        "finished": recording.state is not RecordingState.RECORDING,
    }


def live(recording: SignalRecording, *, points: int = 600) -> dict | None:
    runner = acquisition.runners.get(recording.id)
    return runner.live(points=points) if runner is not None else None


# --- stopping ---------------------------------------------------------------------------------------


def stop(db: DbSession, recording: SignalRecording) -> SignalRecording:
    """Stop acquisition, close the files, measure what is on disk and write the metadata."""
    if recording.state not in (RecordingState.RECORDING, RecordingState.PROCESSING):
        raise RecordingClosed(f"this recording is already {recording.state.value.lower()}")

    recording.state = RecordingState.PROCESSING
    recording.stopped_at = now()
    db.commit()

    runner = acquisition.runners.pop(recording.id)
    if runner is not None:
        finished = runner.stop()
        recording.samples = finished.samples
        recording.dropped_samples = finished.dropped
        recording.invalid_packets = finished.invalid_packets
        recording.reconnects = finished.reconnects
        if finished.error:
            recording.error = finished.error
    else:
        writer = writers.pop(recording.id)
        if writer is not None:
            writer.close()

    key = recording.storage_key
    files = storage.file_manifest(key) if key else []
    data_files = [entry for entry in files if entry["name"].endswith(".csv")]
    if not data_files or all(entry["bytes"] <= 64 for entry in data_files):
        # Only headers were written, so no sample ever arrived.
        storage.discard(key)
        recording.state = RecordingState.DISCARDED
        recording.error = recording.error or (
            "the recording was stopped without receiving any sample. Nothing was stored."
        )
        recording.files = []
        db.commit()
        raise NoSamples(recording.error)

    rate = acquisition.primary_rate(recording.channel_rates or {})
    recording.duration_seconds = round(recording.samples / rate, 3) if rate > 0 else 0.0

    storage.write_metadata(
        key,
        {
            "session_id": str(recording.id),
            "participant_ref": recording.participant_ref,
            "source": recording.source.value,
            "adapter": recording.adapter,
            "device_label": recording.device_label,
            "device_identifier": recording.device_identifier,
            "channels": recording.channels,
            "channel_rates": recording.channel_rates,
            "units": {
                code: schema.CHANNEL_BY_CODE[code].unit
                for code in recording.channels
                if code in schema.CHANNEL_BY_CODE
            },
            "started_at": recording.started_at.isoformat(),
            "stopped_at": recording.stopped_at.isoformat(),
            "duration_seconds": recording.duration_seconds,
            "samples": recording.samples,
            "dropped_samples": recording.dropped_samples,
            "invalid_packets": recording.invalid_packets,
            "reconnects": recording.reconnects,
            "consent": {
                "scope": CONSENT_SCOPE,
                "recorded": recording.consent_id is not None,
                "consent_id": str(recording.consent_id) if recording.consent_id else None,
            },
            "provenance": (
                "synthetic simulation"
                if recording.source is SignalSource.SIMULATION
                else "hardware acquisition"
            ),
        },
    )
    recording.files = storage.file_manifest(key)
    recording.bytes = sum(entry["bytes"] for entry in recording.files)
    recording.sha256 = integrity.digest_of_session(recording.files)
    recording.state = RecordingState.SAVED
    db.commit()

    validate(db, recording)
    return recording


# --- validation ------------------------------------------------------------------------------------


def validate(db: DbSession, recording: SignalRecording) -> dict:
    """Check the files are intact and complete. About the recording, not the signal."""
    findings: list[str] = []
    key = recording.storage_key
    samples, rates = ({}, {})
    if key:
        try:
            samples, rates = storage.read_samples(key)
        except (storage.StorageError, OSError, ValueError) as exc:
            findings.append(f"the stored files could not be read back: {exc}")

    missing = [code for code in recording.channels if code not in samples]
    if missing:
        findings.append("declared but absent from the files: " + ", ".join(sorted(missing)))

    lengths = {code: len(values) for code, values in samples.items()}
    if lengths and len(set(lengths.values())) > 1:
        # Expected where rates differ; only worth noting when they do not.
        distinct_rates = {rates.get(code) for code in lengths}
        if len(distinct_rates) <= 1:
            findings.append(
                "channels at the same rate hold different numbers of samples: "
                + ", ".join(f"{code}={count}" for code, count in sorted(lengths.items()))
            )

    gaps = {
        code: int(np.isnan(values).sum())
        for code, values in samples.items()
        if np.isnan(values).any()
    }
    if gaps:
        findings.append(
            "gaps present (recorded as missing, not as zero): "
            + ", ".join(f"{code}={count}" for code, count in sorted(gaps.items()))
        )
    if recording.dropped_samples:
        findings.append(
            f"{recording.dropped_samples} sample(s) the device numbered never arrived"
        )
    if recording.invalid_packets:
        findings.append(f"{recording.invalid_packets} frame(s) failed protocol validation")

    recomputed = storage.file_manifest(key) if key else []
    if recording.files and integrity.digest_of_session(recomputed) != recording.sha256:
        findings.append(
            "the files on disk no longer match the digest recorded when they were written"
        )

    report = {
        "checked_at": now().isoformat(),
        "channels_declared": list(recording.channels),
        "channels_present": sorted(samples),
        "samples_per_channel": lengths,
        "rates": rates,
        "gaps": gaps,
        "intact": not findings,
        "findings": findings,
    }
    recording.validation = report
    recording.validated_at = now()
    db.commit()
    return report


# --- analysis ----------------------------------------------------------------------------------------


def _rate_groups(samples: dict[str, np.ndarray], rates: dict[str, float]) -> dict:
    """Channels grouped by sampling rate.

    Quality and features are computed per group. Running a 1 kHz EMG through a 250 Hz
    assumption would put its median frequency in the wrong place, and resampling it onto the
    EEG clock to avoid that would alter the signal the features describe.
    """
    groups: dict[float, dict[str, np.ndarray]] = {}
    for code, values in samples.items():
        rate = float(rates.get(code) or 0.0)
        if rate <= 0:
            continue
        groups.setdefault(rate, {})[code] = values
    return groups


def analyse(
    db: DbSession,
    recording: SignalRecording,
    *,
    reported_nrs: float | None = None,
    actor_id=None,
) -> SignalAnalysis:
    """Read the recording back, assess quality per rate group, extract features, ask a model."""
    if recording.state not in (RecordingState.SAVED, RecordingState.ANALYSED):
        raise NotReady(
            f"this recording is {recording.state.value.lower()}; stop it before analysing"
        )
    if not recording.storage_key:
        raise NotReady("no samples are stored for this recording")

    samples, rates = storage.read_samples(recording.storage_key)
    if not samples:
        raise NotReady("the stored files hold no channel")

    groups = _rate_groups(samples, rates)
    merged_channels: list[quality_module.ChannelQuality] = []
    merged_findings: list[str] = []
    all_features: dict[str, float] = {}
    derived: list[str] = []
    skipped: dict[str, str] = {}
    duration = 0.0

    for rate, group in sorted(groups.items()):
        length = max((len(values) for values in group.values()), default=0)
        group_duration = length / rate if rate > 0 else 0.0
        duration = max(duration, group_duration)
        report = quality_module.assess(group, rate=rate, duration=group_duration)
        merged_channels.extend(report.channels)
        merged_findings.extend(
            f"at {rate:g} Hz: {finding}" for finding in report.findings
        )
        extracted = feature_module.extract(group, rate=rate, report=report)
        all_features.update(extracted.values)
        derived.extend(extracted.derived_from)
        skipped.update(extracted.skipped)

    combined = quality_module.Report(
        sample_rate_hz=acquisition.primary_rate(rates),
        duration_seconds=duration,
        channels=merged_channels,
        findings=merged_findings,
    )
    recording.quality = combined.as_dict()
    recording.quality_verdict = combined.verdict
    if recording.storage_key:
        storage.write_quality(recording.storage_key, combined.as_dict())
    db.commit()

    bundle = feature_module.FeatureSet(
        values=all_features, derived_from=sorted(set(derived)), skipped=skipped
    )
    summary = feature_module.summary(bundle)
    estimate = inference.estimate(db, all_features, quality_verdict=combined.verdict)

    analysis = SignalAnalysis(
        recording_id=recording.id,
        analysed_by=actor_id,
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
        feature_count=len(all_features),
        features={name: round(value, 6) for name, value in all_features.items()},
        summary=summary,
        derived_from=bundle.derived_from,
        skipped_channels=skipped,
        heart_rate_bpm=summary.get("heart_rate_bpm"),
        hrv_rmssd_ms=summary.get("hrv_rmssd_ms"),
        skin_conductance_us=summary.get("skin_conductance_us"),
        respiration_per_min=summary.get("respiration_per_min"),
        estimate_available=estimate.available,
        unavailable_reason=None if estimate.available else inference.UNAVAILABLE_MESSAGE,
        model_version=estimate.model_version,
        pain_score=estimate.pain_score,
        pain_category=estimate.category,
        scale=estimate.scale,
        uncertainty=estimate.uncertainty,
        interval_low=estimate.interval[0] if estimate.interval else None,
        interval_high=estimate.interval[1] if estimate.interval else None,
        reported_nrs=reported_nrs,
        notes=[
            *bundle.notes,
            *estimate.limitations,
            (
                f"Quality and features were computed per sampling rate across "
                f"{len(groups)} rate group(s); no channel was resampled onto another's "
                "clock."
            ),
        ],
    )
    db.add(analysis)
    recording.state = RecordingState.ANALYSED
    db.commit()
    db.refresh(analysis)
    return analysis


# --- discarding and sweeping --------------------------------------------------------------------------


def discard(db: DbSession, recording: SignalRecording, *, reason: str) -> SignalRecording:
    runner = acquisition.runners.pop(recording.id)
    if runner is not None:
        runner.stop()
    writer = writers.pop(recording.id)
    if writer is not None:
        writer.close()
    if recording.storage_key:
        storage.discard(recording.storage_key)
        recording.storage_key = None
    recording.files = []
    recording.sha256 = None
    recording.state = RecordingState.DISCARDED
    recording.stopped_at = recording.stopped_at or now()
    recording.error = reason
    db.commit()
    return recording


def sweep_stale(db: DbSession, *, older_than: timedelta = STALE_AFTER) -> int:
    """Close recordings left open, so the history has no permanently 'recording' rows."""
    cutoff = now() - older_than
    rows = db.scalars(
        select(SignalRecording).where(
            SignalRecording.state == RecordingState.RECORDING,
            SignalRecording.started_at < cutoff,
        )
    ).all()
    for row in rows:
        discard(
            db,
            row,
            reason=(
                "left open with no stop; closed automatically. Samples written before the "
                "sweep are on disk but the session has no metadata or quality report."
            ),
        )
    if rows:
        logger.info("closed %d abandoned signal recording(s)", len(rows))
    return len(rows)
