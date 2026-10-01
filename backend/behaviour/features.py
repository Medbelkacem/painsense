"""Turning a window of frames and a waveform into the measures a clinician reads.

Three things happen here that are worth stating before the code.

**A measure with nothing behind it is absent, not zero.** Every value in the output exists
because frames or voiced samples supported it. A patient who kept their eyes shut has no
aperture; a patient who said nothing has no pitch. Both are informative, and both would be
misrepresented by a zero, which a model would read as a very small opening and a very low
voice.

**Orbital tightening and brow lowering need a reference, and the reference is named.** How
tight an eye is only means something against how that eye looks at rest. The best reference
is a short resting observation of the same patient, which is what the calibration is for.
Failing that, the widest moment inside this same window is used — a real within-recording
comparison rather than a population average, and one whose limitation is plain: a patient
who squinted from the first frame to the last has no wide moment, so the index reads low. So
the source is recorded alongside the value, and a reader can see which one they are looking
at.

**The composite is a partial score and says so.** Three of the four facial actions that
make up the Prkachin and Solomon pain intensity score are measurable from a face box:
orbital tightening, sustained closure, brow lowering. The fourth, the levator contraction
that wrinkles the nose and raises the upper lip, is not, and is not guessed at. Calling the
result PSPI would claim a score built on four actions when it is built on three.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.behaviour import quality as quality_module
from backend.behaviour import schema
from backend.behaviour.video import VideoReading
from backend.behaviour.voice import HOP_SECONDS, VoiceReading

#: Where the reference for a change-from-rest measure came from.
CALIBRATION = "CALIBRATION"
WITHIN_WINDOW = "WITHIN_WINDOW"

#: The actions the composite is built from, and their weight in it. Equal weights: the
#: literature ranks orbital tightening first, but not by a margin this platform has
#: established on its own patients, and an invented weighting would be worse than none.
COMPOSITE_PARTS = ("eye_squint_index", "long_closure_share", "brow_lower_index")


@dataclass
class Baseline:
    """This patient's own resting behaviour, from an earlier observation at rest."""

    eye_aperture_ratio: float | None = None
    pupil_diameter_mm: float | None = None
    blink_rate_per_min: float | None = None
    brow_gap_ratio: float | None = None
    f0_mean_hz: float | None = None
    intensity_db: float | None = None
    speech_rate_per_s: float | None = None

    @property
    def empty(self) -> bool:
        return all(getattr(self, name) is None for name in self.__dataclass_fields__)


@dataclass
class FeatureSet:
    schema_version: str = schema.FEATURE_SCHEMA_VERSION
    values: dict[str, float] = field(default_factory=dict)
    #: Mel-frequency coefficients, kept apart from the measures a clinician reads.
    cepstral: dict[str, float] = field(default_factory=dict)
    #: Change from this patient's own resting value, where there is one.
    deltas: dict[str, float] = field(default_factory=dict)
    #: Which reference each change-from-rest measure was taken against.
    reference: dict[str, str] = field(default_factory=dict)
    #: Measures not reported, and why.
    absent: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Counts the measures rest on, so a reader can see how much was behind each average.
    support: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "values": {name: round(value, 4) for name, value in sorted(self.values.items())},
            "cepstral": {
                name: round(value, 4) for name, value in sorted(self.cepstral.items())
            },
            "deltas": {name: round(value, 4) for name, value in sorted(self.deltas.items())},
            "reference": dict(sorted(self.reference.items())),
            "absent": dict(sorted(self.absent.items())),
            "support": dict(sorted(self.support.items())),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Closure:
    """A run of frames in which a located face had its eyes shut."""

    start_s: float
    duration_ms: float

    @property
    def is_blink(self) -> bool:
        return schema.MINIMUM_BLINK_MS <= self.duration_ms <= schema.MAXIMUM_BLINK_MS

    @property
    def is_squeeze(self) -> bool:
        return self.duration_ms > schema.MAXIMUM_BLINK_MS


def closures(reading: VideoReading) -> list[Closure]:
    """Every eye closure in the window, with its length.

    Only frames in which a face was found count. A patient who turned away has not closed
    their eyes, and treating the two the same would turn every head movement into a blink.
    The frame interval is taken from the sampled frames themselves rather than from the
    file's declared rate, because the sampling is what the sequence is in.
    """
    frames = [frame for frame in reading.frames if frame.face is not None]
    if len(frames) < 2:
        return []
    intervals = np.diff([frame.time_s for frame in frames])
    interval = float(np.median(intervals)) if len(intervals) else 0.0
    if interval <= 0:
        return []

    found: list[Closure] = []
    start: int | None = None
    for index, frame in enumerate(frames + [None]):
        shut = frame is not None and not frame.eyes_open
        if shut and start is None:
            start = index
        elif not shut and start is not None:
            found.append(
                Closure(
                    start_s=frames[start].time_s,
                    duration_ms=(index - start) * interval * 1000.0,
                )
            )
            start = None
    return found


def _mean(values) -> float | None:
    finite = [float(value) for value in values if value is not None and not np.isnan(value)]
    return float(np.mean(finite)) if finite else None


def _record(
    out: FeatureSet, code: str, value: float | None, *, support: int | None = None
) -> None:
    """Store a measure, unless it is missing or outside what a face or a voice does."""
    measure = schema.BY_CODE[code]
    if value is None or np.isnan(value):
        out.absent.setdefault(code, "nothing in the window supported it")
        return
    if measure.plausible is not None:
        low, high = measure.plausible
        if not low <= value <= high:
            out.absent[code] = (
                f"measured {value:.3g} {measure.unit}, outside the {low:g} to {high:g} "
                "a face or a voice produces"
            )
            return
    out.values[code] = float(value)
    if support is not None:
        out.support[code] = support


def _relative(baseline: float | None, current: float) -> float | None:
    if baseline is None or baseline == 0:
        return None
    return (current - baseline) / abs(baseline)


def _eye_features(
    out: FeatureSet, reading: VideoReading, baseline: Baseline, report: quality_module.Report
) -> None:
    if not report.allows(schema.EYE):
        verdict = report.of(schema.EYE)
        reason = (
            f"eye quality {verdict.verdict.lower()}" if verdict else "no eye assessment"
        )
        for measure in schema.of_modality(schema.EYE):
            out.absent[measure.code] = reason
        return

    frames = reading.with_eyes_open
    analysed = max(reading.analysed, 1)
    pairs = [(frame.left, frame.right) for frame in frames]

    apertures = [(left.aperture_ratio + right.aperture_ratio) / 2 for left, right in pairs]
    _record(out, "eye_aperture_ratio", _mean(apertures), support=len(apertures))
    _record(out, "eye_open_share", len(frames) / analysed, support=analysed)
    _record(
        out,
        "eye_asymmetry_ratio",
        _mean([abs(left.aperture_ratio - right.aperture_ratio) for left, right in pairs]),
        support=len(pairs),
    )

    # Orbital tightening, against the best reference available.
    mean_aperture = _mean(apertures)
    if mean_aperture is not None:
        resting = baseline.eye_aperture_ratio
        source = CALIBRATION
        if resting is None:
            resting = max(apertures) if apertures else None
            source = WITHIN_WINDOW
        if resting and resting > 0:
            _record(out, "eye_squint_index", max(0.0, 1.0 - mean_aperture / resting))
            out.reference["eye_squint_index"] = source
        else:
            out.absent["eye_squint_index"] = "no resting aperture to compare against"

    diameters = [
        value
        for left, right in pairs
        for value in (left.pupil_diameter_mm, right.pupil_diameter_mm)
        if value > 0
    ]
    _record(out, "pupil_diameter_mm", _mean(diameters), support=len(diameters))
    _record(
        out,
        "pupil_iris_ratio",
        _mean(
            [
                value
                for left, right in pairs
                for value in (left.pupil_iris_ratio, right.pupil_iris_ratio)
                if value > 0
            ]
        ),
    )
    # Pupillary unrest needs several readings to be a spread rather than a difference.
    if len(diameters) >= 4:
        _record(out, "pupil_unrest_mm", float(np.std(diameters)), support=len(diameters))
    else:
        out.absent["pupil_unrest_mm"] = (
            "fewer than four pupil readings, which is too few for a spread"
        )
    _record(
        out,
        "pupil_asymmetry_mm",
        _mean(
            [
                abs(left.pupil_diameter_mm - right.pupil_diameter_mm)
                for left, right in pairs
                if left.pupil_diameter_mm > 0 and right.pupil_diameter_mm > 0
            ]
        ),
    )

    # Gaze: how far the iris centre wandered inside its window, pooled over both eyes.
    spread = [
        float(np.hypot(np.std([eye.gaze[0] for eye in side]), np.std([eye.gaze[1] for eye in side])))
        for side in ([left for left, _ in pairs], [right for _, right in pairs])
        if len(side) >= 4
    ]
    if spread:
        _record(out, "gaze_dispersion_ratio", float(np.mean(spread)))
    else:
        out.absent["gaze_dispersion_ratio"] = "too few open-eye frames to measure movement"

    events = closures(reading)
    observed = [frame for frame in reading.frames if frame.face is not None]
    seconds = (observed[-1].time_s - observed[0].time_s) if len(observed) >= 2 else 0.0
    if seconds > 0:
        blinks = [event for event in events if event.is_blink]
        _record(out, "blink_rate_per_min", len(blinks) * 60.0 / seconds, support=len(blinks))
        _record(out, "blink_closure_ms", _mean([event.duration_ms for event in blinks]))
        squeezed = sum(event.duration_ms for event in events if event.is_squeeze) / 1000.0
        _record(out, "long_closure_share", min(1.0, squeezed / seconds))
    else:
        for code in ("blink_rate_per_min", "blink_closure_ms", "long_closure_share"):
            out.absent[code] = "no stretch of frames with a face in them to count over"


def _face_features(
    out: FeatureSet, reading: VideoReading, baseline: Baseline, report: quality_module.Report
) -> None:
    analysed = max(reading.analysed, 1)
    # Facing away is counted whatever the facial quality verdict: it is the one facial
    # measure that a window full of turned-away frames supports rather than refutes.
    _record(
        out, "head_turn_share", 1.0 - len(reading.with_face) / analysed, support=analysed
    )

    if not report.allows(schema.FACE):
        verdict = report.of(schema.FACE)
        reason = f"face quality {verdict.verdict.lower()}" if verdict else "no face assessment"
        for measure in schema.of_modality(schema.FACE):
            if measure.code != "head_turn_share":
                out.absent[measure.code] = reason
        return

    frames = reading.with_face
    _record(
        out,
        "mouth_open_ratio",
        _mean([frame.mouth_open_ratio for frame in frames]),
        support=len(frames),
    )

    gaps = [frame.brow_gap_ratio for frame in frames if not np.isnan(frame.brow_gap_ratio)]
    mean_gap = _mean(gaps)
    _record(out, "brow_gap_ratio", mean_gap, support=len(gaps))
    if mean_gap is not None:
        resting = baseline.brow_gap_ratio
        source = CALIBRATION
        if resting is None:
            resting = max(gaps) if gaps else None
            source = WITHIN_WINDOW
        if resting and resting > 0:
            _record(out, "brow_lower_index", max(0.0, 1.0 - mean_gap / resting))
            out.reference["brow_lower_index"] = source
        else:
            out.absent["brow_lower_index"] = "no resting brow position to compare against"
    else:
        out.absent["brow_lower_index"] = "no eyebrow was located in any frame"

    # Head movement, from the face box between consecutive frames that both held a face.
    moves = []
    for previous, current in zip(reading.frames, reading.frames[1:]):
        if previous.face is None or current.face is None:
            continue
        gap = current.time_s - previous.time_s
        if gap <= 0:
            continue
        before = np.array([previous.face[0] + previous.face[2] / 2,
                           previous.face[1] + previous.face[3] / 2])
        after = np.array([current.face[0] + current.face[2] / 2,
                          current.face[1] + current.face[3] / 2])
        moves.append(float(np.linalg.norm(after - before)) / current.face[2] / gap)
    if moves:
        _record(out, "face_motion_index", float(np.mean(moves)), support=len(moves))
    else:
        out.absent["face_motion_index"] = "no two consecutive frames both held a face"


def _voice_features(
    out: FeatureSet, reading: VoiceReading, baseline: Baseline, report: quality_module.Report
) -> None:
    if not report.allows(schema.VOICE):
        verdict = report.of(schema.VOICE)
        reason = f"voice quality {verdict.verdict.lower()}" if verdict else "no voice assessment"
        for measure in schema.of_modality(schema.VOICE):
            out.absent[measure.code] = reason
        return

    voiced = reading.voiced
    pitch = reading.pitch[voiced]
    _record(out, "voiced_share", float(voiced.mean()), support=int(voiced.sum()))

    if pitch.size:
        _record(out, "f0_mean_hz", float(np.mean(pitch)), support=int(pitch.size))
        # Spread in semitones rather than hertz, so a bass and a soprano holding the same
        # musical interval produce the same number.
        semitones = 12 * np.log2(pitch / np.mean(pitch))
        _record(out, "f0_sd_semitones", float(np.std(semitones)))

    periods = reading.periods
    if periods.size >= 3 and periods.mean() > 0:
        _record(
            out,
            "jitter_percent",
            100.0 * float(np.mean(np.abs(np.diff(periods))) / periods.mean()),
            support=int(periods.size),
        )
    else:
        out.absent["jitter_percent"] = (
            "fewer than three glottal periods were marked, which is too few for a "
            "period-to-period measure"
        )
    amplitudes = reading.period_amplitudes
    if amplitudes.size >= 3 and amplitudes.mean() > 0:
        _record(
            out,
            "shimmer_percent",
            100.0 * float(np.mean(np.abs(np.diff(amplitudes))) / amplitudes.mean()),
            support=int(amplitudes.size),
        )
    else:
        out.absent["shimmer_percent"] = "fewer than three glottal periods were marked"

    periodicity = reading.periodicity[voiced]
    if periodicity.size:
        clamped = float(np.clip(periodicity.mean(), 1e-6, 1 - 1e-6))
        _record(out, "hnr_db", 10 * float(np.log10(clamped / (1 - clamped))))

    levels = reading.level_db[voiced] if voiced.any() else np.empty(0)
    if levels.size:
        _record(out, "intensity_db", float(np.mean(levels)), support=int(levels.size))

    if reading.level_db.size:
        floor = reading.level_db.max() - 35.0
        _record(out, "pause_share", float((reading.level_db < floor).mean()))
    if reading.duration_seconds > 0:
        _record(out, "speech_rate_per_s", reading.syllables / reading.duration_seconds,
                support=reading.syllables)
    voiced_seconds = float(voiced.sum()) * HOP_SECONDS
    if voiced_seconds > 0:
        _record(
            out,
            "vocalisation_share",
            min(1.0, reading.sustained_seconds / voiced_seconds),
        )

    if reading.spectral_centroid.size:
        _record(out, "spectral_centroid_hz", float(np.mean(reading.spectral_centroid)))
    if reading.spectral_rolloff.size:
        _record(out, "spectral_rolloff_hz", float(np.mean(reading.spectral_rolloff)))
    if reading.zero_crossing_rate.size:
        _record(out, "zero_crossing_rate", float(np.mean(reading.zero_crossing_rate)))

    if reading.mfcc.size:
        for index in range(reading.mfcc.shape[1]):
            column = reading.mfcc[:, index]
            out.cepstral[f"mfcc_{index + 1}_mean"] = float(np.mean(column))
            out.cepstral[f"mfcc_{index + 1}_sd"] = float(np.std(column))


def _composite(out: FeatureSet) -> None:
    parts = {name: out.values[name] for name in COMPOSITE_PARTS if name in out.values}
    if not parts:
        out.absent["facial_action_index"] = (
            "none of the actions it combines was measurable: "
            + ", ".join(COMPOSITE_PARTS)
        )
        return
    _record(out, "facial_action_index", float(np.mean(list(parts.values()))))
    missing = [name for name in COMPOSITE_PARTS if name not in parts]
    if missing:
        out.notes.append(
            "The facial action index combines "
            + ", ".join(schema.BY_CODE[name].label.lower() for name in parts)
            + " only; "
            + ", ".join(schema.BY_CODE[name].label.lower() for name in missing)
            + " was not measurable in this observation."
        )


def _deltas(out: FeatureSet, baseline: Baseline) -> None:
    if baseline.empty:
        out.notes.append(
            "No resting observation of this patient exists, so nothing here is a change "
            "from their own baseline. Recording one at rest is what turns these figures "
            "from population comparisons into personal ones."
        )
        return
    for measure in schema.MEASURES:
        if not measure.baseline_relative:
            continue
        resting = getattr(baseline, measure.code, None)
        current = out.values.get(measure.code)
        if current is None:
            continue
        change = _relative(resting, current)
        if change is not None:
            out.deltas[measure.code] = change
            out.reference[measure.code] = CALIBRATION


def extract(
    *,
    video: VideoReading | None,
    voice: VoiceReading | None,
    report: quality_module.Report,
    baseline: Baseline | None = None,
) -> FeatureSet:
    """Every measure the observation supports, and a reason for each one it does not."""
    baseline = baseline or Baseline()
    out = FeatureSet()

    if video is not None:
        _eye_features(out, video, baseline, report)
        _face_features(out, video, baseline, report)
    else:
        for modality in (schema.EYE, schema.FACE):
            for measure in schema.of_modality(modality):
                out.absent[measure.code] = "the clip holds no video track"

    if voice is not None:
        _voice_features(out, voice, baseline, report)
    else:
        for measure in schema.of_modality(schema.VOICE):
            out.absent[measure.code] = "the clip holds no audio track"

    _composite(out)
    _deltas(out, baseline)
    out.notes.append(
        "These are measurements of behaviour, not of pain. Every one of them also moves "
        "with fear, fatigue, room light, sedation and how far the patient sat from the "
        "camera, and none of them is a pain reading on its own."
    )
    return out


def summary(features: FeatureSet) -> dict:
    """The handful of figures a results panel leads with."""
    values = features.values
    return {
        "eye": {
            code: values.get(code)
            for code in (
                "eye_aperture_ratio",
                "eye_squint_index",
                "eye_open_share",
                "blink_rate_per_min",
                "long_closure_share",
                "pupil_diameter_mm",
                "pupil_unrest_mm",
                "gaze_dispersion_ratio",
            )
        },
        "face": {
            code: values.get(code)
            for code in (
                "brow_gap_ratio",
                "brow_lower_index",
                "mouth_open_ratio",
                "face_motion_index",
                "head_turn_share",
                "facial_action_index",
            )
        },
        "voice": {
            code: values.get(code)
            for code in (
                "f0_mean_hz",
                "f0_sd_semitones",
                "jitter_percent",
                "shimmer_percent",
                "hnr_db",
                "intensity_db",
                "speech_rate_per_s",
                "pause_share",
                "vocalisation_share",
            )
        },
        "reference": dict(features.reference),
        "deltas": {name: round(value, 4) for name, value in features.deltas.items()},
    }
