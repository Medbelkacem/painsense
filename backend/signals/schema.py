"""What a recording is made of: channels, their units, and the bands features are read in.

Channel definitions are reference data rather than configuration because the feature
extractor's output names are built from them, and a stored analysis has to stay readable
after someone adds a channel.

The EEG bands are the conventional clinical boundaries. They are used because a reader of
the analysis expects them, not because this platform has established that any of them
relates to pain — it has not.
"""

from __future__ import annotations

from dataclasses import dataclass

EEG = "EEG"
EMG = "EMG"
PPG = "PPG"
GSR = "GSR"
RESPIRATION = "RESPIRATION"
MODALITIES = (EEG, EMG, PPG, GSR, RESPIRATION)

#: The modalities this feature's analysis is about. A recording's overall quality verdict is
#: taken over these alone: a chest belt that slipped should cost the respiratory rate, not
#: invalidate an otherwise clean EEG and EMG recording.
PRIMARY_MODALITIES = (EEG, EMG)

#: Reported where present, never required, and never part of the quality verdict.
SUPPORTING_MODALITIES = (PPG, GSR, RESPIRATION)

#: A channel whose standard deviation is below this is not measuring anything. Expressed in
#: the channel's own unit; an electrode on skin never sits this still. A channel whose own
#: signal is slower and smaller says so with `Channel.flatline_sd`.
DEFAULT_FLATLINE_SD = 0.05

#: Feature schema version. Bumped when the feature set changes shape, so a stored analysis
#: can be told apart from one produced by a different extractor.
FEATURE_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Channel:
    code: str
    label: str
    modality: str
    unit: str
    #: Where the amplifier's useful range ends. A sample at or beyond this is clipping, and
    #: clipped samples are counted rather than quietly averaged into a feature.
    saturation: float
    #: Sampling rates below this cannot carry the band the features are read in.
    minimum_rate_hz: float
    #: The standard deviation below which this channel reads as disconnected rather than
    #: quiet, in its own unit.
    flatline_sd: float = DEFAULT_FLATLINE_SD
    note: str = ""


#: A minimal, defensible channel set: two midline EEG derivations, two surface EMG sites, and
#: the optional autonomic channels the brief asks to report where they exist.
CHANNELS: tuple[Channel, ...] = (
    Channel(
        "EEG_FPZ",
        "EEG Fpz (frontal midline)",
        EEG,
        "uV",
        200.0,
        128.0,
        note="Midline rather than a left/right pair. Nothing here reads a difference "
        "between the hemispheres, so recording one would cost two electrodes and an "
        "application step to produce a number no feature uses.",
    ),
    Channel("EEG_CZ", "EEG Cz (central midline, vertex)", EEG, "uV", 200.0, 128.0),
    Channel(
        "EMG_TRAPEZIUS_L",
        "Surface EMG, left trapezius",
        EMG,
        "uV",
        2000.0,
        500.0,
        note="Surface EMG needs a far higher sampling rate than EEG; its power extends well "
        "above 100 Hz.",
    ),
    Channel("EMG_TRAPEZIUS_R", "Surface EMG, right trapezius", EMG, "uV", 2000.0, 500.0),
    Channel(
        "PPG_FINGER",
        "PPG, fingertip",
        PPG,
        "arbitrary",
        4.0,
        100.0,
        note="A pulse waveform, not a volume. The minimum rate is set by the variability "
        "features rather than by the pulse: beat-to-beat intervals are read off the "
        "waveform, and at 100 Hz each one carries 10 ms of timing error, which is already "
        "a fifth of a normal RMSSD. Sample at 250 Hz where the amplifier allows it.",
    ),
    Channel(
        "GSR_PALMAR",
        "GSR, palmar",
        GSR,
        "uS",
        100.0,
        4.0,
        flatline_sd=0.002,
        note="Two electrodes on the volar surface of the index and middle fingers. Skin "
        "conductance moves slowly and in hundredths of a microsiemens, so it needs its own "
        "flatline floor: a resting trace that the EEG floor would call a detached "
        "electrode is a normal quiet recording here.",
    ),
    Channel(
        "RESPIRATION_BELT",
        "Respiration, chest belt",
        RESPIRATION,
        "arbitrary",
        4.0,
        10.0,
        note="A relative excursion, not a volume. Reported as a rate only. The range is the "
        "belt amplifier's, not a physiological bound; a normal breath sits well inside it.",
    ),
)

CHANNEL_BY_CODE = {entry.code: entry for entry in CHANNELS}


def channels_for(modality: str) -> tuple[Channel, ...]:
    return tuple(entry for entry in CHANNELS if entry.modality == modality)


#: Conventional EEG band boundaries, in hertz.
EEG_BANDS: tuple[tuple[str, float, float], ...] = (
    ("delta", 0.5, 4.0),
    ("theta", 4.0, 8.0),
    ("alpha", 8.0, 13.0),
    ("beta", 13.0, 30.0),
    ("gamma", 30.0, 45.0),
)

#: Surface EMG band. The lower bound removes movement artefact and the upper bound sits
#: below the Nyquist frequency of the slowest rate this module accepts for EMG.
EMG_BAND = (20.0, 250.0)

#: Band a fingertip pulse is found in: 36 to 210 beats per minute, wide enough to hold a
#: bradycardic adult and a distressed child without admitting a respiratory swing.
PULSE_BAND = (0.6, 3.5)

#: Breathing band, in hertz. 6 to 42 breaths per minute.
RESPIRATION_BAND = (0.1, 0.7)

#: Mains frequency, for the line-noise check. Both are tested because the platform is
#: deployed where the grid is 50 Hz and the literature is largely written where it is 60.
MAINS_HZ = (50.0, 60.0)

DEFAULT_SAMPLE_RATE_HZ = 512.0

#: Shorter than this and a band-power estimate has too few cycles of the slowest band to
#: mean anything: 0.5 Hz delta needs several seconds.
MINIMUM_DURATION_SECONDS = 10.0
