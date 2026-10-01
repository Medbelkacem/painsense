"""That the signal pain model is trained on what it claims to be trained on.

The corpus these tests run against is written here rather than read from disk. The real one
is the PainMonit database, which comes under an agreement that forbids redistribution, so a
test that needed it would only ever pass on a machine that happened to hold a copy. What
is written instead is the same shape: the same column names, the same semicolon-and-comma
CSV dialect, the same 250 Hz, the same heat protocol, and the same units — so the reader's
unit conversion, its windowing and its refusals are all exercised, and only the physiology
is invented.

The two halves are written differently on purpose. The experimental one carries a skin
conductance response that grows with the stimulus, so a model should find it and the
registration should go active. The clinical one carries ratings unrelated to the signal,
which is what the real clinical half turns out to behave like under patient-grouped
validation, and a model should fail to beat predicting the mean and be registered inactive.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from database.models import ModelVersion
from backend.signals import features as feature_module
from backend.signals import inference, painmonit, quality
from backend.signals import training as signal_training

RATE = painmonit.SAMPLE_RATE_HZ
SUBJECTS = 8
#: Five calibrated steps, twice each, as the real protocol runs them.
STEPS = (44.0, 46.0, 47.0, 48.0, 49.0)
REPEATS = 2
REST_SECONDS = 14.0

CLINICAL_SECONDS = 200.0
CLINICAL_RATINGS = 12


def _pulse(t: np.ndarray, bpm: float) -> np.ndarray:
    """A beat train, so the pulse features have something to find."""
    beats = np.arange(60.0 / bpm, t[-1], 60.0 / bpm)
    wave = np.zeros_like(t)
    for beat in beats:
        wave += np.exp(-(((t - beat) / 0.05) ** 2))
    return wave


def _response(t: np.ndarray, onset: float, height: float) -> np.ndarray:
    """One skin conductance response: a rise over a second, a recovery over several."""
    phase = t - onset
    after = phase >= 0
    out = np.zeros_like(t)
    out[after] = height * np.exp(-phase[after] / 4.0) * (1.0 - np.exp(-phase[after] / 0.7))
    return out


def _experimental_subject(rng: np.random.Generator) -> pd.DataFrame:
    plan = [(step, repeat) for repeat in range(REPEATS) for step in STEPS]
    rng.shuffle(plan)
    cycle = REST_SECONDS + painmonit.STIMULUS_WINDOW_SECONDS
    # A rest before each stimulus and one more after the last, as the real protocol runs:
    # the recording does not stop the instant the heater comes off, and a window over the
    # final stimulus needs the seconds after it.
    seconds = np.arange(0.0, len(plan) * cycle + REST_SECONDS, 1.0 / RATE)
    heater = np.full(len(seconds), painmonit.BASELINE_TEMPERATURE_C)
    covas = np.zeros(len(seconds))

    # Resting conductance differs severalfold between people and barely at all within one,
    # so the level is drawn per subject and wide. A model that leans on it instead of on
    # the response will not survive the grouped folds, which is the point of drawing it.
    conductance = rng.uniform(2.0, 14.0) + 0.3 * np.sin(2 * np.pi * 0.01 * seconds)
    gain = rng.uniform(0.6, 1.4)

    for index, (step, _) in enumerate(plan):
        start = index * cycle + REST_SECONDS
        level = STEPS.index(step) + 1
        window = (seconds >= start) & (seconds < start + painmonit.STIMULUS_WINDOW_SECONDS)
        heater[window] = step
        # The dial cannot be turned past its end, so the top step saturates as it does in
        # the real recordings.
        covas[window] = min(100.0, level * 18.0 * rng.uniform(0.85, 1.15))
        conductance = conductance + _response(seconds, start + 1.5, gain * 0.35 * level)

    return pd.DataFrame(
        {
            "Seconds": seconds,
            "Bvp": _pulse(seconds, rng.uniform(60.0, 85.0)) * 80.0,
            "Eda_E4": conductance * 0.4,
            "Tmp": np.full(len(seconds), 34.8),
            "Ibi": np.full(len(seconds), 0.8),
            "Hr": np.full(len(seconds), 75.0),
            "Resp": np.sin(2 * np.pi * 0.25 * seconds) * 6.0,
            "Eda_RB": conductance,
            "Ecg": rng.normal(0.0, 0.2, len(seconds)),
            "Emg": rng.normal(0.0, 0.01, len(seconds)),
            "Heater [C]": heater,
            "COVAS": covas,
            "Heater_cleaned": heater,
        }
    )


def _clinical_session(rng: np.random.Generator, *, early_rating: bool) -> pd.DataFrame:
    seconds = np.arange(0.0, CLINICAL_SECONDS, 1.0 / RATE)
    conductance = rng.uniform(3.0, 15.0) + 0.4 * np.sin(2 * np.pi * 0.02 * seconds)
    for onset in rng.uniform(5.0, CLINICAL_SECONDS - 5.0, 9):
        conductance = conductance + _response(seconds, onset, rng.uniform(0.2, 0.9))

    rates = np.full(len(seconds), np.nan)
    moments = np.linspace(20.0, CLINICAL_SECONDS - 10.0, CLINICAL_RATINGS)
    if early_rating:
        # Spoken before a full window has been recorded. The reader has to drop it.
        moments = np.r_[5.0, moments]
    for moment in moments:
        rates[int(moment * RATE)] = float(rng.integers(1, 11))

    return pd.DataFrame(
        {
            "Seconds": seconds,
            "Bvp": _pulse(seconds, rng.uniform(60.0, 85.0)) * 80.0,
            "Eda_E4": conductance * 0.4,
            "Tmp": np.full(len(seconds), 34.7),
            "Resp": np.sin(2 * np.pi * 0.23 * seconds) * 6.0,
            "Eda_RB": conductance,
            "Bvp_RB": rng.normal(0.0, 0.02, len(seconds)),
            "Emg": rng.normal(0.0, 0.01, len(seconds)),
            "Grip": np.full(len(seconds), -1.9),
            "Pain rates": rates,
            "Pain labels": np.where(np.isfinite(rates), 1.0, np.nan),
        }
    )


def _write(frame: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep=";", decimal=",", index=False, float_format="%.6f")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """A PainMonit-shaped corpus, both halves, as extracted trees."""
    root = tmp_path_factory.mktemp("painmonit")
    rng = np.random.default_rng(3)

    experimental = root / painmonit.TREES[painmonit.EXPERIMENTAL] / "raw-data"
    for index in range(1, SUBJECTS + 1):
        _write(
            _experimental_subject(rng),
            experimental / f"S_{index:02d}-synchronised-data.csv",
        )

    clinical = root / painmonit.TREES[painmonit.CLINICAL] / "raw-data"
    for index in range(1, SUBJECTS + 1):
        for session in (1, 2):
            key = f"P{index:02d}_{session}"
            _write(
                _clinical_session(rng, early_rating=session == 1),
                clinical / key / f"{key}.csv",
            )
            # The run-up recording beside each session. Nothing reads it, and the point of
            # writing one is that nothing reads it.
            _write(_clinical_session(rng, early_rating=False), clinical / key / f"{key}_runUp.csv")
    return root


@pytest.fixture(scope="module")
def experimental(corpus):
    return painmonit.table(painmonit.read(corpus, painmonit.EXPERIMENTAL))


@pytest.fixture(scope="module")
def clinical(corpus):
    return painmonit.table(painmonit.read(corpus, painmonit.CLINICAL))


def test_every_stimulus_and_every_rest_becomes_one_labelled_window(experimental):
    assert experimental["subject"].nunique() == SUBJECTS
    counts = experimental.groupby(["subject", experimental["level"] > 0]).size().unstack()
    # One window per stimulus, and one over each stretch of rest: the ten before the
    # stimuli and the one after the last.
    assert counts[True].unique().tolist() == [len(STEPS) * REPEATS]
    assert counts[False].unique().tolist() == [len(STEPS) * REPEATS + 1]
    assert sorted(experimental["level"].unique()) == [0, 1, 2, 3, 4, 5]
    assert experimental["target"].between(0.0, 100.0).all()
    # Each step twice per subject, which is what makes the step number comparable.
    stimuli = experimental[experimental["level"] > 0]
    assert stimuli.groupby(["subject", "level"]).size().unique().tolist() == [REPEATS]


def test_the_rating_is_the_label_and_an_early_one_is_dropped(clinical):
    assert clinical["subject"].nunique() == SUBJECTS
    assert clinical["target"].between(1.0, 10.0).all()
    assert clinical["level"].isna().all()
    # Each first session writes one rating before a full window exists; it is not a window.
    assert len(clinical) == SUBJECTS * 2 * CLINICAL_RATINGS


def test_both_sessions_of_a_patient_are_one_group(clinical):
    """Otherwise a patient lands on both sides of a split and the error means nothing."""
    pairs = clinical.groupby("subject")["session"].nunique()
    assert (pairs == 2).all()
    assert clinical["subject"].str.fullmatch(r"P\d+").all()


def test_the_features_are_the_platform_s_own(experimental):
    """Not a parallel extractor. The names and the values have to be the ones a recording
    made on the ward produces, or the model is fed different numbers under the same names."""
    produced = {column for column in experimental.columns if "__" in column}
    expected = set()
    for code in ("GSR_PALMAR", "PPG_FINGER", "RESPIRATION_BELT"):
        samples = {code: np.asarray(_reference_trace(code))}
        report = quality.assess(samples, rate=RATE, duration=20.0)
        expected |= set(feature_module.extract(samples, rate=RATE, report=report).values)
    assert produced == expected


def _reference_trace(code: str) -> np.ndarray:
    t = np.arange(0.0, 20.0, 1.0 / RATE)
    if code == "GSR_PALMAR":
        return 6.0 + _response(t, 4.0, 1.2)
    if code == "PPG_FINGER":
        return _pulse(t, 70.0)
    return np.sin(2 * np.pi * 0.25 * t) * 1.4


def test_no_muscle_or_cardiac_feature_is_read(experimental):
    """The corpus carries EMG and ECG columns and is sampled at 250 Hz, which is under the
    rate this platform's EMG channels declare. Reading them anyway would mean training on a
    band half the width of the one the same code computes at the bedside."""
    assert not [column for column in experimental.columns if column.startswith("EMG")]
    assert not [column for column in experimental.columns if "ecg" in column.lower()]


def test_a_recording_at_the_wrong_rate_is_refused(corpus, tmp_path):
    """The gains and the window lengths all assume the published rate."""
    source = next(
        (corpus / painmonit.TREES[painmonit.EXPERIMENTAL] / "raw-data").glob("*.csv")
    )
    frame = pd.read_csv(source, sep=";", decimal=",")
    frame["Seconds"] = frame["Seconds"] * 2.0
    target = tmp_path / painmonit.TREES[painmonit.EXPERIMENTAL] / "raw-data"
    _write(frame, target / "S_01-synchronised-data.csv")
    with pytest.raises(painmonit.NoCorpus, match="125.0 Hz"):
        painmonit.read(tmp_path, painmonit.EXPERIMENTAL)


def test_an_unknown_half_is_refused(corpus):
    with pytest.raises(painmonit.NoCorpus, match="unknown half"):
        painmonit.read(corpus, "both")


def test_a_corpus_that_is_not_there_says_where_it_looked(tmp_path):
    with pytest.raises(painmonit.NoCorpus, match="PMED.zip"):
        painmonit.read(tmp_path, painmonit.EXPERIMENTAL)


def test_the_feature_set_is_chosen_by_held_out_error(experimental):
    """Every channel combination is scored, and the one that wins is the one fitted. A
    channel that earns nothing is not free: it decides which recordings the model can be
    offered at all."""
    scored = signal_training.evaluate(experimental, seed=0, folds=4)
    assert {result.channels for result in scored} == set(signal_training.CHANNEL_SETS)
    chosen = min(scored, key=lambda result: result.mae)
    assert chosen.beats_mean, (chosen.mae, chosen.baseline_mae)
    assert chosen.n_subjects == SUBJECTS
    # The response is in the skin conductance, so whatever wins has to be reading it.
    assert any(name.startswith("GSR_PALMAR__") for name in chosen.features)
    assert chosen.auc_rest_vs_highest > 0.75


def test_training_registers_the_model_and_leaves_other_families_alone(db, corpus):
    before = {
        row.version
        for row in db.scalars(
            select(ModelVersion).where(
                ModelVersion.model_name != inference.MODEL_NAME,
                ModelVersion.is_active.is_(True),
            )
        )
    }
    assert before, "the session fixture trains and activates a clinical model"

    row, scored = signal_training.train(
        db, dataset=corpus, half=painmonit.EXPERIMENTAL, seed=0, folds=4
    )
    assert row.is_active
    assert row.model_name == inference.MODEL_NAME
    assert row.feature_schema_version == inference.schema.FEATURE_SCHEMA_VERSION
    assert row.features and set(row.features) <= set(experimental_names(scored))
    assert row.comparison == [result.as_dict() for result in scored]
    assert painmonit.CITATION in row.notes

    after = {
        r.version
        for r in db.scalars(
            select(ModelVersion).where(
                ModelVersion.model_name != inference.MODEL_NAME,
                ModelVersion.is_active.is_(True),
            )
        )
    }
    assert after == before, "activating a signal model deactivated another family's"


def experimental_names(scored) -> list[str]:
    return [name for result in scored for name in result.features]


def test_the_estimate_reports_the_corpus_scale_and_withholds_the_band(db, corpus):
    """The model's number is a visual analogue rating out of a hundred. The platform's pain
    bands are defined on a 0-10 scale, and reading 30 out of 100 as severe pain is the
    mistake this guards against."""
    signal_training.train(db, dataset=corpus, half=painmonit.EXPERIMENTAL, seed=0, folds=4)
    bundle = inference.find_model(db)
    assert bundle is not None

    features = {name: 1.0 for name in bundle.features}
    estimate = inference.estimate(db, features, quality_verdict=quality.GOOD)
    assert estimate.available
    assert estimate.scale == painmonit.SCALES[painmonit.EXPERIMENTAL]
    assert estimate.category is None
    assert 0.0 <= estimate.pain_score <= 100.0
    assert any("no mapping" in line.lower() for line in estimate.limitations)


def test_a_missing_feature_is_reported_rather_than_imputed(db, corpus):
    signal_training.train(db, dataset=corpus, half=painmonit.EXPERIMENTAL, seed=0, folds=4)
    row = inference.find_model(db)
    short = {name: 1.0 for name in row.features[1:]}
    estimate = inference.estimate(db, short, quality_verdict=quality.GOOD)
    assert not estimate.available
    assert row.features[0] in " ".join(estimate.limitations)


def test_an_analysed_recording_stores_the_score_with_its_scale(db, client, doctor_headers, corpus):
    """The whole way through, not just out of `inference.estimate`. A score of 62 on a row
    that does not say what it is out of is not a clinical record of anything."""
    from database.models import Patient

    row, _ = signal_training.train(
        db, dataset=corpus, half=painmonit.EXPERIMENTAL, seed=0, folds=4
    )
    patient = Patient(code=f"PMN-{uuid.uuid4().hex[:8]}", is_synthetic=True)
    db.add(patient)
    db.flush()

    # The channels the model actually chose, plus the two primaries a real recording is of.
    # Taken from the model rather than written out here: which channel set wins is decided
    # by held-out error, and a recording that does not carry one of them is refused an
    # estimate by name, which another test here covers.
    channels = ["EEG_FPZ", "EMG_TRAPEZIUS_L"]
    channels += sorted({name.split("__")[0] for name in row.features})
    recording = client.post(
        "/api/signals/recordings",
        headers=doctor_headers,
        json={
            "patient_id": str(patient.id),
            "channels": channels,
            "source": "SIMULATION",
            "simulate_seconds": 20,
            "simulate_seed": 11,
        },
    ).json()
    assert client.post(
        f"/api/signals/recordings/{recording['id']}/stop", headers=doctor_headers
    ).status_code == 200
    analysed = client.post(
        f"/api/signals/recordings/{recording['id']}/analyze", headers=doctor_headers, json={}
    )
    assert analysed.status_code == 200, analysed.text

    analysis = analysed.json()["analyses"][0]
    assert analysis["estimate_available"]
    assert analysis["scale"] == painmonit.SCALES[painmonit.EXPERIMENTAL]
    assert 0.0 <= analysis["pain_score"] <= 100.0
    assert analysis["pain_category"] is None
    assert any("no mapping" in note.lower() for note in analysis["notes"])


def test_a_half_that_carries_no_signal_is_registered_inactive(db, corpus):
    """The clinical ratings here are unrelated to the trace, which is how the real clinical
    half behaves under patient-grouped validation. That is a finding about the corpus, and
    the record of it is worth keeping; what it is not is a model to serve."""
    row, scored = signal_training.train(
        db, dataset=corpus, half=painmonit.CLINICAL, seed=0, folds=4
    )
    chosen = min(scored, key=lambda result: result.mae)
    assert not chosen.beats_mean, chosen.as_dict()
    assert not row.is_active
    assert "does not beat predicting the mean" in row.notes
    assert row.training_profile["scale"] == painmonit.SCALES[painmonit.CLINICAL]
