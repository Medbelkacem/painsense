"""A synthetic signal generator, for developing and testing without hardware.

Everything this produces is labelled `SIMULATION` at the point it enters the database, and
every API response and every row carries that label onwards. The brief's rule is the right
one: simulated and real measurements must never sit together without a visible source, and
the way to guarantee that is to make the source a non-null column rather than a flag
someone can forget to set.

What it generates is plausible in *shape* — an EEG with a 1/f background and an alpha peak,
a surface EMG as band-limited noise with a slow activation envelope, a pulse waveform with a
dicrotic notch and beat-to-beat jitter, a skin conductance level with a few spontaneous
responses on it. It is not a model of a person and carries no information about pain. Its
purpose is to exercise the acquisition path, the quality checks and the interface, including
the failure modes: `fault` reproduces a detached electrode, a clipped amplifier and mains
hum, because those are what the quality checks exist to catch and they need testing.
"""

from __future__ import annotations

import numpy as np

from backend.signals import schema

#: Failure modes the simulator can inject, so the quality checks and the interface's
#: degraded states can be exercised deliberately.
FAULTS = ("none", "flatline", "saturated", "mains", "missing")

#: A pulse interval carries three things, and the simulated one carries all three: a slow
#: wander over half a minute, the respiratory swing (sinus arrhythmia), and beat-to-beat
#: noise. Each is a share of the interval, at a frequency in hertz. The slow term is what
#: puts SDNN above RMSSD, which is the order a resting pulse comes in; without it the two
#: features cannot be told apart in testing.
SLOW_SHARE = 0.06
SLOW_HZ = 0.03
RSA_SHARE = 0.025
RSA_HZ = 0.25


def _pink(rng: np.random.Generator, n: int) -> np.ndarray:
    """Noise with a 1/f amplitude spectrum, which is what a resting EEG background looks
    like. White noise does not, and the band-power features would be flat across bands."""
    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    freqs = np.fft.rfftfreq(n)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / np.sqrt(freqs[1:])
    shaped = np.fft.irfft(spectrum * scale, n=n)
    sd = shaped.std()
    return shaped / sd if sd > 0 else shaped


def _eeg(rng: np.random.Generator, t: np.ndarray, *, alpha_uv: float) -> np.ndarray:
    n = len(t)
    background = 12.0 * _pink(rng, n)
    alpha = alpha_uv * np.sin(2 * np.pi * 10.0 * t + rng.uniform(0, 2 * np.pi))
    # A slow amplitude envelope, so alpha is not a perfectly stationary tone.
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 2 * np.pi))
    beta = 4.0 * np.sin(2 * np.pi * 20.0 * t + rng.uniform(0, 2 * np.pi))
    return background + alpha * envelope + beta


def _emg(rng: np.random.Generator, t: np.ndarray, rate: float, *, activation: float) -> np.ndarray:
    from scipy import signal as scipy_signal

    n = len(t)
    raw = rng.normal(0, 1, n)
    low, high = schema.EMG_BAND
    nyquist = rate / 2
    high = min(high, nyquist - 1.0)
    if high > low:
        b, a = scipy_signal.butter(4, [low / nyquist, high / nyquist], btype="bandpass")
        raw = scipy_signal.filtfilt(b, a, raw)
    envelope = activation * (0.4 + 0.6 * np.abs(np.sin(2 * np.pi * 0.15 * t)))
    return raw / (raw.std() or 1.0) * envelope


def _ppg(
    rng: np.random.Generator, t: np.ndarray, *, bpm: float, jitter_ms: float
) -> np.ndarray:
    """A pulse waveform: a systolic peak, a dicrotic notch, and beats that are not evenly
    spaced. Not a cardiac model.

    The spacing is the point of it. Beats laid down at an exact period give a variability of
    zero, and a test that only asked whether SDNN and RMSSD had been derived would pass on a
    pulse no person has. So the interval wanders slowly, breathes with the respiratory cycle
    and carries a little beat-to-beat noise — see `SLOW_SHARE` and `RSA_SHARE` for why all
    three are there and not just the noise.
    """
    period = 60.0 / bpm
    beats: list[float] = []
    phase = rng.uniform(0, 2 * np.pi)
    at = period
    while at < t[-1]:
        beats.append(at)
        wander = (
            1.0
            + SLOW_SHARE * np.sin(2 * np.pi * SLOW_HZ * at + phase)
            + RSA_SHARE * np.sin(2 * np.pi * RSA_HZ * at)
        )
        at += max(0.3, period * wander + rng.normal(0, jitter_ms / 1000.0))

    wave = np.zeros_like(t)
    for beat in beats:
        phase = t - beat
        wave += np.exp(-((phase / 0.05) ** 2))
        wave += 0.35 * np.exp(-(((phase - 0.18) / 0.07) ** 2))
    return wave


def _gsr(
    rng: np.random.Generator, t: np.ndarray, *, baseline_us: float, per_min: float
) -> np.ndarray:
    """A slowly wandering skin conductance level with spontaneous responses on it.

    Each response has the asymmetric shape skin conductance actually has — a rise over about
    a second and a recovery over several — because that shape is what the feature extractor
    looks for when it counts them. A symmetric bump would be counted too, which would make
    the count look better tested than it is.
    """
    values = baseline_us + 0.3 * np.sin(
        2 * np.pi * 0.01 * t + rng.uniform(0, 2 * np.pi)
    )
    for onset in rng.uniform(t[0], t[-1], max(1, round(per_min * t[-1] / 60.0))):
        phase = t - onset
        after = phase >= 0
        response = np.zeros_like(t)
        response[after] = rng.uniform(0.1, 0.6) * (
            np.exp(-phase[after] / 4.0) * (1.0 - np.exp(-phase[after] / 0.7))
        )
        values = values + response
    return values + rng.normal(0, 0.004, len(t))


def _apply_fault(values: np.ndarray, fault: str, channel: schema.Channel, t: np.ndarray) -> np.ndarray:
    if fault == "flatline":
        return np.zeros_like(values)
    if fault == "saturated":
        return np.clip(values * 50.0, -channel.saturation, channel.saturation)
    if fault == "mains":
        hum = 10.0 * float(np.std(values) or 1.0) * np.sin(2 * np.pi * schema.MAINS_HZ[0] * t)
        return values + hum
    if fault == "missing":
        spoiled = values.astype(float).copy()
        spoiled[len(spoiled) // 3 : len(spoiled) // 2] = np.nan
        return spoiled
    return values


def generate(
    *,
    channels: list[str],
    rate: float = schema.DEFAULT_SAMPLE_RATE_HZ,
    seconds: float = 30.0,
    seed: int = 0,
    faults: dict[str, str] | None = None,
) -> dict[str, np.ndarray]:
    """Synthetic samples for the named channels.

    `faults` maps a channel to one of `FAULTS`, so a test can reproduce a detached
    electrode on one channel while the others record normally.
    """
    rng = np.random.default_rng(seed)
    n = max(1, round(rate * seconds))
    t = np.arange(n) / rate
    faults = faults or {}

    out: dict[str, np.ndarray] = {}
    for code in channels:
        channel = schema.CHANNEL_BY_CODE.get(code)
        if channel is None:
            continue
        if channel.modality == schema.EEG:
            values = _eeg(rng, t, alpha_uv=rng.uniform(10.0, 25.0))
        elif channel.modality == schema.EMG:
            values = _emg(rng, t, rate, activation=rng.uniform(20.0, 60.0))
        elif channel.modality == schema.PPG:
            values = _ppg(
                rng, t, bpm=rng.uniform(58.0, 88.0), jitter_ms=rng.uniform(8.0, 16.0)
            ) + rng.normal(0, 0.02, n)
        elif channel.modality == schema.GSR:
            values = _gsr(
                rng, t, baseline_us=rng.uniform(3.0, 12.0), per_min=rng.uniform(2.0, 6.0)
            )
        else:
            # Scaled to sit comfortably inside the belt amplifier's range, so a clean
            # simulated run does not read as a clipped trace.
            values = 1.5 * np.sin(2 * np.pi * rng.uniform(0.2, 0.35) * t) + rng.normal(
                0, 0.03, n
            )

        fault = faults.get(code, "none")
        if fault not in FAULTS:
            raise ValueError(f"unknown simulated fault {fault!r}; expected one of {FAULTS}")
        out[code] = _apply_fault(values, fault, channel, t)
    return out
