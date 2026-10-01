"""Running an observation end to end.

One clip arrives. It is checked against consent, decoded, measured, judged, offered to the
voice model, written down, and then — unless the clinician asked otherwise — deleted.

Two parts of that order are deliberate.

**Consent is resolved before the file is decoded.** Not after, and not alongside: a clip
nobody consented to should not be decoded at all, let alone measured.

**The two tracks are decoded independently.** A clip with a usable camera and a microphone
that was muted is an entirely ordinary thing to record, as is the reverse. So each track is
read in its own right and a failure on one is a note rather than a refusal, and the
measures that survive are the measures that survive.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.behaviour import features as feature_module
from backend.behaviour import inference, schema, storage
from backend.behaviour import quality as quality_module
from backend.behaviour import video as video_module
from backend.behaviour import voice as voice_module
from database.models import (
    BehaviourObservation,
    Patient,
    PatientBaseline,
    PatientConsent,
)
from security import audit

logger = logging.getLogger("painsense.behaviour")

#: The consent pointing a camera at a patient needs. Deliberately not the same scope as
#: the physiological recording: a face and a voice are identifying in a way an electrode
#: trace is not, and a patient who agreed to one has not agreed to the other.
CONSENT_SCOPE = "CAMERA_AND_MICROPHONE_OBSERVATION"

#: Largest clip accepted. Twenty seconds of 640x480 video with audio is a couple of
#: megabytes; this leaves room for a longer or sharper recording while refusing a file
#: that was never a clip.
MAX_CLIP_BYTES = 80 * 1024 * 1024

#: What a browser's recorder produces, plus the two containers a clinician is likely to
#: upload from a phone. The decoder is ffmpeg and would accept far more; the list is short
#: because every additional format is another thing to have tested.
ACCEPTED_MEDIA = {
    "video/webm": ".webm",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
}

NOTICE = (
    "A camera and a microphone measure behaviour: how open the eyes are, how often they "
    "close, what the pupils are doing, where the brow sits, and how the voice sounds. "
    "None of those is a pain measure. Every one of them also moves with fear, fatigue, "
    "room light, sedation and distance from the lens. The patient's own score is recorded "
    "separately and is never an input to any estimate."
)

#: What the patient is asked to do, shown in the interface and repeated in the report so
#: that a reading can be judged against the instruction it was taken under.
INSTRUCTION = (
    "Ask the patient to look at the camera with their eyes open and to speak or read "
    "aloud for the length of the recording. The eye measures are taken only from frames "
    "where both eyes are found open, so a patient who looks away or keeps their eyes shut "
    "produces no eye reading at all."
)


class ConsentMissing(RuntimeError):
    """No active consent covers pointing a camera at this patient."""


class ClipRejected(RuntimeError):
    """The upload is not something this module will decode."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def consent_for(db: Session, patient_id: uuid.UUID) -> PatientConsent | None:
    row = db.scalar(
        select(PatientConsent).where(
            PatientConsent.patient_id == patient_id,
            PatientConsent.scope == CONSENT_SCOPE,
        )
    )
    return row if row is not None and row.active else None


def baseline_for(patient: Patient) -> feature_module.Baseline:
    """This patient's resting behaviour, or an empty baseline."""
    row = patient.baseline
    if row is None:
        return feature_module.Baseline()
    return feature_module.Baseline(**row.behaviour)


def extension_for(media_type: str | None) -> str:
    """The suffix to write the upload under, which is how ffmpeg picks its demuxer.

    A clip written with no extension is usually still probed correctly, but not always, and
    a webm that ffmpeg decides is raw data produces an error about the file rather than
    about the recording.
    """
    if not media_type:
        raise ClipRejected("the upload carries no media type")
    base = media_type.split(";", 1)[0].strip().lower()
    if base not in ACCEPTED_MEDIA:
        raise ClipRejected(
            f"{base} is not a container this module decodes. Accepted: "
            + ", ".join(sorted(ACCEPTED_MEDIA))
        )
    return ACCEPTED_MEDIA[base]


def _read_tracks(
    path: Path, notes: list[str]
) -> tuple[video_module.VideoReading | None, voice_module.VoiceReading | None]:
    video: video_module.VideoReading | None = None
    voice: voice_module.VoiceReading | None = None
    try:
        video = video_module.read(path)
    except video_module.VideoUnreadable as exc:
        notes.append(f"no video was measured: {exc}")
    except Exception as exc:  # noqa: BLE001 - see below
        # Broad on purpose. Below this line is a third-party decoder and a cascade being
        # fed whatever a browser or a phone produced, and the failures that come back from
        # that are not an enumerable set. An unreadable video track must cost the video
        # measures and nothing else: the audio track is still worth measuring, the
        # observation is still worth storing, and the clinician needs to be told what
        # happened rather than shown a server error.
        logger.warning("video measurement failed for %s: %s", path.name, exc)
        notes.append(f"the video track could not be measured: {exc}")
    try:
        voice = voice_module.read(path)
    except voice_module.AudioUnreadable as exc:
        notes.append(f"no audio was measured: {exc}")
    except Exception as exc:  # noqa: BLE001 - as for the video track above
        logger.warning("voice measurement failed for %s: %s", path.name, exc)
        notes.append(f"the audio track could not be measured: {exc}")
    return video, voice


def record_baseline(
    db: Session, patient: Patient, measures: dict[str, float]
) -> PatientBaseline:
    """Store this patient's resting behaviour from an at-rest observation.

    Only the measures that were actually reported are written, and the rest are left as
    they were. A resting clip whose audio was unusable should set the eye values and leave
    a pitch recorded last week alone rather than erasing it.
    """
    row = patient.baseline
    if row is None:
        row = PatientBaseline(patient_id=patient.id, readings=0)
        db.add(row)
        db.flush()

    fields = {
        "eye_aperture_ratio": "resting_eye_aperture",
        "pupil_diameter_mm": "resting_pupil_mm",
        "blink_rate_per_min": "resting_blink_rate",
        "brow_gap_ratio": "resting_brow_gap",
        "f0_mean_hz": "resting_f0_hz",
        "intensity_db": "resting_intensity_db",
        "speech_rate_per_s": "resting_speech_rate",
    }
    written = 0
    for code, column in fields.items():
        value = measures.get(code)
        if value is not None:
            setattr(row, column, float(value))
            written += 1
    if written:
        row.behaviour_recorded_at = now()
    return row


def analyse(
    db: Session,
    patient: Patient,
    *,
    data: bytes,
    media_type: str | None,
    at_rest: bool = False,
    assessment_id: uuid.UUID | None = None,
    retain_media: bool = False,
    actor_id: uuid.UUID | None = None,
    workspace: Path | None = None,
) -> BehaviourObservation:
    """Measure one clip and store what came out of it."""
    if not data:
        raise ClipRejected("the upload is empty")
    if len(data) > MAX_CLIP_BYTES:
        raise ClipRejected(
            f"the upload is {len(data) / 1e6:.1f} MB, over the "
            f"{MAX_CLIP_BYTES / 1e6:.0f} MB limit"
        )
    suffix = extension_for(media_type)

    consent = consent_for(db, patient.id)
    if consent is None:
        raise ConsentMissing(
            "no active consent under "
            f"{CONSENT_SCOPE} covers recording this patient's camera and microphone. "
            "Record the consent first; nothing is decoded without it."
        )

    observation = BehaviourObservation(
        patient_id=patient.id,
        assessment_id=assessment_id,
        recorded_by=actor_id,
        consent_id=consent.id,
        at_rest=at_rest,
        media_type=media_type,
        media_bytes=len(data),
        media_sha256=storage.digest(data),
        feature_schema_version=schema.FEATURE_SCHEMA_VERSION,
    )
    db.add(observation)
    db.flush()

    notes: list[str] = []
    directory = workspace or Path(tempfile.gettempdir())
    scratch = directory / f"observation-{observation.id.hex}{suffix}"
    try:
        scratch.write_bytes(data)
        video, voice = _read_tracks(scratch, notes)
    finally:
        scratch.unlink(missing_ok=True)

    report = quality_module.assess(video, voice)
    baseline = baseline_for(patient)
    measured = feature_module.extract(
        video=video, voice=voice, report=report, baseline=baseline
    )
    estimate = inference.estimate(
        db, measured.cepstral, voice_usable=report.allows(schema.VOICE)
    )

    observation.has_video = video is not None
    observation.has_audio = voice is not None
    observation.duration_seconds = report.duration_seconds
    observation.frame_rate = report.frame_rate or None
    observation.frames_analysed = report.frames_analysed
    if video is not None:
        observation.frames_decoded = video.frames_decoded
        observation.frame_width = video.width or None
        observation.frame_height = video.height or None
        observation.eyes_calibrated = video.eyes_calibrated
    observation.quality = report.as_dict()
    observation.quality_verdict = report.verdict
    observation.usable_modalities = report.usable
    observation.measures = {
        name: round(value, 4) for name, value in sorted(measured.values.items())
    }
    observation.cepstral = {
        name: round(value, 4) for name, value in sorted(measured.cepstral.items())
    }
    observation.deltas = {
        name: round(value, 4) for name, value in sorted(measured.deltas.items())
    }
    observation.reference = dict(measured.reference)
    observation.absent = dict(measured.absent)
    observation.support = dict(measured.support)
    observation.summary = feature_module.summary(measured)
    observation.estimate_available = estimate.available
    observation.unavailable_reason = None if estimate.available else estimate.message
    observation.model_version = estimate.model_version
    observation.voice_pain_level = estimate.level
    observation.voice_pain_label = estimate.label
    observation.voice_confidence = estimate.level_error
    observation.notes = notes + list(report.findings) + list(measured.notes)

    if retain_media:
        name, wrapped = storage.retain(observation.id, data)
        observation.media_retained = True
        observation.storage_key = name
        observation.wrapped_key = wrapped
    else:
        observation.notes.append(
            "The clip was deleted once these measures were taken from it. Its digest is "
            "kept so the measures can be tied back to it if a copy is produced."
        )

    if at_rest:
        record_baseline(db, patient, measured.values)

    db.commit()
    db.refresh(observation)

    audit.record(
        db,
        event_type=audit.BEHAVIOUR_OBSERVED,
        actor_id=actor_id,
        resource="behaviour_observation",
        resource_id=str(observation.id),
        meta={
            "patient_id": str(patient.id),
            "quality": report.verdict,
            "usable": report.usable,
            "at_rest": at_rest,
            "retained": observation.media_retained,
            "measures": len(observation.measures),
        },
        ledger_payload={
            "observation_id": str(observation.id),
            "media_sha256": observation.media_sha256,
            "quality": report.verdict,
            "feature_schema_version": schema.FEATURE_SCHEMA_VERSION,
            "retained": observation.media_retained,
        },
    )
    return observation


def discard_media(db: Session, observation: BehaviourObservation, *, actor_id=None) -> None:
    """Delete a retained clip, keeping the measures and the digest.

    What withdrawing consent means for an observation already taken: the recording goes,
    the numbers derived from it and the record that it happened stay.
    """
    storage.discard(observation.storage_key)
    observation.media_retained = False
    observation.storage_key = None
    observation.wrapped_key = None
    observation.notes = list(observation.notes or []) + [
        f"The retained clip was deleted on {now().date().isoformat()}."
    ]
    db.commit()
    audit.record(
        db,
        event_type=audit.BEHAVIOUR_MEDIA_DISCARDED,
        actor_id=actor_id,
        resource="behaviour_observation",
        resource_id=str(observation.id),
        meta={"media_sha256": observation.media_sha256},
    )
