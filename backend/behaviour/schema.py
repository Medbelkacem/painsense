"""What a behavioural observation is made of.

This is the channel that watches and listens. A camera and a microphone are pointed at
the patient for a short window, and what comes back are the things a clinician scores by
eye when they use an observational pain scale: how tight the eyes are, how often they
close, what the pupils are doing, where the brow sits, whether the mouth is open, and how
the voice sounds.

That framing is the point. The platform already knows which patients cannot be asked for a
number — a newborn, someone with dementia, someone intubated — and for exactly those
patients the reference scale is observational: NIPS, FLACC, PAINAD, CPOT. Every one of
those scales has a facial item and most have a vocal one, and until now the platform
declared both as signals it did not measure. This module measures them.

Three rules it keeps.

**A measure is named for what it is, not for what it is hoped to mean.** A pupil diameter
is a pupil diameter. It widens with pain and it widens with fear, light, opioids and
tiredness, and nothing here pretends otherwise.

**Nothing is reported from a window the camera did not actually see.** Eye measures need
open eyes in the frame; a measure with no frames behind it is absent, not zero.

**The scale comes from the iris.** The horizontal visible iris diameter is close to
constant across adults and barely changes with refractive error, which makes it the one
thing in a webcam image whose real size is known. Every millimetre figure here is derived
from it, and without an iris there is no millimetre figure at all.
"""

from __future__ import annotations

from dataclasses import dataclass

EYE = "EYE"
FACE = "FACE"
VOICE = "VOICE"
MODALITIES = (EYE, FACE, VOICE)

#: Feature schema version for this channel. Bumped when the measure set changes shape, so
#: a stored observation can be told apart from one produced by a different extractor.
FEATURE_SCHEMA_VERSION = "1"

#: Horizontal visible iris diameter, in millimetres. 11.7 mm is the figure quoted in the
#: ophthalmic literature for adults, with a spread of about half a millimetre and almost
#: no dependence on age past childhood. It is the reference every millimetre figure in
#: this module is scaled by, which is why it is a named constant and not a magic number.
IRIS_DIAMETER_MM = 11.7

#: Under this the iris is a handful of pixels across and a pupil measured inside it is
#: quantisation noise. Measured in pixels of iris radius.
MINIMUM_IRIS_RADIUS_PX = 5.0

#: A closure shorter than this is not a blink, it is one dropped detection.
MINIMUM_BLINK_MS = 60.0
#: A closure longer than this is not a blink either. It is an eye squeeze, or the patient
#: has their eyes shut, and counting it as a blink would inflate the blink rate at exactly
#: the moment the face is doing something worth noticing.
MAXIMUM_BLINK_MS = 500.0

#: Frames per second the camera has to reach before blink timing means anything. A blink
#: lasts 100-400 ms, so under this a blink falls between two frames.
MINIMUM_FRAME_RATE = 10.0

#: Shorter than this and a blink rate has too few blinks behind it to quote, and a voice
#: measure has too few pitch periods.
MINIMUM_SECONDS = 8.0

#: Audio below this cannot carry the top of the spectrum the voice measures are read over.
MINIMUM_SAMPLE_RATE_HZ = 8000.0

#: The rate the audio is resampled to before anything is measured. Fixed rather than
#: taken from the recording, because mel-frequency coefficients are not comparable
#: between sample rates and the voice model is trained at one of them.
ANALYSIS_SAMPLE_RATE_HZ = 22050

#: Human phonation, generously bounded. Below is period-doubling or hum, above is
#: whistling or a harmonic mistaken for the fundamental.
F0_RANGE_HZ = (60.0, 500.0)


@dataclass(frozen=True)
class Measure:
    code: str
    label: str
    modality: str
    unit: str
    #: What the number is, and what else moves it. Shown beside the figure, because a
    #: pupil diameter with no such sentence invites the reader to treat it as a pain
    #: reading.
    note: str = ""
    #: Outside this, the measure is not reported: the extraction found something, but not
    #: something a face or a voice does.
    plausible: tuple[float, float] | None = None
    #: True where the measure is one the patient's own resting value is subtracted from
    #: before it means anything.
    baseline_relative: bool = False


MEASURES: tuple[Measure, ...] = (
    Measure(
        "eye_aperture_ratio",
        "Eye aperture",
        EYE,
        "ratio",
        "Height of the visible iris over its width, averaged over the frames where both "
        "eyes were found open. In an open eye the lids cross the iris top and bottom, so "
        "this falls as they close and reaches 1.0 when they clear the iris entirely. "
        "Scale-free, so it does not change when the patient leans towards the camera.",
        plausible=(0.0, 1.0),
        baseline_relative=True,
    ),
    Measure(
        "eye_squint_index",
        "Orbital tightening",
        EYE,
        "0-1",
        "How far the aperture has narrowed from this patient's own resting opening. This "
        "is AU6 and AU7 of the facial action coding system, the orbital tightening that "
        "carries more of the facial pain signal than any other action. Without a resting "
        "observation to compare against there is no index.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "eye_open_share",
        "Frames with both eyes open",
        EYE,
        "0-1",
        "Share of the analysed frames in which both eyes were found and open. This is "
        "the gate: the eye measures below are taken over these frames and nothing else.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "eye_asymmetry_ratio",
        "Difference between the two eyes",
        EYE,
        "ratio",
        "Absolute difference in aperture between left and right. A persistent difference "
        "is a facial nerve finding or a swollen lid rather than a pain finding, and is "
        "reported so it is not read as one.",
        plausible=(0.0, 0.6),
    ),
    Measure(
        "blink_rate_per_min",
        "Blink rate",
        EYE,
        "per minute",
        "Spontaneous blinks per minute. Rises with distress and with dry eyes, falls with "
        "concentration and with sedation. A resting adult sits around 15 to 20.",
        plausible=(0.0, 120.0),
        baseline_relative=True,
    ),
    Measure(
        "blink_closure_ms",
        "Mean blink duration",
        EYE,
        "ms",
        "How long the eyes stayed shut for an average blink.",
        plausible=(float(MINIMUM_BLINK_MS), float(MAXIMUM_BLINK_MS)),
    ),
    Measure(
        "long_closure_share",
        "Time with the eyes squeezed shut",
        EYE,
        "0-1",
        "Share of the window spent in a closure too long to be a blink. This is the "
        "sustained eye closure that observational scales score, AU43, and it is kept "
        "apart from the blink rate so one does not corrupt the other.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "pupil_diameter_mm",
        "Pupil diameter",
        EYE,
        "mm",
        "Mean pupil diameter over the open-eye frames, scaled from the iris. Pupil size "
        "tracks sympathetic tone, which nociception raises — and so do fear, a dark room, "
        "and withdrawal; opioids shrink it. It is an arousal measure, not a pain measure.",
        plausible=(1.0, 9.0),
        baseline_relative=True,
    ),
    Measure(
        "pupil_iris_ratio",
        "Pupil against iris",
        EYE,
        "ratio",
        "Pupil radius over iris radius. The same reading as the diameter without the "
        "millimetre conversion, reported because it carries no assumption about iris size.",
        plausible=(0.1, 0.8),
    ),
    Measure(
        "pupil_unrest_mm",
        "Pupillary unrest",
        EYE,
        "mm",
        "Standard deviation of the pupil diameter across the window. The small continuous "
        "oscillation of the pupil under steady light grows with sympathetic tone, which is "
        "why it is read separately from the diameter itself.",
        plausible=(0.0, 2.0),
    ),
    Measure(
        "pupil_asymmetry_mm",
        "Difference between the pupils",
        EYE,
        "mm",
        "Absolute difference between the two pupils. Beyond about a millimetre this is a "
        "neurological finding to be looked at, not a pain signal.",
        plausible=(0.0, 4.0),
    ),
    Measure(
        "gaze_dispersion_ratio",
        "Gaze movement",
        EYE,
        "ratio",
        "How much the pupil centre moved inside the eye opening. High values are a "
        "wandering or averted gaze; near zero is a fixed stare.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "brow_gap_ratio",
        "Brow to eye distance",
        FACE,
        "ratio",
        "How far the eyebrow sits above the eye, over the height of the face box. The raw "
        "geometry that brow lowering is read from, reported so a resting value can be "
        "stored and compared against later.",
        plausible=(0.0, 0.5),
        baseline_relative=True,
    ),
    Measure(
        "brow_lower_index",
        "Brow lowering",
        FACE,
        "0-1",
        "How far the brow has come down towards the eye, against this patient's own "
        "resting brow. AU4, the second of the facial pain actions. Measured from the "
        "vertical position of the darkest band above the eye, so a raised eyebrow pencil "
        "or a heavy fringe will move it.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "mouth_open_ratio",
        "Mouth opening",
        FACE,
        "ratio",
        "Vertical opening of the mouth over the width of the face. Rises with speech as "
        "well as with a grimace, which is why it is read together with the voice track "
        "rather than alone.",
        plausible=(0.0, 0.5),
    ),
    Measure(
        "face_motion_index",
        "Head movement",
        FACE,
        "ratio",
        "Frame-to-frame movement of the face, as a fraction of face width per second. "
        "Restlessness and guarding raise it; so does a patient adjusting their chair.",
        plausible=(0.0, 5.0),
    ),
    Measure(
        "head_turn_share",
        "Time facing away",
        FACE,
        "0-1",
        "Share of the window in which no front-facing view was found. Averting the face "
        "is itself a behaviour worth recording, but it is also simply what happens when "
        "someone looks at the clinician rather than the lens.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "facial_action_index",
        "Facial actions measured",
        FACE,
        "0-1",
        "Orbital tightening, sustained eye closure and brow lowering, combined. Three of "
        "the four actions the Prkachin and Solomon pain intensity score is built from; "
        "the fourth, levator contraction around the nose and upper lip, is not measurable "
        "from a face box and is not guessed at. This is therefore a partial score and is "
        "deliberately not called PSPI.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "f0_mean_hz",
        "Pitch",
        VOICE,
        "Hz",
        "Mean fundamental frequency over the voiced frames. Rises with pain and with any "
        "other distress, and differs by a factor of two between adult men and women, "
        "which is why the change from this patient's own resting pitch is the figure that "
        "is read.",
        plausible=F0_RANGE_HZ,
        baseline_relative=True,
    ),
    Measure(
        "f0_sd_semitones",
        "Pitch variability",
        VOICE,
        "semitones",
        "Spread of the pitch, in semitones so it is comparable between voices. A flat "
        "monotone and a strained wavering voice sit at opposite ends.",
        plausible=(0.0, 12.0),
    ),
    Measure(
        "jitter_percent",
        "Jitter",
        VOICE,
        "%",
        "Cycle-to-cycle variation in the length of the pitch period. Above about 1% the "
        "voice is rough. Strain raises it; so does a cold.",
        plausible=(0.0, 20.0),
    ),
    Measure(
        "shimmer_percent",
        "Shimmer",
        VOICE,
        "%",
        "Cycle-to-cycle variation in amplitude. The amplitude counterpart of jitter.",
        plausible=(0.0, 40.0),
    ),
    Measure(
        "hnr_db",
        "Harmonics to noise",
        VOICE,
        "dB",
        "How much of the voiced signal is periodic rather than breath noise. A clear "
        "modal voice is above 15 dB; strain and breathiness pull it down.",
        plausible=(-10.0, 40.0),
    ),
    Measure(
        "intensity_db",
        "Loudness",
        VOICE,
        "dBFS",
        "Mean level of the voiced frames relative to full scale. Depends on how far the "
        "patient sat from the microphone as much as on how loudly they spoke, so it is "
        "read as a change against their own resting recording and not on its own.",
        plausible=(-80.0, 0.0),
        baseline_relative=True,
    ),
    Measure(
        "voiced_share",
        "Time voiced",
        VOICE,
        "0-1",
        "Share of the window carrying periodic sound.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "pause_share",
        "Time silent",
        VOICE,
        "0-1",
        "Share of the window below the noise floor. Long pauses mid-sentence are part of "
        "what makes speech sound laboured.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "speech_rate_per_s",
        "Speech rate",
        VOICE,
        "per second",
        "Syllable-sized peaks in the loudness envelope per second. A rate, not a "
        "transcript: nothing here recognises a word.",
        plausible=(0.0, 12.0),
        baseline_relative=True,
    ),
    Measure(
        "vocalisation_share",
        "Non-speech vocalisation",
        VOICE,
        "0-1",
        "Share of the voiced time spent on sustained sound that is not articulated — a "
        "moan, a groan, a cry. Scored by hand on PAINAD and CPOT, which is why it is "
        "measured here rather than only inferred from the pitch.",
        plausible=(0.0, 1.0),
    ),
    Measure(
        "spectral_centroid_hz",
        "Spectral centre of gravity",
        VOICE,
        "Hz",
        "Where the energy of the sound sits in the spectrum. A tense, pressed voice is "
        "brighter than a relaxed one.",
        plausible=(0.0, 11025.0),
    ),
    Measure(
        "spectral_rolloff_hz",
        "Spectral rolloff",
        VOICE,
        "Hz",
        "The frequency below which 85% of the energy lies.",
        plausible=(0.0, 11025.0),
    ),
    Measure(
        "zero_crossing_rate",
        "Zero crossing rate",
        VOICE,
        "ratio",
        "How often the waveform crosses zero. A simple separator of voiced sound from "
        "breath and consonants.",
        plausible=(0.0, 1.0),
    ),
)

BY_CODE = {measure.code: measure for measure in MEASURES}


def of_modality(modality: str) -> tuple[Measure, ...]:
    return tuple(measure for measure in MEASURES if measure.modality == modality)


#: Mel-frequency cepstral coefficients. Kept out of MEASURES because they are not
#: something to show a clinician — no single coefficient means anything on its own. They
#: exist because the one public pain-labelled speech corpus this platform can reach
#: publishes its features in this form, and a model trained on it has to be fed the same
#: shape at the bedside as it saw in training.
MFCC_COUNT = 13


def mfcc_names() -> tuple[str, ...]:
    return tuple(
        f"mfcc_{index}_{statistic}"
        for statistic in ("mean", "sd")
        for index in range(1, MFCC_COUNT + 1)
    )


#: Everything a stored observation carries, in order. The measures a clinician reads,
#: then the coefficients the voice model reads.
def feature_names() -> tuple[str, ...]:
    return tuple(measure.code for measure in MEASURES) + mfcc_names()
