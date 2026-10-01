"""Deriving features from a recording.

Everything here is a standard signal measure with a name a physiologist would recognise.
None of it is a pain measure. EEG band powers, EMG amplitudes, pulse variability and skin
conductance all move with arousal, attention, movement, electrode placement, skin
temperature and how long the patient has been lying still — pain is one influence among
many, and this module makes no claim about which part of a number is which. That is truest
of the autonomic channels: skin conductance is a measure of arousal, and arousal is not
pain.

Two rules shape the output:

*A channel that failed quality gets no features.* Not zeros, not a mean — nothing. A
feature derived from a flat trace is a number with no referent, and the absence is recorded
per channel so the analysis can say which features exist and which do not.

*Band power is relative as well as absolute.* Absolute microvolts depend on electrode
impedance and amplifier gain and are not comparable between sessions. The relative shares
are, which is why both are reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.signals import quality as quality_module
from backend.signals import schema


@dataclass
class FeatureSet:
    schema_version: str = schema.FEATURE_SCHEMA_VERSION
    values: dict[str, float] = field(default_factory=dict)
    #: Channels features were derived from, and those skipped with the reason.
    derived_from: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "count": len(self.values),
            "values": {name: round(value, 6) for name, value in sorted(self.values.items())},
            "derived_from": self.derived_from,
            "skipped": self.skipped,
            "notes": self.notes,
        }


def _welch(values: np.ndarray, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Power spectral density by Welch's method.

    Segment length is a power of two under one eighth of the record, so a 20-second
    recording still gets several averaged segments. Averaging matters: a single
    periodogram of a noisy biosignal is far too variable to read band powers off.
    """
    from scipy import signal as scipy_signal

    target = max(256, 2 ** int(np.floor(np.log2(max(len(values) // 8, 256)))))
    nperseg = min(len(values), target)
    freqs, power = scipy_signal.welch(values, fs=rate, nperseg=nperseg)
    return freqs, power


def _band_power(freqs: np.ndarray, power: np.ndarray, low: float, high: float) -> float:
    band = (freqs >= low) & (freqs < high)
    if not band.any():
        return 0.0
    return float(np.trapezoid(power[band], freqs[band]))


def _spectral_edge(freqs: np.ndarray, power: np.ndarray, share: float) -> float:
    """The frequency below which `share` of the power lies.

    Reported because it summarises a spectral shift in one number, which band powers do
    only indirectly.
    """
    total = float(power.sum())
    if total <= 0:
        return 0.0
    cumulative = np.cumsum(power) / total
    index = int(np.searchsorted(cumulative, share))
    return float(freqs[min(index, len(freqs) - 1)])


def _eeg_features(code: str, values: np.ndarray, rate: float) -> dict[str, float]:
    freqs, power = _welch(values, rate)
    out: dict[str, float] = {}
    total = 0.0
    absolute: dict[str, float] = {}
    for name, low, high in schema.EEG_BANDS:
        if low >= rate / 2:
            continue
        value = _band_power(freqs, power, low, min(high, rate / 2 - 1e-9))
        absolute[name] = value
        total += value
    for name, value in absolute.items():
        out[f"{code}__{name}_power"] = value
        out[f"{code}__{name}_relative"] = value / total if total > 0 else 0.0

    # Ratios conventionally reported in the EEG literature. Reported because readers look
    # for them, not because this platform has related either to pain.
    alpha = absolute.get("alpha", 0.0)
    beta = absolute.get("beta", 0.0)
    theta = absolute.get("theta", 0.0)
    out[f"{code}__alpha_beta_ratio"] = alpha / beta if beta > 0 else 0.0
    out[f"{code}__theta_alpha_ratio"] = theta / alpha if alpha > 0 else 0.0
    out[f"{code}__total_power"] = total
    out[f"{code}__spectral_edge_95"] = _spectral_edge(freqs, power, 0.95)
    out[f"{code}__rms"] = float(np.sqrt(np.mean(values**2)))
    return out


def _emg_features(code: str, values: np.ndarray, rate: float) -> dict[str, float]:
    from scipy import signal as scipy_signal

    low, high = schema.EMG_BAND
    high = min(high, rate / 2 - 1e-9)
    out: dict[str, float] = {}
    if high <= low:
        return out

    # Band-pass before amplitude features: unfiltered surface EMG carries a movement
    # baseline that dominates RMS and says nothing about muscle activity.
    nyquist = rate / 2
    try:
        b, a = scipy_signal.butter(4, [low / nyquist, high / nyquist], btype="bandpass")
        filtered = scipy_signal.filtfilt(b, a, values)
    except ValueError:
        filtered = values - values.mean()

    out[f"{code}__rms"] = float(np.sqrt(np.mean(filtered**2)))
    out[f"{code}__mav"] = float(np.mean(np.abs(filtered)))
    out[f"{code}__waveform_length"] = float(np.sum(np.abs(np.diff(filtered))) / len(filtered))
    # Zero crossings and slope sign changes, with a small threshold so noise around zero
    # does not inflate either.
    threshold = 0.01 * out[f"{code}__rms"]
    signs = np.sign(filtered)
    out[f"{code}__zero_crossings_per_s"] = float(
        np.sum((signs[:-1] * signs[1:] < 0) & (np.abs(np.diff(filtered)) > threshold))
        / (len(filtered) / rate)
    )
    gradient = np.diff(filtered)
    out[f"{code}__slope_sign_changes_per_s"] = float(
        np.sum(np.sign(gradient[:-1]) * np.sign(gradient[1:]) < 0) / (len(filtered) / rate)
    )

    freqs, power = _welch(filtered, rate)
    total = float(power.sum())
    if total > 0:
        out[f"{code}__mean_frequency"] = float(np.sum(freqs * power) / total)
        out[f"{code}__median_frequency"] = _spectral_edge(freqs, power, 0.5)
    out[f"{code}__band_power"] = _band_power(freqs, power, low, high)
    return out


def _rate_from_spectrum(
    values: np.ndarray, rate: float, *, low: float, high: float
) -> float | None:
    """A rate in events per minute, from the dominant frequency in a plausible band.

    A spectral estimate rather than peak detection, because a respiration trace has no
    landmark as sharp as a systolic upstroke: where a belt is applied loosely the excursion
    is smooth enough that any peak threshold is either tuned per patient or wrong.

    Two things are needed to make it accurate enough to show a clinician. The spectrum is
    taken over the whole record rather than in averaged segments, because the segmenting
    that stabilises a band-power estimate costs frequency resolution — and at the segment
    length used for EEG, the bins are 0.5 Hz apart, while the whole respiratory band is
    0.6 Hz wide. Then the peak is interpolated parabolically across its neighbours, which
    recovers the true frequency to well inside one bin. Without both, every breathing rate
    this module can report would land on the same two numbers.
    """
    from scipy import signal as scipy_signal

    if len(values) < 64 or rate <= 0:
        return None
    detrended = scipy_signal.detrend(values)
    freqs, power = scipy_signal.periodogram(detrended, fs=rate, window="hann")
    ceiling = min(high, rate / 2 - 1e-9)
    band = (freqs >= low) & (freqs <= ceiling)
    if not band.any() or power[band].sum() <= 0:
        return None

    indices = np.flatnonzero(band)
    peak = int(indices[int(np.argmax(power[indices]))])
    dominant = float(freqs[peak])

    # Parabolic interpolation on the log spectrum, which is the standard correction for a
    # windowed peak falling between two bins.
    if 0 < peak < len(power) - 1:
        left, centre, right = (float(np.log(max(power[peak + offset], 1e-30))) for offset in (-1, 0, 1))
        denominator = left - 2 * centre + right
        if denominator != 0:
            shift = 0.5 * (left - right) / denominator
            if abs(shift) <= 1:
                dominant += shift * float(freqs[1] - freqs[0])

    if not low <= dominant <= ceiling:
        return None
    return round(dominant * 60.0, 1) if dominant > 0 else None


#: Beats needed before an interval series is worth reading anything off. Two beats give one
#: interval, which is a rate with no variability behind it.
PULSE_MIN_BEATS = 3

#: Threshold a deflection has to clear to be counted as a skin-conductance response, in
#: microsiemens. The conventional minimum for a non-specific response; a smaller deflection
#: is not distinguishable from the amplifier's own noise.
SCR_THRESHOLD_US = 0.01

#: Window the tonic level is estimated over before responses are counted, in seconds; the
#: window the trace is smoothed over before the peaks are found; and the closest two
#: responses can be and still be counted separately. The first is an upper bound — on a short
#: record the window shrinks rather than the count being refused.
SCR_BASELINE_SECONDS = 8.0
SCR_SMOOTH_SECONDS = 0.5
SCR_SEPARATION_SECONDS = 1.0


def _pulse_intervals(values: np.ndarray, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Beat-to-beat intervals in milliseconds, and which of them are physiologically possible.

    Both are returned because the variability measures need to know where the gaps are, not
    only which intervals survived: a difference taken across a dropped beat is an artefact
    of the gap and nothing else.
    """
    from scipy import signal as scipy_signal

    low, high = schema.PULSE_BAND
    nyquist = rate / 2
    # Band-passed well above the pulse rate, because the detector keys on the systolic
    # upstroke and filtering down to the fundamental would round every beat into a sine.
    top = min(8.0, nyquist - 1e-9)
    empty = (np.empty(0), np.empty(0, dtype=bool))
    if top <= low or len(values) < rate:
        return empty

    b, a = scipy_signal.butter(2, [low / nyquist, top / nyquist], btype="bandpass")
    filtered = scipy_signal.filtfilt(b, a, values)
    spread = float(np.std(filtered))
    if spread <= 0:
        return empty

    # Half a standard deviation of prominence rejects the diastolic notch without rejecting
    # a weak beat, and no two beats can be closer than the top of the pulse band allows.
    peaks, _ = scipy_signal.find_peaks(
        filtered, prominence=0.5 * spread, distance=max(1, int(rate / high))
    )
    if len(peaks) < PULSE_MIN_BEATS:
        return empty

    # An interval measured over a beat the detector missed is twice as long as the beats
    # either side of it. Those are marked rather than averaged in: one of them moves RMSSD
    # further than a minute of real beats does.
    intervals = np.diff(peaks) / rate * 1000.0
    possible = (intervals >= 1000.0 / high) & (intervals <= 1000.0 / low)
    return intervals, possible


def _pulse_features(code: str, values: np.ndarray, rate: float) -> dict[str, float]:
    """Pulse rate and the time-domain variability measures, from the beats in the waveform.

    SDNN and RMSSD are the two figures a reader expects, and they are reported over this
    recording's length. That is shorter than the five minutes they are conventionally
    measured over, so they are smaller and noisier than a published norm and must not be
    compared with one — the analysis says so alongside them.

    Nothing here tells a noisy trace from a quiet pulse. Peaks found in a channel that is
    recording nothing but interference produce a rate, and the quality report is what says
    the channel was interference; this function trusts it.
    """
    out: dict[str, float] = {}
    intervals, possible = _pulse_intervals(values, rate)
    accepted = intervals[possible]

    # The rate comes from the same beats the variability does, not from the spectrum, which
    # would survive a trace with no findable beats in it and report a plausible pulse beside
    # a variability figure derived from nothing. Where the beats are not there, neither
    # number is.
    if len(accepted) < 2:
        return out

    mean_ms = float(np.mean(accepted))
    out[f"{code}__heart_rate_bpm"] = round(60000.0 / mean_ms, 1)
    out[f"{code}__ibi_mean_ms"] = mean_ms
    out[f"{code}__sdnn_ms"] = float(np.std(accepted, ddof=1))

    adjacent = possible[:-1] & possible[1:]
    if adjacent.any():
        successive = np.diff(intervals)[adjacent]
        out[f"{code}__rmssd_ms"] = float(np.sqrt(np.mean(successive**2)))
        out[f"{code}__pnn50"] = float(np.mean(np.abs(successive) > 50.0))
    return out


def _scr_count(values: np.ndarray, rate: float) -> int:
    """Spontaneous skin-conductance responses, counted with the slow drift taken out.

    A response is a rise of a second or two sitting on a level that wanders over minutes.
    Subtracting a several-second moving average leaves the rises and takes the wander away;
    without that step a steadily climbing baseline hides every peak on it.

    The count is of non-specific responses — ones with no stimulus behind them, because this
    module is given no stimulus to relate them to. It is not a count of responses to pain.
    """
    from scipy import ndimage
    from scipy import signal as scipy_signal

    # Half the record where that is shorter than the nominal window: half of even the
    # shortest recording this module accepts is still several times longer than a response,
    # which is all the baseline estimate has to be.
    window = min(int(rate * SCR_BASELINE_SECONDS), len(values) // 2)
    if window < 3:
        return 0
    level = ndimage.uniform_filter1d(values, size=window, mode="nearest")
    # Smoothed before the peaks are found. A response rises over about a second, so
    # averaging over half of one costs nothing of the shape and keeps sensor noise from
    # clearing the threshold and being counted as a response of its own.
    phasic = ndimage.uniform_filter1d(
        values - level, size=max(3, int(rate * SCR_SMOOTH_SECONDS)), mode="nearest"
    )
    peaks, _ = scipy_signal.find_peaks(
        phasic,
        prominence=SCR_THRESHOLD_US,
        distance=max(1, int(rate * SCR_SEPARATION_SECONDS)),
    )
    return len(peaks)


def _gsr_features(code: str, values: np.ndarray, rate: float) -> dict[str, float]:
    """The tonic level, its drift, and the rate of spontaneous responses.

    Skin conductance carries two things at once: a slow level that moves with arousal over
    minutes, and brief responses riding on it. Both are reported, and neither is separated
    out with a model — a tonic/phasic decomposition needs an assumption about the shape of a
    response that this module does not make, and the figures it would produce would look
    more exact than the measurement is.
    """
    out = {
        f"{code}__mean_us": float(np.mean(values)),
        f"{code}__sd_us": float(np.std(values)),
        f"{code}__range_us": float(np.ptp(values)),
    }
    seconds = len(values) / rate
    if seconds <= 0:
        return out
    # Drift as the slope of a straight line through the record, per minute because that is
    # the scale skin conductance moves on.
    seconds_axis = np.arange(len(values)) / rate
    out[f"{code}__slope_us_per_min"] = float(np.polyfit(seconds_axis, values, 1)[0]) * 60.0
    out[f"{code}__scr_per_min"] = _scr_count(values, rate) / (seconds / 60.0)
    return out


def extract(
    samples: dict[str, np.ndarray], *, rate: float, report: quality_module.Report
) -> FeatureSet:
    """Features for every channel the quality report found usable."""
    out = FeatureSet()
    for code, raw in samples.items():
        channel = schema.CHANNEL_BY_CODE.get(code)
        verdict = report.for_channel(code)
        if channel is None:
            out.skipped[code] = "not a channel this platform defines"
            continue
        if verdict is None or not verdict.usable:
            out.skipped[code] = (
                f"signal quality {verdict.verdict.lower()}"
                if verdict
                else "no quality assessment"
            )
            continue

        values = np.asarray(raw, dtype=float)
        values = values[np.isfinite(values)]
        if len(values) < 32:
            out.skipped[code] = "too few finite samples"
            continue

        if channel.modality == schema.EEG:
            out.values.update(_eeg_features(code, values, rate))
        elif channel.modality == schema.EMG:
            out.values.update(_emg_features(code, values, rate))
        elif channel.modality == schema.PPG:
            out.values.update(_pulse_features(code, values, rate))
        elif channel.modality == schema.GSR:
            out.values.update(_gsr_features(code, values, rate))
        elif channel.modality == schema.RESPIRATION:
            low, high = schema.RESPIRATION_BAND
            respiration = _rate_from_spectrum(values, rate, low=low, high=high)
            if respiration is not None:
                out.values[f"{code}__respiration_per_min"] = respiration
        out.derived_from.append(code)

    out.notes.append(
        "These are standard spectral and amplitude measures. They move with arousal, "
        "attention, movement and electrode placement as well as with pain, and none of "
        "them is a pain measure on its own."
    )
    if any(name.endswith("__rmssd_ms") for name in out.values):
        out.notes.append(
            "Heart-rate variability is reported over the length of this recording. SDNN and "
            "RMSSD are conventionally measured over five minutes; over a shorter window they "
            "come out smaller and noisier and are not comparable with a published figure."
        )
    if out.skipped:
        out.notes.append(
            "No feature was derived for "
            + ", ".join(sorted(out.skipped))
            + "; a feature from an unusable trace would be a number with no referent."
        )
    return out


def summary(features: FeatureSet) -> dict:
    """The handful of figures the results panel shows, pulled out of the full set."""
    values = features.values

    def _mean(suffix: str, modality: str) -> float | None:
        picked = [
            value
            for name, value in values.items()
            if name.endswith(suffix)
            and schema.CHANNEL_BY_CODE.get(name.split("__")[0], None) is not None
            and schema.CHANNEL_BY_CODE[name.split("__")[0]].modality == modality
        ]
        return round(float(np.mean(picked)), 4) if picked else None

    def _first(suffix: str, digits: int) -> float | None:
        found = next(
            (value for name, value in values.items() if name.endswith(suffix)), None
        )
        return round(found, digits) if found is not None else None
    return {
        "eeg": {
            "alpha_relative": _mean("__alpha_relative", schema.EEG),
            "beta_relative": _mean("__beta_relative", schema.EEG),
            "theta_relative": _mean("__theta_relative", schema.EEG),
            "delta_relative": _mean("__delta_relative", schema.EEG),
            "gamma_relative": _mean("__gamma_relative", schema.EEG),
            "alpha_beta_ratio": _mean("__alpha_beta_ratio", schema.EEG),
            "spectral_edge_95_hz": _mean("__spectral_edge_95", schema.EEG),
        },
        "emg": {
            "rms_uv": _mean("__rms", schema.EMG),
            "mav_uv": _mean("__mav", schema.EMG),
            "median_frequency_hz": _mean("__median_frequency", schema.EMG),
            "zero_crossings_per_s": _mean("__zero_crossings_per_s", schema.EMG),
        },
        "heart_rate_bpm": _first("__heart_rate_bpm", 1),
        "hrv_rmssd_ms": _first("__rmssd_ms", 1),
        "skin_conductance_us": _first("__mean_us", 3),
        "respiration_per_min": _first("__respiration_per_min", 1),
    }
