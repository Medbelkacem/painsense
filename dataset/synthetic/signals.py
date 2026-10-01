"""Simulated per-second physiological recordings for the pain estimation prototype.

Every number this module produces comes from a model, not a person. The point is not to
imitate a particular study's data but to reproduce the *confusions* a pain estimator has to
survive: a stressed patient and a patient in moderate pain both run a fast heart and a wet
palm, a febrile patient's tachycardia looks like sympathetic arousal, and exertion moves all
three of heart rate, respiration and electrodermal level at once. A model that separates
pain from those states on this dataset has at least learned to use the features that
distinguish them in people — timing, facial expression, temperature, movement — rather than
arousal alone.

Each scenario below carries the physiology it is imitating in its comments, with the
direction and rough magnitude of every term, so that a term can be argued with.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

GENERATOR_VERSION = "1"

WARNING = (
    "SIMULATED DATA. Every value here was produced by a numerical model of autonomic "
    "physiology and measured from nobody. It has no clinical validity, describes no real "
    "population, and must not be used to fit, calibrate or validate anything intended to "
    "be pointed at a patient."
)

REST = "REST"
PAIN = "PAIN"
STRESS = "STRESS"
EXERTION = "EXERTION"
FEVER = "FEVER"
SCENARIOS = (REST, PAIN, STRESS, EXERTION, FEVER)

# The per-second channels. Names carry their units because a dataset that says "temp" and
# leaves the reader to guess Celsius is a dataset that will be misread.
SIGNALS = (
    "heart_rate_bpm",
    "hrv_rmssd_ms",
    "eda_us",
    "eda_tonic_us",
    "eda_phasic_us",
    "respiration_rate_brpm",
    "skin_temp_c",
    "accel_magnitude_g",
    "facial_pspi",
    "voice_energy",
)

SIGNAL_COLUMNS = (
    "patient_id",
    "session_id",
    "time_s",
    *SIGNALS,
    # Protocol annotation, not a measurement: 1 while a nociceptive stimulus is applied.
    # Always 0 outside PAIN, which is what makes event-locked features learnable at all.
    "stimulus",
    "scenario",
    "pain_level",
    # The second state present in the same session, where one was superimposed. This is the
    # ground truth of the overlap and the only honest way to report it.
    "superimposed_state",
    "split",
    "synthetic",
)

# Physiologically bounded ranges. A simulated value outside these is a bug in a coefficient,
# not an unusual patient, so the trace is clipped rather than left to say 300 bpm.
LIMITS = {
    "heart_rate_bpm": (35.0, 210.0),
    "hrv_rmssd_ms": (2.0, 200.0),
    "eda_tonic_us": (0.05, 40.0),
    "eda_phasic_us": (0.0, 20.0),
    "respiration_rate_brpm": (5.0, 60.0),
    "skin_temp_c": (28.0, 42.0),
    "accel_magnitude_g": (0.0, 4.0),
    "facial_pspi": (0.0, 16.0),
    "voice_energy": (0.0, 1.0),
}

# Liebermeister's rule: heart rate rises roughly 8 beats per minute for each degree of
# fever. Used both to generate the febrile tachycardia and, in the feature table, to take it
# back out again — a model given the corrected figure has a fighting chance of not calling
# a fever pain.
LIEBERMEISTER_BPM_PER_C = 8.0

# On the Prkachin and Solomon Pain Intensity scale a frame of 3 or more is conventionally
# read as strong pain, 1 as a trace. The cut matters: a frightened brow clears 2 as often as
# a pain grimace does, and only the higher cut separates them.
PSPI_STRONG = 3.0

# Heart rate attributable to movement, in beats per minute per g of mean acceleration above
# rest. Deliberately crude: it is the same rough correction a wearable would apply.
MOVEMENT_HR_BPM_PER_G = 42.0

# Tanaka's age-predicted maximum heart rate, used to scale the exertion response so a
# 70-year-old does not reach 190 bpm on a treadmill.
TANAKA_INTERCEPT = 208.0
TANAKA_SLOPE = 0.7


@dataclass(frozen=True)
class Config:
    """Every tunable in one place. Nothing below reads a literal that is not here."""

    patients: int = 50
    sessions_per_patient: int = 8
    session_seconds: int = 300
    seed: int = 42
    test_share: float = 0.25

    # Resting values drawn once per patient and held for every one of that patient's
    # sessions, because the individual baseline is the thing every feature is measured
    # against. RMSSD is the widest range of the four: resting vagal tone varies far more
    # between people than resting heart rate does.
    baseline_hr_bpm: tuple[float, float] = (60.0, 90.0)
    baseline_resp_brpm: tuple[float, float] = (12.0, 18.0)
    baseline_eda_us: tuple[float, float] = (1.0, 5.0)
    baseline_skin_temp_c: tuple[float, float] = (33.0, 35.0)
    baseline_rmssd_ms: tuple[float, float] = (18.0, 70.0)
    age_years: tuple[int, int] = (20, 75)

    # How often each scenario is the primary state of a session. The first session of every
    # patient is forced to REST regardless, so that a baseline exists to measure against.
    scenario_mix: tuple[tuple[str, float], ...] = (
        (REST, 0.20),
        (PAIN, 0.42),
        (STRESS, 0.16),
        (EXERTION, 0.12),
        (FEVER, 0.10),
    )

    # Between-subject response gains. These, more than the noise, are what stop the problem
    # being trivially separable: a highly reactive patient at pain 3 and a flat responder at
    # pain 8 produce overlapping traces, which is exactly what happens in a clinic.
    autonomic_gain: tuple[float, float] = (0.55, 1.55)
    vagal_gain: tuple[float, float] = (0.60, 1.40)
    eda_gain: tuple[float, float] = (0.30, 1.80)
    facial_gain: tuple[float, float] = (0.25, 1.40)
    vocal_gain: tuple[float, float] = (0.00, 1.30)
    noise_gain: tuple[float, float] = (0.70, 1.40)

    # Share of patients who are electrodermal non-responders, and the share whose faces give
    # nothing away. Both are real and both are the reason a single-channel estimator fails
    # on somebody. Applied by forcing that patient's gain to near zero.
    eda_nonresponder_share: float = 0.10
    stoic_share: float = 0.16

    # Share of sessions carrying a second state at reduced amplitude: pain on top of a
    # fever, stress on top of pain, pain during exertion.
    overlap_share: float = 0.35
    overlap_scale: tuple[float, float] = (0.40, 0.85)

    # Session-to-session variation in the resting state itself. A patient recorded on two
    # days does not start from the same place: sleep, caffeine, posture, where the
    # electrodes went and how warm the room is all move the baseline by about as much as a
    # mild stimulus does. Without this the deltas are unrealistically clean and every class
    # separates on a single channel.
    session_hr_shift_sd: float = 3.5
    session_resp_shift_sd: float = 0.9
    session_eda_scale: tuple[float, float] = (0.70, 1.45)
    session_rmssd_scale: tuple[float, float] = (0.80, 1.25)
    # Room temperature, as seen at the skin. Wide enough that skin temperature alone cannot
    # call a fever, which is the point: it is a useful feature, not a thermometer.
    ambient_shift_c: tuple[float, float] = (-1.2, 1.2)

    # Movement unrelated to the scenario: being repositioned, reaching for a glass, walking
    # to a chair. Present in every scenario, so a raised accelerometer does not by itself
    # mean exertion, and raising heart rate and respiration with it, because it is real
    # movement.
    incidental_bursts: tuple[int, int] = (0, 4)
    incidental_burst_g: tuple[float, float] = (0.08, 0.45)
    incidental_burst_seconds: tuple[float, float] = (5.0, 40.0)

    # The face is unusable in some share of sessions: a mask, a turned head, an endotracheal
    # tube, a camera that lost the subject. The facial channel is the strongest single
    # predictor of pain here, so a model that cannot work without it will fail on exactly
    # the patients who most need it.
    face_unavailable_share: float = 0.12

    # Self-report is the reference standard and it is noisy. `pain_level` is what the
    # patient said; the physiology is driven by a latent intensity that differs from it by a
    # standing per-patient bias — the stoic who says 4 and means 7, the catastrophiser who
    # says 9 and means 6 — plus session-to-session noise. Set both to zero to recover a
    # dataset in which the label is a deterministic function of the signals.
    report_bias_sd: float = 1.3
    report_noise_sd: float = 0.9

    # Sensor failure. A gap is contiguous, because electrodes lift and wristbands lose
    # contact for seconds at a time rather than for isolated samples.
    dropout_share: float = 0.015
    dropout_seconds: tuple[int, int] = (3, 20)
    # Multiplier on the gap rate for the channels a photoplethysmograph derives, while the
    # limb is moving. Motion artefact is the reason exertion sessions are the dirtiest.
    motion_dropout_factor: float = 4.0
    motion_dropout_threshold_g: float = 0.15

    def scenario_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.scenario_mix)

    def scenario_weights(self) -> np.ndarray:
        weights = np.array([weight for _, weight in self.scenario_mix], dtype=float)
        return weights / weights.sum()


@dataclass(frozen=True)
class Patient:
    patient_id: str
    age: int
    baseline_hr: float
    baseline_rmssd: float
    baseline_eda: float
    baseline_resp: float
    baseline_temp: float
    autonomic_gain: float
    vagal_gain: float
    eda_gain: float
    facial_gain: float
    vocal_gain: float
    noise_gain: float
    # Positive means this patient reports higher than their physiology suggests.
    report_bias: float

    @property
    def hr_reserve(self) -> float:
        """Beats per minute between rest and the age-predicted maximum."""
        return max(TANAKA_INTERCEPT - TANAKA_SLOPE * self.age - self.baseline_hr, 25.0)


@dataclass(frozen=True)
class SessionPlan:
    session_id: str
    patient_id: str
    scenario: str
    pain_level: int
    superimposed: str | None
    overlap_scale: float


@dataclass(frozen=True)
class SessionContext:
    """What differs between two recordings of the same patient, before anything happens.

    Everything here is a nuisance parameter in the statistical sense and a fact of life in
    the clinical one. It is drawn per session and recorded in the patient table only as the
    distribution it came from, because a model is not given these at inference time either.
    """

    hr_shift: float
    resp_shift: float
    eda_scale: float
    rmssd_scale: float
    ambient_shift: float
    face_available: bool
    report_noise: float


@dataclass
class Trace:
    """Working buffers for one session, already in the units of the output columns."""

    seconds: int
    hr: np.ndarray
    rmssd: np.ndarray
    eda_tonic: np.ndarray
    eda_phasic: np.ndarray
    resp: np.ndarray
    temp: np.ndarray
    accel: np.ndarray
    pspi: np.ndarray
    voice: np.ndarray
    stimulus: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.stimulus = np.zeros(self.seconds, dtype=np.int8)


def _draw(rng: np.random.Generator, bounds: tuple[float, float]) -> float:
    return float(rng.uniform(*bounds))


def _ou(rng: np.random.Generator, seconds: int, tau: float, sigma: float) -> np.ndarray:
    """Ornstein-Uhlenbeck drift.

    Physiological baselines wander; they do not jitter. White noise added to a resting heart
    rate produces a trace no filter would ever see, so every baseline here drifts with a
    correlation time, and the sensor's own white noise is added separately at the end.
    """
    decay = float(np.exp(-1.0 / tau))
    step = sigma * float(np.sqrt(max(1.0 - decay**2, 1e-12)))
    white = rng.normal(0.0, 1.0, seconds)
    out = np.empty(seconds)
    out[0] = sigma * white[0]
    for index in range(1, seconds):
        out[index] = decay * out[index - 1] + step * white[index]
    return out


def _event_response(
    seconds: int, onset: float, rise_tau: float, decay_tau: float
) -> np.ndarray:
    """Unit-peak biexponential: rises over `rise_tau`, decays over `decay_tau`.

    The shape every phasic autonomic response takes — a skin conductance response, the heart
    rate answer to a noxious stimulus, a grimace. Peak-normalised so the caller supplies the
    amplitude in the signal's own units.
    """
    time = np.arange(seconds, dtype=float) - onset
    shape = np.where(time >= 0.0, np.exp(-time / decay_tau) - np.exp(-time / rise_tau), 0.0)
    peak = float(shape.max())
    return shape / peak if peak > 1e-9 else shape


def _ramp(seconds: int, onset: float, tau: float) -> np.ndarray:
    """Saturating exponential rise, for states that build rather than fire."""
    time = np.arange(seconds, dtype=float) - onset
    return np.where(time >= 0.0, 1.0 - np.exp(-time / tau), 0.0)


def _window(seconds: int, start: float, stop: float, edge: float = 4.0) -> np.ndarray:
    """A bout with soft edges, for a stretch of activity that starts and then stops."""
    time = np.arange(seconds, dtype=float)
    rising = 1.0 / (1.0 + np.exp(-(time - start) / edge))
    falling = 1.0 / (1.0 + np.exp((time - stop) / edge))
    return rising * falling


def _spontaneous_scrs(
    rng: np.random.Generator,
    seconds: int,
    per_minute: float,
    amplitude: tuple[float, float],
) -> np.ndarray:
    """Non-specific skin conductance responses.

    A resting palm fires one to three of these a minute with no stimulus at all. Their rate
    climbs with arousal, which is why a phasic peak count alone cannot tell pain from
    anxiety; only the alignment with a stimulus can.
    """
    trace = np.zeros(seconds)
    count = rng.poisson(per_minute * seconds / 60.0)
    for onset in rng.uniform(0.0, seconds, int(count)):
        trace += _draw(rng, amplitude) * _event_response(seconds, onset, 1.8, 5.5)
    return trace


def _resting_trace(
    rng: np.random.Generator, patient: Patient, context: SessionContext, seconds: int
) -> Trace:
    """The trace a patient produces lying still, and the floor every scenario builds on.

    Heart rate carries a 0.1 Hz Mayer wave on top of its drift — the baroreflex oscillation
    that is present in everyone awake — because a resting heart rate with no rhythm in it is
    the first thing that makes simulated data obvious. The session context shifts the whole
    resting level, so that the same patient recorded twice does not start twice from the
    same number.
    """
    noise = patient.noise_gain
    time = np.arange(seconds, dtype=float)

    resting_hr = patient.baseline_hr + context.hr_shift
    resting_eda = patient.baseline_eda * context.eda_scale
    resting_rmssd = patient.baseline_rmssd * context.rmssd_scale

    mayer = 1.1 * np.sin(2.0 * np.pi * 0.1 * time + rng.uniform(0.0, 2.0 * np.pi))
    hr = resting_hr + mayer + _ou(rng, seconds, tau=25.0, sigma=1.7 * noise)
    rmssd = resting_rmssd * (1.0 + _ou(rng, seconds, tau=20.0, sigma=0.13 * noise))

    # Tonic electrodermal level falls slowly through a quiet recording as the subject
    # settles; the fall is small but it is the wrong sign for every aroused state, so it is
    # worth having in the baseline.
    settling = -0.06 * resting_eda * _ramp(seconds, 0.0, 120.0)
    eda_tonic = (
        resting_eda + settling + resting_eda * _ou(rng, seconds, tau=90.0, sigma=0.07 * noise)
    )
    eda_phasic = patient.eda_gain * _spontaneous_scrs(rng, seconds, 1.8, (0.02, 0.22))

    resp = (
        patient.baseline_resp
        + context.resp_shift
        + _ou(rng, seconds, tau=15.0, sigma=0.75 * noise)
    )
    # Skin under a sensor warms by a tenth of a degree or so as the contact equilibrates,
    # and sits wherever the room puts it.
    temp = (
        patient.baseline_temp
        + context.ambient_shift
        + 0.12 * _ramp(seconds, 0.0, 150.0)
        + _ou(rng, seconds, tau=150.0, sigma=0.05 * noise)
    )

    accel = 0.011 + 0.006 * np.abs(rng.normal(0.0, 1.0, seconds))
    for onset in rng.uniform(0.0, seconds, rng.poisson(2.0)):
        accel += _draw(rng, (0.02, 0.07)) * _event_response(seconds, onset, 0.7, 2.5)

    # A face at rest scores zero on the PSPI most of the time; blinks and idle brow movement
    # put the occasional one or two on the board, and an estimator that treats any non-zero
    # PSPI as pain will learn that from here.
    pspi = np.zeros(seconds)
    for onset in rng.uniform(0.0, seconds, rng.poisson(2.5)):
        pspi += _draw(rng, (0.3, 1.4)) * patient.facial_gain * _event_response(
            seconds, onset, 0.8, 2.0
        )

    voice = 0.03 + 0.012 * np.abs(rng.normal(0.0, 1.0, seconds))

    return Trace(seconds, hr, rmssd, eda_tonic, eda_phasic, resp, temp, accel, pspi, voice)


def _apply_pain(
    rng: np.random.Generator,
    patient: Patient,
    trace: Trace,
    *,
    level: float,
    scale: float = 1.0,
    mark_stimulus: bool = True,
) -> None:
    """Event-locked nociception at a latent intensity of roughly 1 to 10.

    What makes pain separable in principle is its *timing*: three to six discrete stimuli,
    each answered within a few seconds and gone within half a minute. Everything else here —
    tachycardia, vagal withdrawal, sweating — a frightened or febrile patient also does.

    Magnitudes, per stimulus, at the top of the scale and before the patient's own gain:
      heart rate   +8-9 bpm, latency ~2 s, peak ~6 s, recovery tau 14 s
      RMSSD        -45% of baseline, recovering more slowly than heart rate does
      phasic EDA   +1.3 uS, the single largest discrete deflection in the dataset
      respiration  a breath held at onset, then compensatory tachypnoea and irregularity
      PSPI         up to 13 of 16, in a face that shows anything at all
      skin temp    a slow drift down from distal vasoconstriction, capped at -0.5 C
    """
    seconds = trace.seconds
    gain = patient.autonomic_gain * scale
    events = int(rng.integers(3, 7))
    spacing = seconds / events

    for index in range(events):
        onset = float(index * spacing + rng.uniform(0.1 * spacing, 0.5 * spacing))
        duration = float(rng.uniform(10.0, 25.0))
        if mark_stimulus:
            start, stop = int(onset), min(int(onset + duration), seconds)
            trace.stimulus[start:stop] = 1

        cardiac = _event_response(seconds, onset + 2.0, 2.5, 14.0)
        trace.hr += (0.5 + 0.8 * level) * gain * cardiac
        trace.rmssd -= (
            (0.02 + 0.043 * level)
            * patient.vagal_gain
            * scale
            * patient.baseline_rmssd
            * _event_response(seconds, onset + 2.0, 3.0, 25.0)
        )

        trace.eda_phasic += (
            (0.05 + 0.125 * level)
            * patient.eda_gain
            * scale
            * _event_response(seconds, onset + rng.uniform(1.5, 3.0), 1.8, 5.5)
        )

        # Breath-holding first, then the overshoot. The dip is why respiration *rate* alone
        # reads ambiguously in the first seconds of a stimulus, and why the useful feature is
        # not the rate but its second-to-second roughness.
        trace.resp -= 0.34 * level * gain * _event_response(seconds, onset, 1.0, 3.5)
        trace.resp += 0.26 * level * gain * _event_response(seconds, onset + 4.0, 2.5, 12.0)
        # Roughness confined to the stimulus. Spread over the whole session it would raise
        # the session's variance without making the breathing look disordered at any moment,
        # which is the opposite of what pain does.
        trace.resp += (
            _ou(rng, seconds, tau=3.0, sigma=0.22 * level * gain)
            * _event_response(seconds, onset, 1.5, 0.5 * duration)
        )

        trace.accel += (0.04 + 0.022 * level) * _event_response(seconds, onset, 0.6, 2.0)
        trace.pspi += (
            (0.35 + 1.25 * level)
            * patient.facial_gain
            * scale
            * _event_response(seconds, onset + 1.0, 1.5, 6.0)
        )

        # Vocalisation is close to absent below a self-report of about 5 and common above 8,
        # and some people never make a sound at all.
        if rng.random() < float(np.clip((level - 4.0) / 8.0, 0.0, 0.85)) * patient.vocal_gain:
            trace.voice += (0.18 + 0.055 * level) * _event_response(
                seconds, onset + rng.uniform(0.5, 3.0), 1.0, 4.0
            )

    trace.eda_tonic += 0.035 * level * patient.eda_gain * scale * _ramp(seconds, 0.0, 90.0)
    trace.temp -= min(0.028 * level * gain, 0.5) * _ramp(seconds, 0.0, 110.0)


def _apply_stress(
    rng: np.random.Generator,
    patient: Patient,
    trace: Trace,
    *,
    scale: float = 1.0,
) -> None:
    """Anticipatory stress, anxiety or fear: arousal with no event to lock to.

    The hardest confounder in the set, because its autonomic signature is pain's signature
    with the timing removed. Three things separate it here, and a model has to find at least
    one of them: the rise is monotone over a minute or more rather than repeated and brief;
    the facial score stays low and *sustained* where pain's is high and punctate; and skin
    temperature falls without any stimulus to explain it.
    """
    seconds = trace.seconds
    gain = patient.autonomic_gain * scale
    onset = float(rng.uniform(20.0, 60.0))
    build = _ramp(seconds, onset, float(rng.uniform(70.0, 140.0)))

    trace.hr += _draw(rng, (6.0, 18.0)) * gain * build
    trace.rmssd -= (
        _draw(rng, (0.15, 0.40)) * patient.vagal_gain * scale * patient.baseline_rmssd * build
    )

    # The hallmark: tonic electrodermal level climbs and stays up, with many small
    # non-specific responses rather than a few large stimulus-locked ones.
    trace.eda_tonic += _draw(rng, (0.8, 3.5)) * patient.eda_gain * scale * build
    trace.eda_phasic += patient.eda_gain * scale * _spontaneous_scrs(
        rng, seconds, _draw(rng, (4.0, 10.0)), (0.02, 0.12)
    )

    # Breathing speeds up but stays regular, unlike the stop-start pattern pain produces.
    trace.resp += _draw(rng, (1.5, 4.5)) * gain * build
    trace.temp -= _draw(rng, (0.15, 0.50)) * build

    # Fidgeting: the mean barely moves, the second-to-second difference does.
    trace.accel += 0.015 * build + 0.010 * np.abs(rng.normal(0.0, 1.0, seconds)) * build

    # The fear face shares the PSPI's brow-lowering term with the pain face, so the score is
    # not zero — it is low, and it does not come and go with anything.
    trace.pspi += _draw(rng, (0.6, 2.8)) * patient.facial_gain * scale * build
    trace.voice += _draw(rng, (0.02, 0.09)) * build


def _apply_exertion(
    rng: np.random.Generator,
    patient: Patient,
    trace: Trace,
    *,
    scale: float = 1.0,
) -> None:
    """A bout of physical effort, then recovery.

    Separable on movement, which is the whole point of carrying an accelerometer: the
    cardiorespiratory rise is larger than pain's but it is accompanied by a mean
    acceleration an order of magnitude above rest, and it decays over minutes rather than
    seconds. Heart rate is scaled by the patient's own reserve so age is respected.
    """
    seconds = trace.seconds
    gain = patient.autonomic_gain * scale
    start = float(rng.uniform(30.0, 70.0))
    stop = min(start + float(rng.uniform(120.0, 220.0)), seconds - 10.0)
    bout = _window(seconds, start, stop, edge=6.0)
    # Cardiac kinetics lag the movement: the rise takes about 45 s and the fall after the
    # bout ends takes longer still, which is why a heart rate alone cannot say whether the
    # effort is over.
    time = np.arange(seconds, dtype=float)
    effort = _ramp(seconds, start, 45.0) * bout
    recovery = np.where(
        time > stop, float(effort.max()) * np.exp(-(time - stop) / 60.0), 0.0
    )
    cardiac = np.maximum(effort, recovery)

    trace.accel += _draw(rng, (0.25, 1.10)) * bout
    trace.accel += 0.08 * bout * np.abs(rng.normal(0.0, 1.0, seconds))

    trace.hr += patient.hr_reserve * _draw(rng, (0.35, 0.80)) * gain * cardiac
    trace.rmssd -= (
        _draw(rng, (0.35, 0.65)) * patient.vagal_gain * scale * patient.baseline_rmssd * cardiac
    )
    trace.resp += _draw(rng, (6.0, 18.0)) * gain * cardiac

    # Thermoregulatory sweating starts late and lingers, so the electrodermal rise is
    # delayed relative to the heart rate rise — a timing cue a model can use.
    trace.eda_tonic += (
        _draw(rng, (0.6, 3.0)) * patient.eda_gain * scale * _ramp(seconds, start + 45.0, 60.0)
    )

    # Wrist skin cools briefly as blood is shunted to muscle, then warms as heat is dumped.
    trace.temp -= 0.10 * _ramp(seconds, start, 25.0)
    trace.temp += _draw(rng, (0.20, 0.80)) * _ramp(seconds, start + 90.0, 70.0)

    # Effort grimace. Low, but not zero, and it overlaps the bottom of the pain range.
    trace.pspi += _draw(rng, (0.2, 1.8)) * patient.facial_gain * scale * cardiac
    trace.voice += _draw(rng, (0.05, 0.25)) * patient.vocal_gain * scale * cardiac


def _apply_fever(
    rng: np.random.Generator,
    patient: Patient,
    trace: Trace,
    *,
    scale: float = 1.0,
) -> None:
    """A febrile patient, warm from the first second of the recording.

    Fever is the cleanest confounder to correct for and the easiest to miss: its tachycardia
    follows the temperature at about 8 bpm per degree, so a patient 2.5 C above their own
    baseline arrives with 20 extra beats a minute and no pain at all. The temperature is
    already there when the recording starts — a fever takes hours, not minutes — and creeps
    a further fraction of a degree over the five minutes; the heart rate is what builds
    visibly, over a couple of minutes. Shivering, in about two sessions in five, puts tremor
    into the accelerometer with almost no mean acceleration, which is the signature that
    distinguishes it from exertion.
    """
    seconds = trace.seconds
    gain = patient.autonomic_gain * scale
    offset = _draw(rng, (1.5, 3.0)) * scale
    temperature = offset + _draw(rng, (0.0, 0.3)) * _ramp(seconds, 0.0, 130.0)
    established = 0.55 + 0.45 * _ramp(seconds, 0.0, 110.0)

    trace.temp += temperature
    trace.hr += LIEBERMEISTER_BPM_PER_C * temperature * gain * established
    trace.rmssd -= (
        _draw(rng, (0.20, 0.45))
        * patient.vagal_gain
        * scale
        * patient.baseline_rmssd
        * established
    )
    trace.resp += _draw(rng, (2.0, 6.0)) * gain * established
    trace.eda_tonic += _draw(rng, (0.3, 1.6)) * patient.eda_gain * scale * established

    if rng.random() < 0.4:
        shivering = np.abs(rng.normal(0.0, 1.0, seconds)) * _draw(rng, (0.02, 0.06))
        trace.accel += shivering * _window(
            seconds, rng.uniform(0.0, 0.3 * seconds), rng.uniform(0.6 * seconds, seconds), 10.0
        )

    # Malaise: a drawn face and a quiet voice. Both point away from pain.
    trace.pspi += _draw(rng, (0.3, 2.2)) * patient.facial_gain * scale * established
    trace.voice -= 0.01 * established


def _apply_incidental_movement(
    rng: np.random.Generator, patient: Patient, trace: Trace, config: Config
) -> None:
    """Movement that has nothing to do with the scenario, in every scenario.

    A patient is repositioned, reaches for a glass, walks to a chair. Without it the
    accelerometer is a perfect exertion detector and the hardest real confound — a patient
    who moved and a patient who exerted themselves — disappears. The cardiorespiratory
    consequence comes with it, because the heart does not know why the arm moved.
    """
    seconds = trace.seconds
    low, high = config.incidental_bursts
    for _ in range(int(rng.integers(low, high + 1))):
        start = float(rng.uniform(0.0, seconds))
        stop = start + _draw(rng, config.incidental_burst_seconds)
        magnitude = _draw(rng, config.incidental_burst_g)
        burst = _window(seconds, start, stop, edge=3.0)

        trace.accel += magnitude * burst
        trace.accel += 0.06 * magnitude * burst * np.abs(rng.normal(0.0, 1.0, seconds))
        # The same beats-per-g the feature table uses to take movement back out again, so
        # the correction is removing something that was genuinely put there.
        trace.hr += MOVEMENT_HR_BPM_PER_G * magnitude * patient.autonomic_gain * burst
        trace.resp += 6.0 * magnitude * burst
        trace.rmssd -= 0.18 * patient.baseline_rmssd * patient.vagal_gain * burst


def _apply_scenario(
    rng: np.random.Generator,
    patient: Patient,
    trace: Trace,
    scenario: str,
    *,
    level: float,
    scale: float,
    mark_stimulus: bool,
) -> None:
    if scenario == PAIN:
        _apply_pain(rng, patient, trace, level=level, scale=scale, mark_stimulus=mark_stimulus)
    elif scenario == STRESS:
        _apply_stress(rng, patient, trace, scale=scale)
    elif scenario == EXERTION:
        _apply_exertion(rng, patient, trace, scale=scale)
    elif scenario == FEVER:
        _apply_fever(rng, patient, trace, scale=scale)
    elif scenario != REST:
        raise ValueError(f"unknown scenario {scenario!r}")


def _add_sensor_noise(rng: np.random.Generator, trace: Trace, patient: Patient) -> None:
    """Instrument error, separate from physiological variation.

    Each figure is the error of the *estimate*, not of the underlying quantity: an RMSSD read
    from a wrist photoplethysmograph is several milliseconds out however steady the heart is,
    and an action-unit intensity from a video model is a few tenths out on every frame.
    """
    noise = patient.noise_gain
    trace.hr += rng.normal(0.0, 0.55 * noise, trace.seconds)
    trace.rmssd += rng.normal(0.0, 2.2 * noise, trace.seconds)
    trace.eda_tonic += rng.normal(0.0, 0.012 * noise, trace.seconds)
    trace.eda_phasic += rng.normal(0.0, 0.008 * noise, trace.seconds)
    trace.resp += rng.normal(0.0, 0.40 * noise, trace.seconds)
    trace.temp += rng.normal(0.0, 0.022 * noise, trace.seconds)
    trace.accel += rng.normal(0.0, 0.004 * noise, trace.seconds)
    trace.pspi += rng.normal(0.0, 0.30 * noise, trace.seconds)
    trace.voice += rng.normal(0.0, 0.010 * noise, trace.seconds)


# Channels a wrist photoplethysmograph derives, and therefore the ones motion ruins.
PPG_DERIVED = ("heart_rate_bpm", "hrv_rmssd_ms")


def _apply_dropouts(
    rng: np.random.Generator, frame: pd.DataFrame, config: Config
) -> pd.DataFrame:
    """Blank contiguous runs of samples, per channel.

    Gaps are per channel because sensors fail independently: an electrode lifts while the
    camera keeps running. The rate is raised for photoplethysmographic channels while the
    limb is moving, which makes exertion sessions the ones with the most missing heart rate —
    the same asymmetry a real wearable study has to live with.
    """
    seconds = len(frame)
    moving = frame["accel_magnitude_g"].to_numpy() > config.motion_dropout_threshold_g
    low, high = config.dropout_seconds
    mean_gap = 0.5 * (low + high)

    for column in SIGNALS:
        if column == "eda_us":
            continue
        rate = config.dropout_share / mean_gap
        starts = rng.random(seconds) < rate
        if column in PPG_DERIVED:
            extra = rng.random(seconds) < rate * (config.motion_dropout_factor - 1.0)
            starts |= extra & moving
        values = frame[column].to_numpy(dtype=float, copy=True)
        for start in np.flatnonzero(starts):
            values[start : start + int(rng.integers(low, high + 1))] = np.nan
        frame[column] = values

    # The total is a sum of two channels, so it is missing wherever either part is.
    frame["eda_us"] = frame["eda_tonic_us"] + frame["eda_phasic_us"]
    return frame


def draw_patients(rng: np.random.Generator, config: Config) -> list[Patient]:
    patients = []
    for index in range(config.patients):
        eda = _draw(rng, config.eda_gain)
        if rng.random() < config.eda_nonresponder_share:
            eda = _draw(rng, (0.02, 0.15))
        facial = _draw(rng, config.facial_gain)
        if rng.random() < config.stoic_share:
            facial = _draw(rng, (0.02, 0.20))
        patients.append(
            Patient(
                patient_id=f"P{index + 1:03d}",
                age=int(rng.integers(config.age_years[0], config.age_years[1] + 1)),
                baseline_hr=_draw(rng, config.baseline_hr_bpm),
                baseline_rmssd=_draw(rng, config.baseline_rmssd_ms),
                baseline_eda=_draw(rng, config.baseline_eda_us),
                baseline_resp=_draw(rng, config.baseline_resp_brpm),
                baseline_temp=_draw(rng, config.baseline_skin_temp_c),
                autonomic_gain=_draw(rng, config.autonomic_gain),
                vagal_gain=_draw(rng, config.vagal_gain),
                eda_gain=eda,
                facial_gain=facial,
                vocal_gain=_draw(rng, config.vocal_gain),
                noise_gain=_draw(rng, config.noise_gain),
                report_bias=float(rng.normal(0.0, config.report_bias_sd)),
            )
        )
    return patients


# Which second state may sit underneath which primary one. Rest means rest; everything else
# can be contaminated, and pain is the contaminant that matters most.
OVERLAP_CANDIDATES = {
    PAIN: (FEVER, EXERTION, STRESS),
    STRESS: (PAIN, EXERTION),
    EXERTION: (PAIN, STRESS),
    FEVER: (PAIN, STRESS),
}


def plan_sessions(
    rng: np.random.Generator, patient: Patient, config: Config
) -> list[SessionPlan]:
    """One patient's sessions. The first is always REST, so a baseline always exists."""
    names = config.scenario_names()
    weights = config.scenario_weights()
    plans = []
    for index in range(config.sessions_per_patient):
        scenario = REST if index == 0 else str(rng.choice(names, p=weights))
        superimposed = None
        scale = 0.0
        if scenario != REST and rng.random() < config.overlap_share:
            superimposed = str(rng.choice(OVERLAP_CANDIDATES[scenario]))
            scale = _draw(rng, config.overlap_scale)

        if scenario == PAIN:
            level = int(rng.integers(1, 11))
        elif superimposed == PAIN:
            # Pain hiding inside a confounder session is mild to moderate by construction:
            # a patient in agony would have been recorded as a pain session.
            level = int(rng.integers(1, 6))
        else:
            level = 0

        plans.append(
            SessionPlan(
                session_id=f"{patient.patient_id}_S{index + 1:02d}",
                patient_id=patient.patient_id,
                scenario=scenario,
                pain_level=level,
                superimposed=superimposed,
                overlap_scale=scale,
            )
        )
    return plans


def draw_context(rng: np.random.Generator, config: Config) -> SessionContext:
    return SessionContext(
        hr_shift=float(rng.normal(0.0, config.session_hr_shift_sd)),
        resp_shift=float(rng.normal(0.0, config.session_resp_shift_sd)),
        eda_scale=_draw(rng, config.session_eda_scale),
        rmssd_scale=_draw(rng, config.session_rmssd_scale),
        ambient_shift=_draw(rng, config.ambient_shift_c),
        face_available=bool(rng.random() >= config.face_unavailable_share),
        report_noise=float(rng.normal(0.0, config.report_noise_sd)),
    )


def latent_intensity(patient: Patient, context: SessionContext, reported: int) -> float:
    """What the body is doing, given what the patient said.

    The label is the self-report because the self-report is the reference standard, and the
    physiology is driven by this instead. The gap between them is the ceiling on how well
    any model can do here, and it is the same ceiling that exists in the clinic.
    """
    if reported <= 0:
        return 0.0
    return float(np.clip(reported - patient.report_bias - context.report_noise, 0.3, 11.0))


def simulate_session(
    rng: np.random.Generator, patient: Patient, plan: SessionPlan, config: Config
) -> pd.DataFrame:
    seconds = config.session_seconds
    context = draw_context(rng, config)
    trace = _resting_trace(rng, patient, context, seconds)
    intensity = latent_intensity(patient, context, plan.pain_level)

    _apply_scenario(
        rng,
        patient,
        trace,
        plan.scenario,
        level=intensity if plan.scenario == PAIN else 0.0,
        scale=1.0,
        mark_stimulus=True,
    )
    if plan.superimposed is not None:
        _apply_scenario(
            rng,
            patient,
            trace,
            plan.superimposed,
            level=intensity if plan.superimposed == PAIN else 0.0,
            scale=plan.overlap_scale,
            # A stimulus marker is a record of the protocol. Pain arriving as a
            # contaminant was never part of a protocol, so it is not marked, and a model
            # cannot cheat by reading the annotation.
            mark_stimulus=False,
        )

    _apply_incidental_movement(rng, patient, trace, config)
    _add_sensor_noise(rng, trace, patient)
    if not context.face_available:
        trace.pspi[:] = np.nan

    frame = pd.DataFrame(
        {
            "patient_id": patient.patient_id,
            "session_id": plan.session_id,
            "time_s": np.arange(seconds, dtype=np.int32),
            "heart_rate_bpm": trace.hr,
            "hrv_rmssd_ms": trace.rmssd,
            "eda_tonic_us": trace.eda_tonic,
            "eda_phasic_us": np.maximum(trace.eda_phasic, 0.0),
            "respiration_rate_brpm": trace.resp,
            "skin_temp_c": trace.temp,
            "accel_magnitude_g": np.maximum(trace.accel, 0.0),
            "facial_pspi": trace.pspi,
            "voice_energy": trace.voice,
            "stimulus": trace.stimulus,
        }
    )
    for column, (low, high) in LIMITS.items():
        frame[column] = frame[column].clip(low, high)
    frame["eda_us"] = frame["eda_tonic_us"] + frame["eda_phasic_us"]

    frame = _apply_dropouts(rng, frame, config)
    frame["scenario"] = plan.scenario
    frame["pain_level"] = np.int16(plan.pain_level)
    frame["superimposed_state"] = plan.superimposed
    frame["synthetic"] = True
    return frame


# Channels whose resting level is worth holding per patient. The phasic part of the
# electrodermal signal has no resting level worth the name, so it is not baselined.
BASELINE_CHANNELS = (
    "heart_rate_bpm",
    "hrv_rmssd_ms",
    "eda_tonic_us",
    "respiration_rate_brpm",
    "skin_temp_c",
    "accel_magnitude_g",
    "facial_pspi",
    "voice_energy",
)


def patient_baseline(rest: pd.DataFrame) -> dict[str, float]:
    """A patient's own resting level, from their REST sessions only.

    The median, not the mean, so that a dropout-adjacent artefact or a single sneeze does not
    move the reference every later feature is measured against. The resting standard
    deviation of respiration is kept too, because the useful pain feature is not how fast a
    patient is breathing but how much *less regularly* than usual.
    """
    baseline = {column: float(rest[column].median()) for column in BASELINE_CHANNELS}
    resting_resp = rest["respiration_rate_brpm"].to_numpy(dtype=float)
    baseline["respiration_rate_brpm_sd"] = float(np.nanstd(resting_resp))
    baseline["respiration_rate_brpm_jitter"] = _jitter(resting_resp)
    return baseline


RESP_SMOOTH_SECONDS = 5

NOTHING = float("nan")


def _reduce(values: np.ndarray, how: Callable[[np.ndarray], float]) -> float:
    """Apply a reduction, or report nothing if the channel was never recorded.

    A face the camera never saw is not a face with a PSPI of zero. Returning zero here is
    the single easiest way to teach a model that an intubated patient is comfortable.
    """
    if not np.isfinite(values).any():
        return NOTHING
    return float(how(values))


def _jitter(values: np.ndarray) -> float:
    """Mean second-to-second change, after smoothing off the estimator's own noise.

    A respiration rate read once a second carries a few tenths of a breath of estimator
    noise, which is larger than the physiological roughness being measured. Taken raw, this
    quantity measures the sensor; taken over a five-second mean, it measures the patient.
    """
    smoothed = (
        pd.Series(values).rolling(RESP_SMOOTH_SECONDS, min_periods=2, center=True).mean()
    )
    return float(smoothed.diff().abs().mean())


def _slope_per_minute(values: np.ndarray) -> float:
    """Least-squares trend, in signal units per minute."""
    time = np.arange(len(values), dtype=float)
    mask = np.isfinite(values)
    if mask.sum() < 10:
        return float("nan")
    fit = np.polyfit(time[mask], values[mask], 1)
    return float(fit[0] * 60.0)


def _max_rise(values: np.ndarray, window: int) -> float:
    """Largest increase from any sample to any sample within the next `window` seconds.

    The event-locked feature. A tonic ramp of twenty beats a minute over five minutes gains
    almost nothing on this measure; the same twenty beats arriving in six seconds gains all
    of it. It is the single most useful separator of pain from stress and fever here.
    """
    series = pd.Series(values)
    forward = series[::-1].rolling(window, min_periods=1).max()[::-1].to_numpy()
    rise = forward - values
    return float(np.nanmax(rise)) if np.isfinite(rise).any() else float("nan")


def _peaks(values: np.ndarray, threshold: float) -> np.ndarray:
    """Local maxima above `threshold`, for counting phasic responses."""
    filled = np.nan_to_num(values, nan=0.0)
    if len(filled) < 3:
        return np.array([])
    interior = filled[1:-1]
    rising = interior > filled[:-2]
    falling = interior >= filled[2:]
    return interior[rising & falling & (interior > threshold)]


def session_features(frame: pd.DataFrame, baseline: dict[str, float]) -> dict:
    """One row of features for one session, every delta against this patient's own rest.

    Absolute values are kept alongside the deltas because a model may legitimately use them,
    but the deltas are the point: a resting heart rate of 88 means nothing until it is read
    against the 62 that patient usually sits at.
    """
    seconds = len(frame)
    minutes = seconds / 60.0

    hr = frame["heart_rate_bpm"].to_numpy(dtype=float)
    rmssd = frame["hrv_rmssd_ms"].to_numpy(dtype=float)
    tonic = frame["eda_tonic_us"].to_numpy(dtype=float)
    phasic = frame["eda_phasic_us"].to_numpy(dtype=float)
    resp = frame["respiration_rate_brpm"].to_numpy(dtype=float)
    temp = frame["skin_temp_c"].to_numpy(dtype=float)
    accel = frame["accel_magnitude_g"].to_numpy(dtype=float)
    pspi = frame["facial_pspi"].to_numpy(dtype=float)
    voice = frame["voice_energy"].to_numpy(dtype=float)

    hr_delta = hr - baseline["heart_rate_bpm"]
    temp_delta = temp - baseline["skin_temp_c"]
    accel_delta = accel - baseline["accel_magnitude_g"]
    peaks = _peaks(phasic, 0.05)

    hr_delta_mean = float(np.nanmean(hr_delta))
    temp_delta_mean = float(np.nanmean(temp_delta))
    accel_delta_mean = float(np.nanmean(accel_delta))

    features = {
        "session_seconds": seconds,
        # Cardiac. The pair that matters is the mean rise and the fastest rise: pain earns
        # both, stress and fever earn only the first.
        "hr_mean": float(np.nanmean(hr)),
        "hr_delta_mean": hr_delta_mean,
        "hr_delta_max": _reduce(hr_delta, np.nanmax),
        "hr_delta_positive_auc": float(np.nansum(np.clip(hr_delta, 0.0, None)) / minutes),
        "hr_slope_per_min": _slope_per_minute(hr),
        "hr_rise_max_10s": _max_rise(hr, 10),
        # Vagal withdrawal, as a fraction of the patient's own resting RMSSD so that a
        # 15 ms drop from 20 is not read as the equal of a 15 ms drop from 70.
        "rmssd_mean": float(np.nanmean(rmssd)),
        "rmssd_relative_drop": 1.0 - float(np.nanmean(rmssd)) / baseline["hrv_rmssd_ms"],
        "rmssd_min_relative_drop": (
            1.0 - _reduce(rmssd, np.nanmin) / baseline["hrv_rmssd_ms"]
        ),
        # Electrodermal. Tonic level and slope say aroused; peak rate and amplitude say
        # something discrete happened.
        "eda_tonic_delta_mean": float(np.nanmean(tonic)) - baseline["eda_tonic_us"],
        "eda_tonic_slope_per_min": _slope_per_minute(tonic),
        "eda_phasic_peaks_per_min": len(peaks) / minutes,
        "eda_phasic_peak_mean": float(peaks.mean()) if len(peaks) else 0.0,
        "eda_phasic_peak_max": float(peaks.max()) if len(peaks) else 0.0,
        # Respiration, two different things. The spread of the rate is raised by anything
        # that ramps breathing, exertion most of all, so on its own it says only that the
        # patient is working. The roughness — the second-to-second change, measured after the
        # estimator's own noise is smoothed off — is raised by a stop-start pattern, which is
        # what a stimulus produces and what a smooth ramp does not.
        "resp_mean": float(np.nanmean(resp)),
        "resp_delta_mean": float(np.nanmean(resp)) - baseline["respiration_rate_brpm"],
        "resp_sd": float(np.nanstd(resp)),
        "resp_sd_ratio": (
            float(np.nanstd(resp)) / max(baseline["respiration_rate_brpm_sd"], 0.1)
        ),
        "resp_jitter_ratio": (
            _jitter(resp) / max(baseline["respiration_rate_brpm_jitter"], 0.01)
        ),
        # Temperature. The fever detector, and the term the corrected heart rate uses.
        "temp_delta_mean": temp_delta_mean,
        "temp_delta_max": _reduce(temp_delta, np.nanmax),
        "temp_slope_per_min": _slope_per_minute(temp),
        # Movement. The mean separates exertion from everything; the second-to-second
        # jitter separates shivering and fidgeting, which barely move the mean, from stillness.
        "accel_mean": float(np.nanmean(accel)),
        "accel_delta_mean": accel_delta_mean,
        "accel_active_share": float(np.nanmean(accel > 0.10)),
        "accel_jitter": float(np.nanmean(np.abs(np.diff(accel)))),
        # Face and voice. The two channels that are about pain rather than about arousal,
        # and the face is missing outright in the sessions where it is occluded.
        "pspi_mean": _reduce(pspi, np.nanmean),
        "pspi_max": _reduce(pspi, np.nanmax),
        "pspi_strong_share": _reduce(pspi, lambda x: np.nanmean(x >= PSPI_STRONG)),
        "pspi_rise_max_10s": _max_rise(pspi, 10),
        "face_available": bool(np.isfinite(pspi).any()),
        "voice_mean": _reduce(voice, np.nanmean),
        "voice_burst_share": _reduce(voice, lambda x: np.nanmean(x > 0.15)),
        # Confounder-corrected tachycardia. Each takes out the share of the heart rate rise
        # that movement or temperature already accounts for; what is left is the part a pain
        # model is entitled to treat as unexplained.
        "hr_delta_less_movement": hr_delta_mean - MOVEMENT_HR_BPM_PER_G * accel_delta_mean,
        "hr_delta_less_fever": hr_delta_mean - LIEBERMEISTER_BPM_PER_C * temp_delta_mean,
        "hr_delta_less_both": (
            hr_delta_mean
            - MOVEMENT_HR_BPM_PER_G * accel_delta_mean
            - LIEBERMEISTER_BPM_PER_C * temp_delta_mean
        ),
        # How much of this session was actually recorded. A feature, not a footnote: the
        # sessions with the most missing heart rate are the ones with the most movement.
        "missing_share": float(frame[list(SIGNALS)].isna().to_numpy().mean()),
    }
    return features


def assign_splits(
    rng: np.random.Generator, patients: list[Patient], test_share: float
) -> dict[str, str]:
    """Split by patient, never by session or by second.

    A split that puts two sessions from the same person on both sides of the boundary
    measures how well the model recognises that person, not how well it recognises pain.
    """
    identifiers = np.array([patient.patient_id for patient in patients])
    order = rng.permutation(len(identifiers))
    cut = round(len(identifiers) * test_share)
    test = set(identifiers[order[:cut]])
    return {
        identifier: ("test" if identifier in test else "train")
        for identifier in identifiers
    }


EXAMPLE_PANELS = (
    ("heart_rate_bpm", "heart rate (bpm)"),
    ("hrv_rmssd_ms", "RMSSD (ms)"),
    ("eda_us", "EDA (uS)"),
    ("respiration_rate_brpm", "respiration (breaths/min)"),
    ("skin_temp_c", "skin temperature (C)"),
    ("accel_magnitude_g", "movement (g)"),
    ("facial_pspi", "facial PSPI (0-16)"),
    ("voice_energy", "voice energy"),
)


def plot_examples(signals: pd.DataFrame, directory: Path) -> list[Path]:
    """One figure per scenario, eight stacked panels sharing a time axis.

    Imported here rather than at the top of the module: matplotlib is a development
    dependency, and a run that cannot draw should still produce its tables.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed; skipping plots")
        return []

    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for scenario in SCENARIOS:
        candidates = signals[signals["scenario"] == scenario]
        if candidates.empty:
            continue
        # Show the scenario on its own where a clean session exists, so the figure
        # illustrates one mechanism rather than two at once.
        clean = candidates[candidates["superimposed_state"].isna()]
        candidates = clean if not clean.empty else candidates
        # For pain, show a session in the upper half of the scale: a level-1 session is a
        # fair example of the class and a useless illustration of the mechanism.
        if scenario == PAIN:
            target = candidates["pain_level"].sub(7).abs().idxmin()
            session_id = candidates.loc[target, "session_id"]
        else:
            session_id = candidates["session_id"].iloc[0]
        session = signals[signals["session_id"] == session_id]
        plan_level = int(session["pain_level"].iloc[0])
        superimposed = session["superimposed_state"].iloc[0]

        figure, axes = plt.subplots(
            len(EXAMPLE_PANELS), 1, figsize=(9.5, 13.0), sharex=True
        )
        for axis, (column, label) in zip(axes, EXAMPLE_PANELS, strict=True):
            axis.plot(session["time_s"], session[column], linewidth=0.9, color="#1f4e79")
            axis.set_ylabel(label, fontsize=8)
            axis.tick_params(labelsize=7)
            axis.grid(alpha=0.25, linewidth=0.4)

        # Shade the stimulus windows across every panel so the event locking is visible.
        stimulus = session["stimulus"].to_numpy()
        edges = np.flatnonzero(np.diff(np.concatenate(([0], stimulus, [0]))) != 0)
        for start, stop in zip(edges[::2], edges[1::2], strict=True):
            for axis in axes:
                axis.axvspan(start, stop, color="#d94801", alpha=0.12, linewidth=0)

        axes[-1].set_xlabel("time (s)", fontsize=8)
        extra = f", with {superimposed.lower()}" if isinstance(superimposed, str) else ""
        figure.suptitle(
            f"SIMULATED {scenario}"
            + (f" at level {plan_level}" if plan_level else "")
            + f"{extra} - {session_id}",
            fontsize=11,
        )
        figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.98))
        path = directory / f"{scenario.lower()}.png"
        figure.savefig(path, dpi=130)
        plt.close(figure)
        written.append(path)
    return written


README = """# Simulated multimodal physiological dataset

{warning}

Generated by `app.datasets.signals` version {version} on {generated} with seed {seed}.
The same seed reproduces these files byte for byte.

| file | one row per | rows |
| --- | --- | --- |
| `signals.csv` | second of recording | {signal_rows} |
| `features.csv` | session, relative to that patient's resting baseline | {feature_rows} |
| `patients.csv` | virtual patient: baselines, gains, report bias, split | {patient_rows} |
| `splits.json` | - | train and test patient identifiers |
| `provenance/manifest.json` | - | every parameter of this run |
| `plots/` | - | one example session per scenario |

## Labels

`scenario` is the primary state of the session: `REST`, `PAIN`, `STRESS`, `EXERTION` or
`FEVER`. `superimposed_state` names a second state present at reduced amplitude, in
{overlap:.0%} of non-rest sessions. `pain_level` is the pain in the session on a 0-10 scale
whichever of the two columns it arrived through, so a febrile session with mild pain carries
`scenario=FEVER`, `superimposed_state=PAIN` and a non-zero `pain_level`.

`pain_level` is what the patient *said*, not what their body did. The physiology is driven by
a latent intensity that differs from the report by a standing per-patient bias and by
session noise, because self-report is the reference standard for pain and it is noisy. That
gap is the ceiling on how well any model can score here, and it is deliberate.

## What makes it hard

The confounders are not separable on arousal. Stress raises heart rate, electrodermal level
and respiration exactly as pain does, and does it without any event to lock to; fever raises
heart rate about 8 bpm per degree; exertion raises everything at once. Against that:

- the resting level shifts between sessions, so a delta is not a clean measurement;
- room temperature moves skin temperature by up to a degree either way, so the fever channel
  is not a thermometer;
- movement unrelated to the scenario appears in every scenario, and drags heart rate with it;
- the face is unusable in some sessions, and the face is the strongest single predictor;
- some patients are electrodermal non-responders and some show nothing in the face at all.

The first session of every patient is `REST`; that is where that patient's baseline comes
from, and every `*_delta_*` feature is measured against it.

## Splits

By patient, never by session. No patient appears in both.
"""


def write(config: Config, destination: Path) -> tuple[Path, dict]:
    started = datetime.now(timezone.utc)
    version = (
        f"signals-v{GENERATOR_VERSION}-{started.date().isoformat()}"
        f"-seed{config.seed}-p{config.patients}"
    )
    directory = destination / version
    (directory / "provenance").mkdir(parents=True, exist_ok=True)

    root = np.random.default_rng(config.seed)
    patients = draw_patients(root, config)
    splits = assign_splits(root, patients, config.test_share)
    # One independent stream per patient, so that a patient's trace does not change when
    # the patient count does.
    streams = root.spawn(len(patients))

    signals_path = directory / "signals.csv"
    feature_rows: list[dict] = []
    patient_rows: list[dict] = []
    scenario_counts: dict[str, int] = dict.fromkeys(SCENARIOS, 0)
    signal_rows = 0

    for patient, rng in zip(patients, streams, strict=True):
        plans = plan_sessions(rng, patient, config)
        frames = [simulate_session(rng, patient, plan, config) for plan in plans]
        for plan in plans:
            scenario_counts[plan.scenario] += 1

        recording = pd.concat(frames, ignore_index=True)
        recording["split"] = splits[patient.patient_id]
        recording = recording[list(SIGNAL_COLUMNS)]
        recording.to_csv(
            signals_path,
            mode="w" if signal_rows == 0 else "a",
            header=signal_rows == 0,
            index=False,
            float_format="%.4f",
        )
        signal_rows += len(recording)

        baseline = patient_baseline(recording[recording["scenario"] == REST])
        for plan, frame in zip(plans, frames, strict=True):
            feature_rows.append(
                {
                    "patient_id": patient.patient_id,
                    "session_id": plan.session_id,
                    "scenario": plan.scenario,
                    "pain_level": plan.pain_level,
                    "superimposed_state": plan.superimposed,
                    "split": splits[patient.patient_id],
                    **session_features(frame, baseline),
                    **{f"baseline_{name}": value for name, value in baseline.items()},
                    "synthetic": True,
                }
            )

        patient_rows.append(
            {
                **asdict(patient),
                "split": splits[patient.patient_id],
                "sessions": len(plans),
                "synthetic": True,
            }
        )

    features = pd.DataFrame(feature_rows)
    features.to_csv(directory / "features.csv", index=False, float_format="%.5f")
    pd.DataFrame(patient_rows).to_csv(
        directory / "patients.csv", index=False, float_format="%.4f"
    )

    train = sorted(identifier for identifier, split in splits.items() if split == "train")
    test = sorted(identifier for identifier, split in splits.items() if split == "test")
    overlap = sorted(set(train) & set(test))
    if overlap:
        raise AssertionError(f"patients in both splits: {overlap}")
    (directory / "splits.json").write_text(
        json.dumps({"train": train, "test": test}, indent=2), encoding="utf-8"
    )

    columns = [
        "session_id",
        "time_s",
        "stimulus",
        "scenario",
        "pain_level",
        "superimposed_state",
        *(column for column, _ in EXAMPLE_PANELS),
    ]
    plots = plot_examples(pd.read_csv(signals_path, usecols=columns), directory / "plots")

    manifest = {
        "version": version,
        "generator_version": GENERATOR_VERSION,
        "generated_at": started.isoformat(),
        "seed": config.seed,
        "synthetic": True,
        "warning": WARNING,
        "parameters": asdict(config),
        "counts": {
            "patients": len(patients),
            "sessions": len(feature_rows),
            "signal_rows": signal_rows,
            "scenarios": scenario_counts,
            "split_patients": {"train": len(train), "test": len(test)},
            "superimposed_sessions": int(features["superimposed_state"].notna().sum()),
        },
        "distribution": {
            "pain_level_counts": features["pain_level"].value_counts().sort_index().to_dict(),
            "missing_share": round(float(features["missing_share"].mean()), 5),
            "hr_delta_mean_by_scenario": features.groupby("scenario")["hr_delta_mean"]
            .mean()
            .round(2)
            .to_dict(),
            "pspi_mean_by_scenario": features.groupby("scenario")["pspi_mean"]
            .mean()
            .round(2)
            .to_dict(),
            "temp_delta_mean_by_scenario": features.groupby("scenario")["temp_delta_mean"]
            .mean()
            .round(2)
            .to_dict(),
        },
        "files": sorted(
            str(path.relative_to(directory))
            for path in directory.rglob("*")
            if path.is_file()
        ),
    }
    (directory / "provenance" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    (directory / "README.md").write_text(
        README.format(
            warning=WARNING,
            version=GENERATOR_VERSION,
            generated=started.date().isoformat(),
            seed=config.seed,
            signal_rows=f"{signal_rows:,}",
            feature_rows=f"{len(feature_rows):,}",
            patient_rows=f"{len(patient_rows):,}",
            overlap=config.overlap_share,
        ),
        encoding="utf-8",
    )
    manifest["plots"] = [str(path.relative_to(directory)) for path in plots]
    return directory, manifest


def main(argv: list[str] | None = None) -> None:
    defaults = Config()
    parser = argparse.ArgumentParser(
        description="Generate a simulated per-second multimodal physiological dataset."
    )
    parser.add_argument("--patients", type=int, default=defaults.patients)
    parser.add_argument("--sessions", type=int, default=defaults.sessions_per_patient)
    parser.add_argument("--session-seconds", type=int, default=defaults.session_seconds)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--test-share", type=float, default=defaults.test_share)
    parser.add_argument(
        "--overlap-share",
        type=float,
        default=defaults.overlap_share,
        help="share of non-rest sessions carrying a second state underneath",
    )
    parser.add_argument(
        "--dropout-share",
        type=float,
        default=defaults.dropout_share,
        help="share of samples blanked as sensor dropout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("datasets"),
        help="parent directory; a versioned subdirectory is created inside it",
    )
    arguments = parser.parse_args(argv)

    config = Config(
        patients=arguments.patients,
        sessions_per_patient=arguments.sessions,
        session_seconds=arguments.session_seconds,
        seed=arguments.seed,
        test_share=arguments.test_share,
        overlap_share=arguments.overlap_share,
        dropout_share=arguments.dropout_share,
    )
    directory, manifest = write(config, arguments.output)
    counts = manifest["counts"]

    print(f"SIMULATED DATA written to {directory}")
    print(
        f"{counts['patients']} patients  {counts['sessions']} sessions  "
        f"{counts['signal_rows']:,} seconds  seed {manifest['seed']}"
    )
    print(
        "sessions per scenario: "
        + ", ".join(f"{k} {v}" for k, v in counts["scenarios"].items())
    )
    print(
        f"superimposed second state in {counts['superimposed_sessions']} sessions; "
        f"{manifest['distribution']['missing_share']:.1%} of samples missing"
    )
    print(
        "mean heart rate rise over baseline, bpm: "
        + ", ".join(
            f"{k} {v:+.1f}"
            for k, v in manifest["distribution"]["hr_delta_mean_by_scenario"].items()
        )
    )
    print(
        "mean facial PSPI: "
        + ", ".join(
            f"{k} {v:.2f}" for k, v in manifest["distribution"]["pspi_mean_by_scenario"].items()
        )
    )
    if manifest["plots"]:
        print("plots: " + ", ".join(manifest["plots"]))


if __name__ == "__main__":
    main()
