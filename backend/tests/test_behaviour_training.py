"""That the models are trained on what they claim to be trained on.

Two models touch this channel and they are very different animals. The clinical estimator
learns the behavioural measures alongside the examination, from synthetic cases — so what
is worth testing is that the measures reach its feature vector, that they move with the
generated pain, and that the confounders keep them from moving with it too neatly. The
voice model learns from a real corpus of human recordings, so what is worth testing is
that it beats predicting the mean on speakers it never heard.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.ai import features
from backend.behaviour import inference
from backend.behaviour import schema as behaviour_schema
from backend.behaviour import training as voice_training
from dataset.synthetic import generate

PATIENTS = 150
VISITS = 900

BEHAVIOUR_FEATURES = (
    "eye_squint_index",
    "eye_aperture_ratio",
    "blink_rate_per_min",
    "long_closure_share",
    "pupil_diameter_mm",
    "brow_lower_index",
    "facial_action_index",
    "voice_jitter_percent",
    "voice_hnr_db",
    "voice_vocalisation_share",
    "delta_pupil_rel",
    "delta_voice_f0_rel",
)


@pytest.fixture(scope="module")
def cohort():
    engine = generate.Generator(seed=11, patients=PATIENTS, assessments=VISITS)
    return [record for patient in engine.patients() for record in engine.visits(patient)]


@pytest.fixture(scope="module")
def observed(cohort):
    return [record for record in cohort if record.context.behaviour]


def test_the_feature_schema_carries_the_behavioural_measures():
    assert features.FEATURE_SCHEMA_VERSION == "4"
    for name in BEHAVIOUR_FEATURES:
        assert name in features.NAMES, name
        assert features.LABELS[name]


def test_some_visits_carry_an_observation_and_some_do_not(cohort, observed):
    """A camera is not pointed at every patient at every visit, and a model that has only
    ever seen complete observations will lean on them."""
    share = len(observed) / len(cohort)
    assert 0.3 < share < 0.8, share


def test_a_clip_can_contribute_one_modality_without_the_other(observed):
    seen = {tuple(sorted(record.context.behaviour_modalities)) for record in observed}
    assert (behaviour_schema.EYE, behaviour_schema.FACE, behaviour_schema.VOICE) in seen
    # And at least one of the partial combinations: eyes shut, or nothing said.
    assert any(len(entry) < 3 for entry in seen)


def test_an_unrecorded_measure_reaches_the_model_as_missing_not_as_zero(cohort):
    """A zero would be read as a very small opening and a very low voice.

    Checked against the observation itself rather than against the value: the column is
    missing exactly where no clip contributed that measure, and present exactly where one
    did. Nothing is filled in between.
    """
    matrix = features.matrix([record.context for record in cohort])
    for feature_name, measure in (
        ("eye_squint_index", "eye_squint_index"),
        ("voice_jitter_percent", "jitter_percent"),
    ):
        column = matrix[:, features.NAMES.index(feature_name)]
        recorded = np.array(
            [measure in record.context.behaviour for record in cohort], dtype=bool
        )
        assert recorded.any() and not recorded.all(), feature_name
        assert np.array_equal(np.isnan(column), ~recorded), feature_name


def test_the_behavioural_measures_move_with_the_pain(observed):
    """Positively, and not too strongly.

    Both bounds matter. Below the floor the generator is producing noise and the model
    would learn nothing from the channel. Above the ceiling it is producing a dataset in
    which a face predicts pain better than it does in any published cohort, and a model
    fitted on that would carry the overclaim into the clinic.
    """
    scores = np.array([record.nrs for record in observed])
    for name, floor, ceiling in (
        ("eye_squint_index", 0.35, 0.85),
        ("facial_action_index", 0.35, 0.85),
        ("jitter_percent", 0.35, 0.85),
        ("pupil_diameter_mm", 0.15, 0.75),
    ):
        present = np.array([name in record.context.behaviour for record in observed])
        values = np.array(
            [record.context.behaviour[name] for record in observed if name in record.context.behaviour]
        )
        correlation = float(np.corrcoef(scores[present], values)[0, 1])
        assert floor <= correlation <= ceiling, f"{name} r={correlation:.3f}"


def test_harmonics_to_noise_moves_the_other_way(observed):
    scores = np.array([record.nrs for record in observed])
    present = np.array(["hnr_db" in record.context.behaviour for record in observed])
    values = np.array(
        [record.context.behaviour["hnr_db"] for record in observed if "hnr_db" in record.context.behaviour]
    )
    assert float(np.corrcoef(scores[present], values)[0, 1]) < -0.3


def test_sedation_suppresses_the_grimace_it_should_be_showing(observed):
    """The false negative the brief asks about, and the reason a behavioural channel cannot
    be trusted on its own. A sedated patient in pain shows less of it, so the generated
    cases have to show less of it too — otherwise the model learns that a calm face means
    no pain and is most wrong about the patient least able to say so."""
    high = [record for record in observed if record.nrs >= 6]
    sedated = [
        record.context.behaviour["eye_squint_index"]
        for record in high
        if "SEDATION" in record.context.confounders
        and "eye_squint_index" in record.context.behaviour
    ]
    awake = [
        record.context.behaviour["eye_squint_index"]
        for record in high
        if "SEDATION" not in record.context.confounders
        and "eye_squint_index" in record.context.behaviour
    ]
    assert len(sedated) >= 3, "no sedated case with high pain was generated"
    assert float(np.mean(sedated)) < float(np.mean(awake))


def test_a_wide_pupil_is_not_only_pain(observed):
    """The false positive. Anxiety and fear widen a pupil with no pain behind them, so
    among the low-pain cases the anxious ones have to have the wider pupils."""
    low = [
        record
        for record in observed
        if record.nrs <= 3 and "pupil_diameter_mm" in record.context.behaviour
    ]
    anxious = [
        record.context.behaviour["pupil_diameter_mm"]
        for record in low
        if record.context.confounders & {"ANXIETY", "FEAR", "STRESS"}
    ]
    settled = [
        record.context.behaviour["pupil_diameter_mm"]
        for record in low
        if not record.context.confounders & {"ANXIETY", "FEAR", "STRESS"}
    ]
    assert len(anxious) >= 3, "no anxious case with low pain was generated"
    assert float(np.mean(anxious)) > float(np.mean(settled))


def test_the_same_pain_shows_differently_in_different_people(cohort):
    """Expressiveness varies several-fold between patients at the same reported intensity,
    and it is the reason a behavioural measure has to be read against the same patient at
    rest rather than against a population average."""
    engine = generate.Generator(seed=11, patients=PATIENTS, assessments=VISITS)
    gains = [patient.facial_expressiveness for patient in engine.patients()]
    assert float(np.std(gains)) > 0.2
    assert min(gains) < 0.7 < max(gains)


def test_a_resting_observation_is_not_always_there(observed):
    with_baseline = [record for record in observed if record.context.behaviour_baseline]
    assert 0 < len(with_baseline) < len(observed)
    # And where there is one, the change from it is computable.
    record = next(
        record
        for record in with_baseline
        if "pupil_diameter_mm" in record.context.behaviour
    )
    assert record.context.behaviour_change("pupil_diameter_mm") is not None


# --- the voice model, on real recordings -----------------------------------------------


def _corpus():
    try:
        return voice_training.load()
    except voice_training.NoCorpus as exc:
        pytest.skip(str(exc))


def test_the_voice_corpus_loads_under_the_names_the_extractor_uses():
    frame = _corpus()
    assert list(voice_training.FEATURES) == [
        f"mfcc_{index}_mean" for index in range(1, behaviour_schema.MFCC_COUNT + 1)
    ]
    for name in voice_training.FEATURES:
        assert name in frame.columns
    assert frame[voice_training.TARGET].between(1, len(inference.LEVELS)).all()
    assert frame[voice_training.SUBJECT].nunique() > 50


def test_the_voice_model_beats_predicting_the_mean_on_unheard_speakers():
    frame = _corpus()
    scored = voice_training.evaluate(frame, seed=0, folds=5)
    best = min(scored, key=lambda result: result.mae)

    assert best.n_speakers > 50
    assert best.mae < best.baseline_mae, (
        f"{best.candidate} scored {best.mae} against {best.baseline_mae} for predicting "
        "the mean, so the corpus carries no signal this feature set can reach"
    )
    assert best.within_one_level > 0.8
    # Every level has to be predicted somewhat, not only the extremes.
    assert max(best.by_level.values()) < 2.0


def test_the_voice_model_predicts_a_level_and_never_a_score_out_of_ten():
    assert inference.LEVELS == ("no pain", "low", "middle", "high")
    assert inference.label_for(1.2) == "no pain"
    assert inference.label_for(3.9) == "high"
    assert any("not a 0-10 score" in line for line in inference.LIMITATIONS)
    unavailable = inference.unavailable("no model")
    assert unavailable.level is None
    assert unavailable.available is False
