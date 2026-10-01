"""Whether an observation is good enough for its measures to mean anything.

A camera pointed at a patient in a ward produces a great deal of material that looks like
data and is not. The patient looked at the clinician instead of the lens. The window blind
was open behind them. They had their eyes shut because they were asleep. The microphone was
the laptop's and the trolley was being wheeled past. Each of those yields numbers, and each
of those numbers is about something other than pain.

So quality is settled before any measure is reported, it is settled per modality, and the
verdict names what failed. A clip with a clean face and a useless audio track is a normal
thing to record and the facial measures from it are fine.

**The eyes-open share is a gate, not a score.** The patient is asked to look at the camera
with their eyes open, and the eye measures — aperture, pupil, gaze — exist only for the
frames where both eyes were found open. Below a floor of such frames there is nothing to
average and the eye modality is refused outright, rather than reporting a mean of four
frames as though it were a mean of two hundred. A sleeping or sedated patient therefore
gets no eye reading, which is the correct answer: what there is to see is the closure
itself, and that is reported separately and does need the eyes to be open to be counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.behaviour import schema
from backend.behaviour import video as video_module
from backend.behaviour.video import VideoReading
from backend.behaviour.voice import VoiceReading

GOOD = "GOOD"
ADEQUATE = "ADEQUATE"
POOR = "POOR"
UNUSABLE = "UNUSABLE"

#: Worst-last, so a summary is the worst verdict among the modalities present.
ORDER = (GOOD, ADEQUATE, POOR, UNUSABLE)

#: Share of analysed frames that must hold a front-facing view before the facial measures
#: are worth averaging.
FACE_SHARE = {GOOD: 0.75, ADEQUATE: 0.50, POOR: 0.25}

#: Share of analysed frames that must hold both eyes open. The gate.
EYES_OPEN_SHARE = {GOOD: 0.60, ADEQUATE: 0.35, POOR: 0.20}

#: Fewest open-eye frames an average may be taken over, whatever the share. Twenty frames
#: at the analysis rate is two seconds of looking at the camera.
MINIMUM_OPEN_FRAMES = 20

#: Share of the voiced time that must be present before the voice measures are reported.
#: A patient who said nothing has no voice measures, which is not a fault of the recording.
VOICED_SHARE = {GOOD: 0.25, ADEQUATE: 0.10, POOR: 0.03}

#: A recording whose peak sample is at or above this is clipped, and the amplitude measures
#: taken from it — shimmer, loudness — are flattened by the ceiling rather than measured.
CLIPPING_PEAK = 0.99
CLIPPING_SHARE_POOR = 0.001

#: Harmonics-to-noise below this over the voiced frames means the room is louder than the
#: patient.
NOISY_HNR_DB = 3.0


@dataclass
class ModalityQuality:
    modality: str
    verdict: str
    findings: list[str] = field(default_factory=list)
    #: The figures the verdict was reached on, for a reader who wants to see why.
    evidence: dict[str, float] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.verdict in (GOOD, ADEQUATE)

    def as_dict(self) -> dict:
        return {
            "modality": self.modality,
            "verdict": self.verdict,
            "usable": self.usable,
            "findings": self.findings,
            "evidence": {name: round(value, 4) for name, value in self.evidence.items()},
        }


@dataclass
class Report:
    duration_seconds: float
    frame_rate: float = 0.0
    frames_analysed: int = 0
    modalities: list[ModalityQuality] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        present = [item.verdict for item in self.modalities]
        return max(present, key=ORDER.index) if present else UNUSABLE

    @property
    def usable(self) -> list[str]:
        return [item.modality for item in self.modalities if item.usable]

    def of(self, modality: str) -> ModalityQuality | None:
        return next((item for item in self.modalities if item.modality == modality), None)

    def allows(self, modality: str) -> bool:
        found = self.of(modality)
        return found is not None and found.usable

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "duration_seconds": round(self.duration_seconds, 2),
            "frame_rate": round(self.frame_rate, 2),
            "frames_analysed": self.frames_analysed,
            "usable_modalities": self.usable,
            "modalities": [item.as_dict() for item in self.modalities],
            "findings": self.findings,
        }


def _tier(value: float, thresholds: dict[str, float]) -> str:
    for verdict in (GOOD, ADEQUATE, POOR):
        if value >= thresholds[verdict]:
            return verdict
    return UNUSABLE


def _worse(current: str, candidate: str) -> str:
    return max((current, candidate), key=ORDER.index)


def _nanmean(values: list[float]) -> float:
    finite = [value for value in values if not np.isnan(value)]
    return float(np.mean(finite)) if finite else float("nan")


def _face_quality(reading: VideoReading) -> ModalityQuality:
    analysed = max(reading.analysed, 1)
    with_face = reading.with_face
    share = len(with_face) / analysed
    result = ModalityQuality(schema.FACE, _tier(share, FACE_SHARE))
    result.evidence["face_share"] = share

    if result.verdict == UNUSABLE:
        result.findings.append(
            f"a front-facing view was found in {share:.0%} of the frames. Below "
            f"{FACE_SHARE[POOR]:.0%} there is no face to measure — the patient was turned "
            "away, or out of the frame"
        )
        return result
    if share < FACE_SHARE[GOOD]:
        result.findings.append(
            f"a front-facing view was found in {share:.0%} of the frames; the facial "
            "measures are averages over those"
        )

    sharpness = _nanmean([frame.sharpness for frame in with_face])
    brightness = _nanmean([frame.brightness for frame in with_face])
    result.evidence["sharpness"] = sharpness
    result.evidence["brightness"] = brightness

    if not np.isnan(sharpness) and sharpness < video_module.SHARPNESS_FLOOR:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"the face is out of focus or motion-blurred (detail {sharpness:.0f}, floor "
            f"{video_module.SHARPNESS_FLOOR:g}); an edge measured in it is a guess"
        )
    low, high = video_module.BRIGHTNESS_RANGE
    if not np.isnan(brightness) and not low <= brightness <= high:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"the face is {'under' if brightness < low else 'over'}-exposed (mean level "
            f"{brightness:.0f} of 255)"
        )
    return result


def _eye_quality(reading: VideoReading) -> ModalityQuality:
    analysed = max(reading.analysed, 1)
    open_frames = reading.with_eyes_open
    share = len(open_frames) / analysed
    result = ModalityQuality(schema.EYE, _tier(share, EYES_OPEN_SHARE))
    result.evidence["eyes_open_share"] = share
    result.evidence["open_frames"] = float(len(open_frames))

    if result.verdict == UNUSABLE:
        result.findings.append(
            f"both eyes were found open in {share:.0%} of the frames, below the "
            f"{EYES_OPEN_SHARE[POOR]:.0%} the eye measures need. The patient has to be "
            "looking at the camera with their eyes open for an aperture or a pupil to be "
            "measured at all"
        )
        return result
    if len(open_frames) < MINIMUM_OPEN_FRAMES:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"only {len(open_frames)} frames held both eyes open. An average over so few "
            "is a reading of a moment, not of the window"
        )
    elif share < EYES_OPEN_SHARE[GOOD]:
        result.findings.append(
            f"both eyes were found open in {share:.0%} of the frames; the eye measures are "
            "averages over those"
        )

    if not reading.eyes_calibrated:
        # The eye windows and the iris width came from the anatomical average rather than
        # from this patient. Still usable — the width only has to separate an iris from an
        # eyebrow — but a reader should know the scale was assumed.
        result.verdict = _worse(result.verdict, ADEQUATE)
        result.findings.append(
            "this patient's own eyes were never found wide open, so the eye windows and "
            "the iris width come from the average proportions of a face. The millimetre "
            "figures carry that assumption. Asking the patient to look at the camera with "
            "their eyes fully open, once, removes it"
        )

    radii = [
        value
        for frame in open_frames
        for value in (frame.left.iris_radius_px, frame.right.iris_radius_px)
        if value > 0
    ]
    if radii:
        median = float(np.median(radii))
        result.evidence["iris_radius_px"] = median
        if median < schema.MINIMUM_IRIS_RADIUS_PX:
            result.verdict = _worse(result.verdict, POOR)
            result.findings.append(
                f"the iris spans {median * 2:.0f} pixels. The patient is too far from the "
                "camera, or the camera's resolution is too low, for the millimetre scale "
                "to carry"
            )

    if reading.frame_rate and reading.frame_rate < schema.MINIMUM_FRAME_RATE:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"at {reading.frame_rate:.0f} frames a second a blink falls between two frames, "
            "so the blink rate and the closure durations are not reliable"
        )
    return result


def _voice_quality(reading: VoiceReading) -> ModalityQuality:
    voiced = reading.voiced
    share = float(voiced.mean()) if voiced.size else 0.0
    result = ModalityQuality(schema.VOICE, _tier(share, VOICED_SHARE))
    result.evidence["voiced_share"] = share
    result.evidence["duration_seconds"] = reading.duration_seconds
    result.evidence["peak_amplitude"] = reading.peak_amplitude

    if result.verdict == UNUSABLE:
        result.findings.append(
            f"periodic sound was present in {share:.0%} of the recording. The patient did "
            "not speak or vocalise, or the microphone did not pick them up — either way "
            "there is no voice to measure"
        )
        return result

    if reading.duration_seconds < schema.MINIMUM_SECONDS:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"the audio runs {reading.duration_seconds:.1f} s, under the "
            f"{schema.MINIMUM_SECONDS:g} s the pitch and perturbation measures need"
        )

    if reading.peak_amplitude >= CLIPPING_PEAK:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            "the recording reaches full scale and is clipped. Loudness and shimmer are "
            "flattened by the ceiling rather than measured"
        )

    periodicity = reading.periodicity[voiced] if voiced.any() else np.empty(0)
    if periodicity.size:
        mean_peak = float(np.clip(periodicity.mean(), 1e-6, 1 - 1e-6))
        hnr = 10 * np.log10(mean_peak / (1 - mean_peak))
        result.evidence["hnr_db"] = hnr
        if hnr < NOISY_HNR_DB:
            result.verdict = _worse(result.verdict, POOR)
            result.findings.append(
                f"the voiced frames carry {hnr:.1f} dB of harmonics over noise. The room "
                "is about as loud as the patient, and the pitch measures are reading both"
            )
    return result


def assess(
    video: VideoReading | None, voice: VoiceReading | None
) -> Report:
    """Judge every modality the observation actually carries."""
    duration = 0.0
    if video is not None:
        duration = max(duration, video.duration_seconds)
    if voice is not None:
        duration = max(duration, voice.duration_seconds)

    report = Report(duration_seconds=duration)
    if video is not None:
        report.frame_rate = video.frame_rate
        report.frames_analysed = video.analysed
        report.modalities.append(_face_quality(video))
        report.modalities.append(_eye_quality(video))
        report.findings.extend(video.notes)
    if voice is not None:
        report.modalities.append(_voice_quality(voice))
        report.findings.extend(voice.notes)

    if not report.modalities:
        report.findings.append("the clip holds neither a video nor an audio track")
    if duration < schema.MINIMUM_SECONDS:
        report.findings.append(
            f"the observation is {duration:.1f} s long, under the {schema.MINIMUM_SECONDS:g} s "
            "a blink rate and a pitch measure need behind them"
        )
    refused = [item.modality for item in report.modalities if not item.usable]
    if refused:
        report.findings.append(
            "no measure was reported for " + ", ".join(sorted(refused)).lower()
        )
    return report
