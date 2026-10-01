"""Measuring a voice.

What a clinician hears when they score the vocal item of an observational pain scale is
pitch, effort and roughness, and those are what this measures. Nothing here recognises a
word; nothing here is sent anywhere. The audio becomes about thirty numbers and is then
done with.

The three decisions worth knowing about:

**Pitch is found by autocorrelation, with the peak interpolated.** The interpolation is not
a nicety. Jitter is a difference between consecutive pitch periods of a percent or two, and
at 22 kHz a period of 200 Hz is 110 samples — so rounding the peak to the nearest sample
puts a floor of nearly 1% on a measurement whose interesting range starts at 0.5%. Fitting
a parabola across the peak and its neighbours removes that floor.

**Jitter and shimmer are measured between glottal periods, not between analysis frames.**
Those are the quantities the clinical literature names. Taking the difference between pitch
estimates ten milliseconds apart would be a different and much smoother thing, and calling
it jitter would be wrong. So within each voiced stretch the individual periods are marked
on the waveform and the perturbation is taken across them.

**Loudness is reported but never trusted on its own.** It is as much a measurement of how
far the patient sat from the microphone as of how loudly they spoke. It earns its place
only as a change against the same patient's resting recording.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.fft import dct
from scipy.signal import find_peaks

from backend.behaviour import schema

NAN = float("nan")

#: Analysis frame length and hop, in seconds. 50 ms holds three periods of the lowest
#: pitch this module accepts, which is the minimum autocorrelation needs to find it at all.
FRAME_SECONDS = 0.050
HOP_SECONDS = 0.010

#: Normalised autocorrelation peak a frame needs before it counts as voiced. Below this the
#: frame is breath, consonant or noise, and no pitch is reported for it.
VOICING_FLOOR = 0.35

#: How much periodicity a candidate period may give up against the best one and still be
#: preferred for being shorter. See the octave correction in `_pitch_of`.
OCTAVE_MARGIN = 0.03

#: A frame this far below the loudest frame of the recording is silence rather than quiet
#: speech. Relative, because nothing is known about the microphone's gain.
SILENCE_BELOW_PEAK_DB = 35.0

#: Shortest run of voiced frames worth marking periods in. Below three frames there are too
#: few periods for a perturbation measure to mean anything.
MINIMUM_VOICED_FRAMES = 3

#: A sustained sound this long with a pitch this steady is a vocalisation rather than
#: speech — a moan or a groan holds its pitch where a spoken syllable does not.
SUSTAIN_SECONDS = 0.25
SUSTAIN_PITCH_TOLERANCE = 0.06

#: Syllable peaks closer together than this are one syllable. 120 ms is near the floor of
#: what a speaker can articulate.
SYLLABLE_SPACING_SECONDS = 0.12

#: Fraction of the spectrum's energy below the reported rolloff frequency.
ROLLOFF_SHARE = 0.85

#: Mel-spectrogram geometry. These are the long-standing defaults of the common Python
#: audio libraries, and they are fixed here for one reason: the only public pain-labelled
#: speech corpus this platform can reach publishes coefficients computed with them, and a
#: model trained on that corpus has to be given the same thing at the bedside. Changing any
#: of them invalidates that model rather than merely shifting a number.
FFT_SIZE = 2048
MEL_HOP = 512
MEL_BANDS = 128
MEL_RANGE_HZ = (0.0, schema.ANALYSIS_SAMPLE_RATE_HZ / 2)
#: Decibel floor of the mel spectrogram, below the loudest band.
MEL_TOP_DB = 80.0


class AudioUnreadable(RuntimeError):
    """The clip holds no decodable audio."""


@dataclass
class VoiceReading:
    sample_rate: int
    duration_seconds: float
    #: Per-frame pitch in hertz, NaN where the frame was not voiced.
    pitch: np.ndarray = field(default_factory=lambda: np.empty(0))
    #: Per-frame level in decibels relative to full scale.
    level_db: np.ndarray = field(default_factory=lambda: np.empty(0))
    #: Per-frame normalised autocorrelation peak, the periodicity of the frame.
    periodicity: np.ndarray = field(default_factory=lambda: np.empty(0))
    #: Glottal period lengths and their peak amplitudes, pooled over the voiced stretches.
    periods: np.ndarray = field(default_factory=lambda: np.empty(0))
    period_amplitudes: np.ndarray = field(default_factory=lambda: np.empty(0))
    #: Mel-frequency cepstral coefficients, one column per analysis window.
    mfcc: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    spectral_centroid: np.ndarray = field(default_factory=lambda: np.empty(0))
    spectral_rolloff: np.ndarray = field(default_factory=lambda: np.empty(0))
    zero_crossing_rate: np.ndarray = field(default_factory=lambda: np.empty(0))
    #: Peak sample magnitude, for the clipping check.
    peak_amplitude: float = 0.0
    syllables: int = 0
    sustained_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def voiced(self) -> np.ndarray:
        return ~np.isnan(self.pitch)

    @property
    def voiced_seconds(self) -> float:
        return float(self.voiced.sum()) * HOP_SECONDS


def pcm(path: Path, *, sample_rate: int = schema.ANALYSIS_SAMPLE_RATE_HZ) -> np.ndarray:
    """Mono float samples from any container ffmpeg can open.

    ffmpeg does the decoding and the resampling. It is already a dependency of the
    container image for the same reason every media pipeline ends up depending on it, and
    reimplementing Opus decoding to avoid it would be absurd. A fixed output rate matters
    rather than being tidy: cepstral coefficients are not comparable between sample rates.
    """
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "f32le", "-",
    ]
    try:
        finished = subprocess.run(command, capture_output=True, check=False, timeout=120)
    except FileNotFoundError as exc:
        raise AudioUnreadable(
            "ffmpeg was not found on the path, and the audio track cannot be decoded "
            "without it"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioUnreadable(f"decoding {path.name} took longer than two minutes") from exc

    if not finished.stdout:
        detail = finished.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AudioUnreadable(
            f"{path.name} holds no decodable audio track"
            + (f": {detail[-1]}" if detail else "")
        )
    return np.frombuffer(finished.stdout, dtype=np.float32).astype(float)


def _frames(samples: np.ndarray, length: int, hop: int) -> np.ndarray:
    if len(samples) < length:
        return np.empty((0, length))
    count = 1 + (len(samples) - length) // hop
    return np.lib.stride_tricks.as_strided(
        samples, shape=(count, length), strides=(samples.strides[0] * hop, samples.strides[0])
    )


def _pitch_of(frame: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """Pitch in hertz and the normalised autocorrelation peak that found it.

    Returns (NaN, peak) when nothing periodic is in the plausible range.
    """
    centred = frame - frame.mean()
    energy = float(centred @ centred)
    if energy <= 0:
        return NAN, 0.0

    # Autocorrelation through the spectrum, zero-padded so the circular wrap of the FFT
    # does not fold the tail of the correlation back onto its head.
    padded = int(2 ** np.ceil(np.log2(2 * len(centred))))
    spectrum = np.fft.rfft(centred, padded)
    raw = np.fft.irfft(spectrum * np.conjugate(spectrum))[: len(centred)]

    # Normalise each lag by the energy of the two stretches that actually overlap at it,
    # rather than by the energy of the whole frame. The difference decides whether the
    # periodicity figure means anything: at a lag of one period only N-T of the frame's N
    # samples line up, so dividing by the whole frame costs a perfectly periodic signal
    # about a tenth of its score at 150 Hz and a third at 60 Hz — a pitch-dependent
    # penalty that would land straight in the harmonics-to-noise figure read off it. With
    # the overlapping normalisation a noiseless periodic signal scores 1.0 at its period
    # whatever its pitch, and what is left below 1.0 is noise, which is the point.
    cumulative = np.concatenate(([0.0], np.cumsum(centred**2)))
    total = len(centred)
    lags = np.arange(total)
    head = cumulative[total - lags]
    tail = cumulative[total] - cumulative[lags]
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = np.where(
            (head > 0) & (tail > 0), raw / np.sqrt(head * tail), 0.0
        )

    low = int(sample_rate / schema.F0_RANGE_HZ[1])
    # Capped at a third of the frame as well as at the lowest pitch: past that the two
    # overlapping stretches are short enough that their correlation is mostly chance.
    high = min(
        int(sample_rate / schema.F0_RANGE_HZ[0]), total // 3, len(correlation) - 2
    )
    if high <= low:
        return NAN, 0.0

    window = correlation[low : high + 1]
    best = int(np.argmax(window))
    peak = float(window[best])
    if peak < VOICING_FLOOR:
        return NAN, peak

    # Prefer the shortest lag that explains the signal about as well as the best one does.
    # This is the octave correction and it is not optional once the correlation is
    # normalised over the overlap: a perfectly periodic signal scores 1.0 at one period
    # and 1.0 again at two and three, so the largest peak is chosen by rounding noise and
    # the pitch comes back halved or thirded for an arbitrary scattering of frames. Taking
    # the shortest near-tie fixes that. The margin is tight on purpose — a voice with a
    # strong second harmonic has a real peak at half its period, and a loose margin would
    # trade this error for its mirror image.
    near = np.flatnonzero(window >= peak - OCTAVE_MARGIN)
    offset = int(near[0]) if len(near) else best
    lag = low + offset
    peak = float(window[offset])

    # Parabolic interpolation across the peak, which is what takes the period estimate
    # below one sample of error and so lets a jitter of a percent be measured at all.
    if 0 < lag < len(correlation) - 1:
        before, centre, after = correlation[lag - 1], correlation[lag], correlation[lag + 1]
        denominator = before - 2 * centre + after
        if denominator != 0:
            shift = 0.5 * (before - after) / denominator
            if abs(shift) <= 1:
                lag += shift
    return (sample_rate / lag if lag > 0 else NAN), peak


def _mark_periods(
    samples: np.ndarray, sample_rate: int, pitch: np.ndarray, hop: int, length: int
) -> tuple[np.ndarray, np.ndarray]:
    """Individual glottal periods across the voiced stretches, and their amplitudes.

    Within a voiced stretch the pitch is known to within a percent, so the period markers
    are the waveform's own peaks found with that spacing enforced as a minimum. The
    distances between consecutive markers are the periods that jitter is taken over, and
    the heights at the markers are what shimmer is taken over.
    """
    voiced = ~np.isnan(pitch)
    if not voiced.any():
        return np.empty(0), np.empty(0)

    periods: list[float] = []
    amplitudes: list[float] = []
    start = None
    for index in range(len(voiced) + 1):
        inside = index < len(voiced) and voiced[index]
        if inside and start is None:
            start = index
            continue
        if inside or start is None:
            continue

        run = slice(start, index)
        start_sample = run.start * hop
        stop_sample = min((run.stop - 1) * hop + length, len(samples))
        if run.stop - run.start >= MINIMUM_VOICED_FRAMES and stop_sample > start_sample:
            stretch = samples[start_sample:stop_sample]
            median_pitch = float(np.nanmedian(pitch[run]))
            if median_pitch > 0:
                spacing = sample_rate / median_pitch
                found, _ = find_peaks(stretch, distance=max(2, int(spacing * 0.75)))
                if len(found) >= 3:
                    periods.extend(np.diff(found) / sample_rate)
                    amplitudes.extend(np.abs(stretch[found[:-1]]))
        start = None
    return np.asarray(periods, dtype=float), np.asarray(amplitudes, dtype=float)


def _mel_filterbank(sample_rate: int) -> np.ndarray:
    """Triangular mel filters, normalised by bandwidth.

    The mel scale is the piecewise one — linear to 1 kHz at 200/3 hertz per mel, then
    logarithmic — and the filters are scaled by the width of the band each covers so that
    a flat-spectrum input gives a flat set of band energies. That normalisation is the one
    detail that differs between implementations and the one that would shift every
    coefficient if it were dropped.
    """
    minimum_log_hz = 1000.0
    minimum_log_mel = minimum_log_hz / (200.0 / 3)
    step = np.log(6.4) / 27.0

    def to_mel(hz: np.ndarray) -> np.ndarray:
        mel = hz / (200.0 / 3)
        above = hz >= minimum_log_hz
        mel[above] = minimum_log_mel + np.log(hz[above] / minimum_log_hz) / step
        return mel

    def to_hz(mel: np.ndarray) -> np.ndarray:
        hz = mel * (200.0 / 3)
        above = mel >= minimum_log_mel
        hz[above] = minimum_log_hz * np.exp(step * (mel[above] - minimum_log_mel))
        return hz

    edges_mel = np.linspace(
        *to_mel(np.asarray(MEL_RANGE_HZ, dtype=float)), MEL_BANDS + 2
    )
    edges = to_hz(edges_mel)
    frequencies = np.fft.rfftfreq(FFT_SIZE, 1.0 / sample_rate)

    ramps = edges[:, None] - frequencies[None, :]
    widths = np.diff(edges)
    lower = -ramps[:-2] / widths[:-1, None]
    upper = ramps[2:] / widths[1:, None]
    filters = np.maximum(0.0, np.minimum(lower, upper))
    filters *= (2.0 / (edges[2:] - edges[:-2]))[:, None]
    return filters


def _spectrogram(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    windows = _frames(samples, FFT_SIZE, MEL_HOP)
    if not len(windows):
        return np.empty((0, 0)), np.fft.rfftfreq(FFT_SIZE, 1.0 / sample_rate)
    power = np.abs(np.fft.rfft(windows * np.hanning(FFT_SIZE), FFT_SIZE, axis=1)) ** 2
    return power, np.fft.rfftfreq(FFT_SIZE, 1.0 / sample_rate)


def read(path: Path, *, sample_rate: int = schema.ANALYSIS_SAMPLE_RATE_HZ) -> VoiceReading:
    """Decode a clip's audio track and measure it."""
    samples = pcm(path, sample_rate=sample_rate)
    reading = VoiceReading(
        sample_rate=sample_rate, duration_seconds=len(samples) / sample_rate
    )
    if len(samples) < int(FRAME_SECONDS * sample_rate):
        raise AudioUnreadable(
            f"{path.name} carries {reading.duration_seconds:.2f} s of audio, less than one "
            "analysis frame"
        )
    reading.peak_amplitude = float(np.max(np.abs(samples)))

    length = int(FRAME_SECONDS * sample_rate)
    hop = int(HOP_SECONDS * sample_rate)
    frames = _frames(samples, length, hop)

    pitch = np.full(len(frames), NAN)
    periodicity = np.zeros(len(frames))
    rms = np.sqrt((frames**2).mean(axis=1))
    for index, frame in enumerate(frames):
        pitch[index], periodicity[index] = _pitch_of(frame, sample_rate)

    with np.errstate(divide="ignore"):
        level = 20 * np.log10(np.maximum(rms, 1e-12))
    # A frame far below the loudest one is silence. Frames that are quiet but periodic stay
    # voiced: a weak moan is exactly the thing worth keeping.
    floor = level.max() - SILENCE_BELOW_PEAK_DB if len(level) else -np.inf
    pitch[(level < floor) & (periodicity < VOICING_FLOOR)] = NAN

    reading.pitch = pitch
    reading.level_db = level
    reading.periodicity = periodicity
    reading.periods, reading.period_amplitudes = _mark_periods(
        samples, sample_rate, pitch, hop, length
    )

    # Syllable nuclei: peaks in the loudness envelope, no closer than a syllable apart.
    if len(level):
        smoothed = np.convolve(level, np.ones(5) / 5, mode="same")
        found, _ = find_peaks(
            smoothed,
            distance=max(1, int(SYLLABLE_SPACING_SECONDS / HOP_SECONDS)),
            prominence=3.0,
        )
        reading.syllables = len(found)

    # Sustained vocalisation: a voiced run holding its pitch inside a narrow band.
    hold = max(1, int(SUSTAIN_SECONDS / HOP_SECONDS))
    voiced = ~np.isnan(pitch)
    sustained = 0
    index = 0
    while index < len(pitch):
        if not voiced[index]:
            index += 1
            continue
        stop = index
        while stop < len(pitch) and voiced[stop]:
            stop += 1
        run = pitch[index:stop]
        if len(run) >= hold:
            reference = float(np.median(run))
            steady = np.abs(run - reference) <= reference * SUSTAIN_PITCH_TOLERANCE
            # Counted over the whole run rather than per window, because a moan that
            # wavers once in the middle is still a moan.
            if steady.mean() >= 0.8:
                sustained += len(run)
        index = stop
    reading.sustained_seconds = sustained * HOP_SECONDS

    power, frequencies = _spectrogram(samples, sample_rate)
    if power.size:
        total = power.sum(axis=1)
        safe = np.maximum(total, 1e-20)
        reading.spectral_centroid = (power @ frequencies) / safe
        cumulative = np.cumsum(power, axis=1) / safe[:, None]
        reading.spectral_rolloff = frequencies[
            np.argmax(cumulative >= ROLLOFF_SHARE, axis=1)
        ]

        bands = power @ _mel_filterbank(sample_rate).T
        decibels = 10 * np.log10(np.maximum(bands, 1e-10))
        decibels = np.maximum(decibels, decibels.max() - MEL_TOP_DB)
        reading.mfcc = dct(decibels, type=2, norm="ortho", axis=1)[:, : schema.MFCC_COUNT]

        windows = _frames(samples, FFT_SIZE, MEL_HOP)
        reading.zero_crossing_rate = (
            np.abs(np.diff(np.sign(windows), axis=1)) > 0
        ).mean(axis=1)

    if sample_rate < schema.MINIMUM_SAMPLE_RATE_HZ:
        reading.notes.append(
            f"the audio was decoded at {sample_rate} Hz, below the "
            f"{schema.MINIMUM_SAMPLE_RATE_HZ:g} Hz the spectral measures are read over"
        )
    return reading
