"""Signal quality, feature extraction and the simulator.

The arithmetic is checked against signals constructed in the test, so a feature that drifts
is caught by its value and not only by its presence.
"""

import numpy as np
import pytest

from backend.signals import features, quality, schema, simulate

RATE = 512.0
SECONDS = 20.0


def _t(rate=RATE, seconds=SECONDS):
    return np.arange(int(rate * seconds)) / rate


def _sine(hz, amplitude=20.0, rate=RATE, seconds=SECONDS):
    return amplitude * np.sin(2 * np.pi * hz * _t(rate, seconds))


# --- quality ---------------------------------------------------------------------------


def test_a_clean_channel_passes():
    rng = np.random.default_rng(0)
    values = _sine(10.0) + rng.normal(0, 4, len(_t()))
    result = quality.assess_channel("EEG_FPZ", values, RATE)
    assert result.verdict in (quality.GOOD, quality.ADEQUATE)
    assert result.usable


def test_a_detached_electrode_is_unusable_not_quiet():
    result = quality.assess_channel("EEG_FPZ", np.full(int(RATE * SECONDS), 0.001), RATE)
    assert result.verdict == quality.UNUSABLE
    assert not result.usable
    assert "not connected" in result.findings[0]


def test_a_clipped_amplifier_is_unusable():
    saturation = schema.CHANNEL_BY_CODE["EEG_FPZ"].saturation
    values = np.clip(_sine(10.0, amplitude=saturation * 3), -saturation, saturation)
    result = quality.assess_channel("EEG_FPZ", values, RATE)
    assert result.verdict == quality.UNUSABLE
    assert result.saturated_share > quality.SATURATION_UNUSABLE


def test_mains_hum_is_detected_at_both_grid_frequencies():
    for mains in schema.MAINS_HZ:
        values = _sine(10.0, 3.0) + _sine(mains, 80.0)
        result = quality.assess_channel("EEG_FPZ", values, RATE)
        assert result.mains_share > quality.MAINS_POOR, f"{mains} Hz hum not detected"
        assert result.verdict == quality.UNUSABLE


def test_missing_samples_are_counted():
    values = _sine(10.0)
    values[100:2000] = np.nan
    result = quality.assess_channel("EEG_FPZ", values, RATE)
    assert result.missing_share > 0.1


def test_an_emg_channel_sampled_too_slowly_is_flagged():
    slow = 200.0
    rng = np.random.default_rng(1)
    values = rng.normal(0, 30, int(slow * SECONDS))
    result = quality.assess_channel("EMG_TRAPEZIUS_L", values, slow)
    assert any("below the" in finding for finding in result.findings)


def test_the_overall_verdict_ignores_a_slipped_respiration_belt():
    """A supporting channel must not invalidate a clean EEG and EMG recording."""
    rng = np.random.default_rng(2)
    samples = {
        "EEG_FPZ": _sine(10.0) + rng.normal(0, 4, len(_t())),
        "EMG_TRAPEZIUS_L": rng.normal(0, 30, len(_t())),
        "RESPIRATION_BELT": np.zeros(len(_t())),
    }
    report = quality.assess(samples, rate=RATE, duration=SECONDS)
    assert report.verdict in (quality.GOOD, quality.ADEQUATE)
    assert report.supporting_verdicts["RESPIRATION_BELT"] == quality.UNUSABLE


def test_a_detached_eeg_does_degrade_the_overall_verdict():
    rng = np.random.default_rng(3)
    samples = {
        "EEG_FPZ": np.zeros(len(_t())),
        "EMG_TRAPEZIUS_L": rng.normal(0, 30, len(_t())),
    }
    report = quality.assess(samples, rate=RATE, duration=SECONDS)
    assert report.verdict == quality.UNUSABLE


def test_a_recording_with_no_primary_channel_says_so():
    report = quality.assess({"PPG_FINGER": _sine(1.2, 1.0)}, rate=RATE, duration=SECONDS)
    assert any("no EEG or EMG channel" in finding for finding in report.findings)


def test_a_short_recording_is_flagged():
    rng = np.random.default_rng(4)
    short = 4.0
    samples = {"EEG_FPZ": rng.normal(0, 10, int(RATE * short))}
    report = quality.assess(samples, rate=RATE, duration=short)
    assert any("at least" in finding for finding in report.findings)


def test_an_empty_recording_is_unusable():
    assert quality.assess({}, rate=RATE, duration=0.0).verdict == quality.UNUSABLE


# --- features -----------------------------------------------------------------------------


def _report(samples, rate=RATE, duration=SECONDS):
    return quality.assess(samples, rate=rate, duration=duration)


def test_band_power_finds_the_band_the_signal_is_in():
    for band, low, high in schema.EEG_BANDS:
        centre = (low + high) / 2
        samples = {"EEG_FPZ": _sine(centre, 30.0)}
        extracted = features.extract(samples, rate=RATE, report=_report(samples))
        relative = extracted.values[f"EEG_FPZ__{band}_relative"]
        assert relative > 0.8, f"{band} at {centre} Hz gave only {relative:.2f}"


def test_relative_band_powers_sum_to_one():
    rng = np.random.default_rng(5)
    samples = {"EEG_FPZ": _sine(10.0) + _sine(20.0, 10.0) + rng.normal(0, 5, len(_t()))}
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    total = sum(
        value
        for name, value in extracted.values.items()
        if name.endswith("_relative")
    )
    assert total == pytest.approx(1.0, abs=0.01)


def test_the_alpha_beta_ratio_tracks_the_two_bands():
    strong_alpha = {"EEG_FPZ": _sine(10.0, 30.0) + _sine(20.0, 5.0)}
    strong_beta = {"EEG_FPZ": _sine(10.0, 5.0) + _sine(20.0, 30.0)}
    high = features.extract(strong_alpha, rate=RATE, report=_report(strong_alpha))
    low = features.extract(strong_beta, rate=RATE, report=_report(strong_beta))
    assert high.values["EEG_FPZ__alpha_beta_ratio"] > 1.0
    assert low.values["EEG_FPZ__alpha_beta_ratio"] < 1.0


def test_emg_amplitude_features_rise_with_activation():
    rng = np.random.default_rng(6)
    quiet = {"EMG_TRAPEZIUS_L": rng.normal(0, 10, len(_t()))}
    active = {"EMG_TRAPEZIUS_L": rng.normal(0, 60, len(_t()))}
    low = features.extract(quiet, rate=RATE, report=_report(quiet))
    high = features.extract(active, rate=RATE, report=_report(active))
    assert high.values["EMG_TRAPEZIUS_L__rms"] > low.values["EMG_TRAPEZIUS_L__rms"] * 3
    assert high.values["EMG_TRAPEZIUS_L__mav"] > low.values["EMG_TRAPEZIUS_L__mav"] * 3


@pytest.mark.parametrize(
    ("bpm", "hz"), [(48, 0.8), (60, 1.0), (72, 1.2), (90, 1.5), (120, 2.0)]
)
def test_pulse_rate_is_recovered_accurately(bpm, hz):
    rng = np.random.default_rng(7)
    samples = {
        "EEG_FPZ": rng.normal(0, 10, len(_t())),
        "PPG_FINGER": _sine(hz, 1.0) + rng.normal(0, 0.02, len(_t())),
    }
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    assert features.summary(extracted)["heart_rate_bpm"] == pytest.approx(bpm, abs=1.0)


def test_a_pulse_too_short_to_hold_beats_reports_no_pulse_figures():
    """Rate and variability come from the same beats, so they arrive and go together."""
    brief = {"PPG_FINGER": _sine(1.2, 1.0, seconds=0.5)}
    extracted = features.extract(
        brief, rate=RATE, report=_report(brief, duration=0.5)
    )
    assert not any(name.startswith("PPG_FINGER__") for name in extracted.values)


def test_pulse_variability_follows_the_spacing_of_the_beats():
    steady = {"PPG_FINGER": _sine(1.2, 1.0, seconds=60.0)}
    varying = simulate.generate(channels=["PPG_FINGER"], seconds=60, seed=6)
    flat = features.extract(steady, rate=RATE, report=_report(steady, duration=60.0))
    jittered = features.extract(varying, rate=RATE, report=_report(varying, duration=60.0))

    # A metronome has no variability beyond the sample it is quantised to.
    assert flat.values["PPG_FINGER__sdnn_ms"] < 3.0

    sdnn = jittered.values["PPG_FINGER__sdnn_ms"]
    rmssd = jittered.values["PPG_FINGER__rmssd_ms"]
    assert 10.0 < rmssd < sdnn < 100.0, (
        "a resting pulse varies more over a minute than it does beat to beat, and a "
        "simulator that gets that order backwards cannot tell the two features apart"
    )
    assert 0.0 <= jittered.values["PPG_FINGER__pnn50"] <= 1.0


def test_the_variability_figures_say_the_window_is_too_short_to_compare():
    samples = {"PPG_FINGER": simulate.generate(channels=["PPG_FINGER"], seed=6)["PPG_FINGER"]}
    extracted = features.extract(samples, rate=RATE, report=_report(samples, duration=30.0))
    joined = " ".join(extracted.notes).casefold()
    assert "five minutes" in joined


def test_skin_conductance_reports_its_level_and_its_responses():
    seconds = 60.0
    axis = _t(seconds=seconds)
    baseline = 6.0
    onsets = (8.0, 20.0, 34.0, 48.0)
    trace = np.full(len(axis), baseline)
    for onset in onsets:
        after = axis >= onset
        trace[after] += 0.4 * (
            np.exp(-(axis[after] - onset) / 4.0) * (1.0 - np.exp(-(axis[after] - onset) / 0.7))
        )
    samples = {"GSR_PALMAR": trace}
    extracted = features.extract(samples, rate=RATE, report=_report(samples, duration=seconds))

    assert extracted.values["GSR_PALMAR__mean_us"] == pytest.approx(baseline, abs=0.2)
    assert extracted.values["GSR_PALMAR__scr_per_min"] == pytest.approx(
        len(onsets) / (seconds / 60.0), abs=0.5
    )


def test_a_resting_skin_conductance_channel_is_not_called_a_detached_electrode():
    """Its own flatline floor, because it moves in hundredths of a microsiemens.

    The floor the EEG channels are held to would fail this trace, and the channel would be
    dropped from an otherwise good recording for being quiet.
    """
    rng = np.random.default_rng(14)
    quiet = 5.0 + rng.normal(0, 0.01, len(_t()))
    assert np.std(quiet) < schema.DEFAULT_FLATLINE_SD
    assert quality.assess_channel("GSR_PALMAR", quiet, RATE).usable
    assert not quality.assess_channel("EEG_FPZ", quiet - 5.0, RATE).usable


@pytest.mark.parametrize(("per_min", "hz"), [(12, 0.2), (15, 0.25), (18, 0.3), (24, 0.4)])
def test_respiration_rate_is_recovered_accurately(per_min, hz):
    rng = np.random.default_rng(8)
    samples = {
        "EEG_FPZ": rng.normal(0, 10, len(_t())),
        "RESPIRATION_BELT": 1.5 * np.sin(2 * np.pi * hz * _t()) + rng.normal(0, 0.02, len(_t())),
    }
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    assert features.summary(extracted)["respiration_per_min"] == pytest.approx(per_min, abs=1.0)


def test_an_unusable_channel_yields_no_feature_rather_than_a_zero():
    """A feature from a flat trace would be a number with no referent."""
    rng = np.random.default_rng(9)
    samples = {
        "EEG_FPZ": rng.normal(0, 10, len(_t())),
        "EEG_CZ": np.zeros(len(_t())),
    }
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    assert "EEG_CZ" in extracted.skipped
    assert not any(name.startswith("EEG_CZ__") for name in extracted.values)
    assert "EEG_FPZ" in extracted.derived_from


def test_an_unknown_channel_is_skipped_with_a_reason():
    rng = np.random.default_rng(10)
    samples = {"EEG_FPZ": rng.normal(0, 10, len(_t())), "MADE_UP": rng.normal(0, 1, len(_t()))}
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    assert "MADE_UP" in extracted.skipped


def test_the_feature_set_states_what_it_is_not():
    rng = np.random.default_rng(11)
    samples = {"EEG_FPZ": rng.normal(0, 10, len(_t()))}
    extracted = features.extract(samples, rate=RATE, report=_report(samples))
    joined = " ".join(extracted.notes).casefold()
    assert "none of them is a pain measure" in joined


def test_the_summary_reports_nothing_for_absent_modalities():
    rng = np.random.default_rng(12)
    samples = {"EEG_FPZ": rng.normal(0, 10, len(_t()))}
    summary = features.summary(features.extract(samples, rate=RATE, report=_report(samples)))
    assert summary["emg"]["rms_uv"] is None
    assert summary["heart_rate_bpm"] is None
    assert summary["hrv_rmssd_ms"] is None
    assert summary["skin_conductance_us"] is None
    assert summary["respiration_per_min"] is None


# --- simulator ---------------------------------------------------------------------------------


def test_a_clean_simulated_recording_passes_quality():
    channels = [
        "EEG_FPZ",
        "EEG_CZ",
        "EMG_TRAPEZIUS_L",
        "PPG_FINGER",
        "GSR_PALMAR",
        "RESPIRATION_BELT",
    ]
    samples = simulate.generate(channels=channels, seconds=30, seed=3)
    report = quality.assess(samples, rate=RATE, duration=30.0)
    assert report.verdict in (quality.GOOD, quality.ADEQUATE)
    assert sorted(report.usable_channels) == sorted(channels)


def test_the_simulated_eeg_has_a_realistic_spectrum():
    """A flat spectrum would make every band-power feature meaningless in testing."""
    samples = simulate.generate(channels=["EEG_FPZ"], seconds=30, seed=4)
    extracted = features.extract(
        samples, rate=RATE, report=quality.assess(samples, rate=RATE, duration=30.0)
    )
    delta = extracted.values["EEG_FPZ__delta_relative"]
    gamma = extracted.values["EEG_FPZ__gamma_relative"]
    assert delta > gamma, "a 1/f background should put more power in delta than gamma"
    assert extracted.values["EEG_FPZ__alpha_relative"] > 0.05


@pytest.mark.parametrize("fault", [f for f in simulate.FAULTS if f != "none"])
def test_every_simulated_fault_is_caught_by_the_quality_checks(fault):
    samples = simulate.generate(
        channels=["EEG_FPZ", "EEG_CZ"], seconds=20, seed=5, faults={"EEG_CZ": fault}
    )
    report = quality.assess(samples, rate=RATE, duration=20.0)
    channel = report.for_channel("EEG_CZ")
    assert channel.verdict != quality.GOOD, f"{fault} was not detected"


def test_an_unknown_fault_is_refused():
    with pytest.raises(ValueError, match="unknown simulated fault"):
        simulate.generate(channels=["EEG_FPZ"], faults={"EEG_FPZ": "explode"})


def test_the_simulator_is_reproducible():
    first = simulate.generate(channels=["EEG_FPZ"], seconds=5, seed=42)
    second = simulate.generate(channels=["EEG_FPZ"], seconds=5, seed=42)
    assert np.allclose(first["EEG_FPZ"], second["EEG_FPZ"])


def test_different_seeds_give_different_signals():
    first = simulate.generate(channels=["EEG_FPZ"], seconds=5, seed=1)
    second = simulate.generate(channels=["EEG_FPZ"], seconds=5, seed=2)
    assert not np.allclose(first["EEG_FPZ"], second["EEG_FPZ"])
