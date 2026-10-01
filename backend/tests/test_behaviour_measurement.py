"""What the camera and the microphone measure, checked against known answers.

Every test here puts a number into a rendered eye or a synthesised voice and asks the
measurement to give it back. That is the only kind of test worth writing for this module:
"the pupil was measured as 4.6 mm" means nothing on its own, and means a great deal when
the pupil drawn was 4.55 mm across.

The thresholds are loose where the quantity is quantised — an iris 30 pixels wide cannot
resolve a pupil to better than a few percent — and tight where it is not.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.behaviour import eyes, features, quality, schema, video, voice
from backend.tests import synthetic_clip


def eye_window(
    *, iris_radius: int = 18, pupil_radius: float = 7.0, lid_gap: int = 28, skin: int = 165
) -> np.ndarray:
    """A grayscale eye: skin, sclera, iris, pupil, and lids closed to `lid_gap` pixels."""
    import cv2

    width, height = 120, 70
    image = np.full((height, width), skin, np.uint8)
    centre_x, centre_y = width // 2, height // 2
    cv2.ellipse(
        image, (centre_x, centre_y), (int(width * 0.38), int(height * 0.30)), 0, 0, 360, 225, -1
    )
    cv2.circle(image, (centre_x, centre_y), iris_radius, 62, -1)
    if pupil_radius:
        cv2.circle(image, (centre_x, centre_y), round(pupil_radius), 18, -1)
    half = lid_gap // 2
    image[: centre_y - half, :] = 160
    image[centre_y + half :, :] = 158
    return cv2.GaussianBlur(image, (3, 3), 0)


# --- one eye ---------------------------------------------------------------------------


def test_the_iris_width_is_recovered_within_a_pixel():
    reading = eyes.measure(eye_window(iris_radius=18))
    assert reading.found and reading.open
    assert reading.iris_radius_px == pytest.approx(18, abs=1.0)


@pytest.mark.parametrize("lid_gap", [34, 28, 20, 14])
def test_the_aperture_follows_the_lid_gap(lid_gap):
    """Aperture is the visible iris height over its width, so the lid gap over the iris
    diameter is the answer it should give."""
    reading = eyes.measure(eye_window(iris_radius=18, lid_gap=lid_gap))
    expected = min(lid_gap / 36, eyes.APERTURE_CEILING)
    assert reading.aperture_ratio == pytest.approx(expected, abs=0.08)


@pytest.mark.parametrize("pupil_radius", [4.0, 7.0, 11.0])
def test_the_pupil_is_measured_and_not_assumed(pupil_radius):
    """The test that matters most in this file.

    A threshold taken as a fixed share of the iris returns that share back as the answer
    whatever the pupil is doing, which looks entirely plausible and measures nothing. Three
    pupils of different sizes in an iris of one size have to come back different.
    """
    reading = eyes.measure(eye_window(iris_radius=18, pupil_radius=pupil_radius))
    assert reading.pupil_iris_ratio == pytest.approx(pupil_radius / 18, abs=0.07)
    expected_mm = 2 * pupil_radius * schema.IRIS_DIAMETER_MM / 36
    assert reading.pupil_diameter_mm == pytest.approx(expected_mm, abs=0.8)


def test_a_narrowed_eye_does_not_inflate_the_pupil():
    """With the lids across the iris, a threshold found over the whole disc separates lid
    from iris and hands back the visible iris as the pupil — growing the reading at exactly
    the moment the patient squints."""
    wide = eyes.measure(eye_window(lid_gap=28, pupil_radius=7))
    narrow = eyes.measure(eye_window(lid_gap=14, pupil_radius=7))
    assert narrow.aperture_ratio < wide.aperture_ratio / 1.5
    assert narrow.pupil_iris_ratio == pytest.approx(wide.pupil_iris_ratio, abs=0.08)


def test_closed_lids_are_reported_as_closed_rather_than_as_a_narrow_eye():
    reading = eyes.measure(eye_window(lid_gap=6))
    assert not reading.open
    assert reading.pupil_diameter_mm == 0.0


def test_a_window_with_no_eye_in_it_finds_nothing():
    assert eyes.measure(np.full((70, 120), 162, np.uint8)) == eyes.CLOSED


def test_a_distant_eye_yields_an_aperture_but_no_millimetres():
    """At nine pixels of iris radius one pixel of error in the pupil is a tenth of the
    reading, so the millimetre figure is withheld while the aperture, a ratio of two long
    extents, survives."""
    reading = eyes.measure(eye_window(iris_radius=9, pupil_radius=3.5, lid_gap=14))
    assert reading.open
    assert reading.aperture_ratio > 0
    assert reading.pupil_diameter_mm == 0.0


def test_the_calibrated_width_rejects_an_eyebrow():
    """A brow is two or three times as wide as the iris above which it sits, and that is
    what separates them once the lids are shut and there is no iris left to find.

    The blob here is deliberately sized to clear the fallback guard — it spans just over
    half the window, where the guard refuses three fifths — so that what rejects it is the
    calibrated width and nothing else.
    """
    brow = eye_window(iris_radius=32, pupil_radius=0, lid_gap=28)
    assert eyes.measure(brow).found is True
    assert eyes.measure(brow, 18.0).found is False


# --- one voice -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wav(tmp_path_factory):
    directory = tmp_path_factory.mktemp("voice")

    def write(**kwargs):
        from scipy.io import wavfile

        signal = synthetic_clip.voice(seconds=3.0, **kwargs)
        path = directory / f"v{abs(hash(tuple(sorted(kwargs.items())))):x}.wav"
        wavfile.write(path, synthetic_clip.SAMPLE_RATE, (signal * 32767).astype(np.int16))
        return path

    return write


@pytest.mark.parametrize("pitch", [90.0, 150.0, 220.0])
def test_the_pitch_is_recovered(wav, pitch):
    reading = voice.read(wav(pitch=pitch))
    assert float(np.nanmedian(reading.pitch)) == pytest.approx(pitch, rel=0.02)


def test_the_octave_is_not_halved(wav):
    """With the correlation normalised over the overlap, a perfectly periodic signal scores
    the same at one period as at two, and the pitch comes back halved for an arbitrary
    scattering of frames unless the shorter near-tie is preferred."""
    reading = voice.read(wav(pitch=150.0))
    voiced = reading.pitch[reading.voiced]
    assert len(voiced) > 100
    # Not one frame in the recording should have landed an octave down.
    assert (voiced < 110).mean() < 0.02


@pytest.mark.parametrize("jitter", [0.0, 0.02, 0.05])
def test_jitter_is_measured_between_glottal_periods(wav, jitter):
    reading = voice.read(wav(pitch=150.0, jitter=jitter))
    measured = (
        100 * np.mean(np.abs(np.diff(reading.periods))) / np.mean(reading.periods)
        if len(reading.periods) > 2
        else 0.0
    )
    # The mean absolute difference between consecutive normal draws is 2/sqrt(pi) sigma.
    expected = 100 * jitter * 2 / np.sqrt(np.pi)
    assert measured == pytest.approx(expected, abs=0.6)


@pytest.mark.parametrize("shimmer", [0.0, 0.10, 0.25])
def test_shimmer_is_measured_between_glottal_periods(wav, shimmer):
    reading = voice.read(wav(pitch=150.0, shimmer=shimmer))
    amplitudes = reading.period_amplitudes
    measured = (
        100 * np.mean(np.abs(np.diff(amplitudes))) / np.mean(amplitudes)
        if len(amplitudes) > 2
        else 0.0
    )
    expected = 100 * shimmer * 2 / np.sqrt(np.pi)
    assert measured == pytest.approx(expected, abs=2.0)


def test_harmonics_to_noise_falls_as_noise_rises(wav):
    def hnr(noise: float) -> float:
        reading = voice.read(wav(pitch=150.0, noise=noise))
        peak = float(np.clip(reading.periodicity[reading.voiced].mean(), 1e-6, 1 - 1e-6))
        return 10 * np.log10(peak / (1 - peak))

    clean, breathy, worst = hnr(0.0), hnr(0.05), hnr(0.3)
    assert clean > 25
    assert clean > breathy > worst
    assert worst < 5


def test_noise_and_silence_carry_no_pitch(wav, tmp_path):
    from scipy.io import wavfile

    for name, signal in (
        ("noise", np.random.default_rng(3).normal(0, 0.3, synthetic_clip.SAMPLE_RATE * 3)),
        ("silence", np.zeros(synthetic_clip.SAMPLE_RATE * 3)),
    ):
        path = tmp_path / f"{name}.wav"
        wavfile.write(path, synthetic_clip.SAMPLE_RATE, (signal * 32767).astype(np.int16))
        reading = voice.read(path)
        assert not reading.voiced.any(), name


def test_a_file_with_no_audio_is_refused(tmp_path):
    path = tmp_path / "nothing.wav"
    path.write_bytes(b"not audio")
    with pytest.raises(voice.AudioUnreadable):
        voice.read(path)


# --- a whole clip ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def resting(tmp_path_factory):
    path = synthetic_clip.clip(
        tmp_path_factory.mktemp("clips") / "resting.webm",
        aperture=1.0, pupil=0.34, brow_drop=0.0, blinks_per_min=15, pitch=140, jitter=0.004,
    )
    return _measure(path)


@pytest.fixture(scope="module")
def strained(tmp_path_factory):
    path = synthetic_clip.clip(
        tmp_path_factory.mktemp("clips") / "strained.webm",
        aperture=0.42, pupil=0.60, brow_drop=0.9, blinks_per_min=34, pitch=196, jitter=0.028,
    )
    return _measure(path)


def _measure(path, baseline: features.Baseline | None = None):
    seen = video.read(path)
    heard = voice.read(path)
    report = quality.assess(seen, heard)
    return seen, heard, report, features.extract(
        video=seen, voice=heard, report=report, baseline=baseline
    )


def test_a_clean_clip_passes_every_modality(resting):
    _, _, report, _ = resting
    assert report.verdict in (quality.GOOD, quality.ADEQUATE)
    assert set(report.usable) == {schema.EYE, schema.FACE, schema.VOICE}


def test_the_blink_rate_is_recovered(resting):
    _, _, _, measured = resting
    assert measured.values["blink_rate_per_min"] == pytest.approx(15.0, abs=3.0)


def test_a_squint_reads_as_a_narrower_aperture(resting, strained):
    _, _, _, calm = resting
    _, _, _, tight = strained
    assert calm.values["eye_aperture_ratio"] > 0.85
    assert tight.values["eye_aperture_ratio"] == pytest.approx(0.42, abs=0.12)


def test_orbital_tightening_needs_a_resting_observation(tmp_path_factory, resting, strained):
    """Without one it can only compare the window against its own widest moment, and a
    patient who squinted throughout has no widest moment."""
    _, _, _, calm = resting
    baseline = features.Baseline(
        eye_aperture_ratio=calm.values["eye_aperture_ratio"],
        pupil_diameter_mm=calm.values["pupil_diameter_mm"],
        blink_rate_per_min=calm.values["blink_rate_per_min"],
        brow_gap_ratio=calm.values["brow_gap_ratio"],
        f0_mean_hz=calm.values["f0_mean_hz"],
    )
    path = synthetic_clip.clip(
        tmp_path_factory.mktemp("against") / "strained.webm",
        aperture=0.42, pupil=0.60, brow_drop=0.9, blinks_per_min=34, pitch=196, jitter=0.028,
    )
    _, _, _, against = _measure(path, baseline)

    assert against.reference["eye_squint_index"] == features.CALIBRATION
    assert against.values["eye_squint_index"] > 0.4
    assert against.values["brow_lower_index"] > 0.05
    assert against.deltas["pupil_diameter_mm"] > 0.1
    assert against.deltas["f0_mean_hz"] > 0.2
    # Without the baseline the same clip can only see within-window variation.
    _, _, _, alone = strained
    assert alone.reference["eye_squint_index"] == features.WITHIN_WINDOW
    assert alone.values["eye_squint_index"] < against.values["eye_squint_index"]


def test_the_voice_measures_follow_the_voice(resting, strained):
    _, _, _, calm = resting
    _, _, _, tight = strained
    assert tight.values["f0_mean_hz"] > calm.values["f0_mean_hz"] * 1.2
    assert tight.values["jitter_percent"] > calm.values["jitter_percent"] * 2
    assert tight.values["hnr_db"] < calm.values["hnr_db"]


def test_eyes_that_are_never_open_produce_no_eye_measure(tmp_path):
    """The gate. A sleeping or sedated patient has no aperture and no pupil, and the honest
    answer is an absence with a reason rather than an average over four frames."""
    path = synthetic_clip.clip(
        tmp_path / "asleep.webm", aperture=0.0, blinks_per_min=0, seconds=10
    )
    _, _, report, measured = _measure(path)

    assert not report.allows(schema.EYE)
    for code in ("eye_aperture_ratio", "pupil_diameter_mm", "blink_rate_per_min"):
        assert code not in measured.values
        assert code in measured.absent
    # The brow and the mouth are visible with the eyes shut, and are still measured.
    assert "brow_gap_ratio" in measured.values
    # As is the voice.
    assert report.allows(schema.VOICE)


def test_a_clip_with_no_sound_still_yields_the_eyes(tmp_path):
    """A camera-only capture. The microphone was muted or the patient said nothing, and
    the eyes are measured anyway."""
    path = synthetic_clip.clip(
        tmp_path / "seen.webm", aperture=0.6, blinks_per_min=20, seconds=10, silent=True
    )
    seen = video.read(path)
    with pytest.raises(voice.AudioUnreadable):
        voice.read(path)

    report = quality.assess(seen, None)
    measured = features.extract(video=seen, voice=None, report=report)
    assert report.allows(schema.EYE)
    assert measured.values["eye_aperture_ratio"] == pytest.approx(0.6, abs=0.15)
    assert measured.absent["f0_mean_hz"] == "the clip holds no audio track"


def test_a_clip_with_no_picture_still_yields_a_voice(tmp_path):
    path = synthetic_clip.audio_only(tmp_path / "heard.webm", seconds=10, pitch=150)
    heard = voice.read(path)
    report = quality.assess(None, heard)
    measured = features.extract(video=None, voice=heard, report=report)

    assert report.allows(schema.VOICE)
    assert measured.values["f0_mean_hz"] == pytest.approx(150, rel=0.05)
    assert measured.absent["eye_aperture_ratio"] == "the clip holds no video track"


def test_a_measure_outside_what_a_face_does_is_dropped_not_clamped():
    out = features.FeatureSet()
    features._record(out, "pupil_diameter_mm", 42.0)
    assert "pupil_diameter_mm" not in out.values
    assert "outside" in out.absent["pupil_diameter_mm"]


def test_a_closure_shorter_than_a_blink_is_a_dropped_detection():
    frames = [
        video.FrameReading(index=i, time_s=i * 0.1, face=(0, 0, 100, 100)) for i in range(20)
    ]
    reading = video.VideoReading(frame_rate=10, duration_seconds=2.0, width=640, height=480)
    reading.frames = frames
    # Every frame has the default closed eyes, so this is one long closure, not twenty
    # blinks.
    found = features.closures(reading)
    assert len(found) == 1
    assert found[0].is_squeeze
    assert not found[0].is_blink
