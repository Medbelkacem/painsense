import math

from backend.ai import drift, features, model
from database.models import ModelVersion

REQUIRED_KEYS = {
    "candidate",
    "algorithm",
    "explainable",
    "selectable",
    "selected",
    "cv",
    "mae",
    "rmse",
    "r2",
    "f1_band",
    "fit_seconds",
    "inference_ms_per_1000",
}


def _active(db) -> ModelVersion:
    return db.query(ModelVersion).filter_by(is_active=True).one()


def test_five_candidates_were_compared_and_a_tree_model_selected(db):
    row = _active(db)
    assert len(row.comparison) == 5
    for entry in row.comparison:
        assert REQUIRED_KEYS <= set(entry), entry
    selected = [entry for entry in row.comparison if entry["selected"]]
    assert len(selected) == 1
    assert selected[0]["candidate"] in ("hgb", "hgb_regularised", "random_forest")
    assert selected[0]["explainable"]
    for entry in row.comparison:
        if entry["candidate"] in ("ridge", "mlp"):
            assert not entry["selectable"]
    best = min(e["mae"] for e in row.comparison if e["selectable"])
    assert selected[0]["mae"] == best


def test_headline_metrics_are_in_range(db):
    row = _active(db)
    assert 0.0 < row.mae < 3.0
    assert row.mae <= row.rmse
    assert -1.0 <= row.r2 <= 1.0
    assert -1.0 <= row.pearson <= 1.0
    assert 0.0 <= row.f1_band <= 1.0
    assert row.inference_ms is not None and row.inference_ms >= 0.0
    assert row.n_train > 0 and row.n_validation > 0 and row.n_test > 0
    assert row.model_name == model.MODEL_NAME
    assert row.feature_schema_version == features.FEATURE_SCHEMA_VERSION


def test_feature_importance_is_sorted_and_complete(db):
    row = _active(db)
    assert row.feature_importance
    values = [entry["importance"] for entry in row.feature_importance]
    assert values == sorted(values, reverse=True)
    assert {entry["feature"] for entry in row.feature_importance} == set(features.NAMES)
    assert all(entry["label"] for entry in row.feature_importance)


def test_the_training_profile_covers_every_feature(db):
    row = _active(db)
    profile = row.training_profile
    assert set(profile["features"]) == set(features.NAMES)
    for summary in profile["features"].values():
        assert {"mean", "sd", "missing_rate", "p05", "p50", "p95"} <= set(summary)
    assert set(profile["prediction"]["histogram"]) == {
        "NONE",
        "MILD",
        "MODERATE",
        "SEVERE",
        "EXTREME",
    }
    assert "scenario" in profile["subgroups"] and "archetype" in profile["subgroups"]
    bundle = model.load(row.version)
    assert bundle.training_profile == profile
    assert bundle.feature_schema_version == features.FEATURE_SCHEMA_VERSION
    assert bundle.model_name == model.MODEL_NAME


def test_drift_is_absent_on_the_training_rows_themselves(db):
    row = _active(db)
    bundle = model.load(row.version)
    profile = bundle.training_profile
    rng_rows = []

    n = 200
    for index in range(n):
        values = {}
        for name, summary in profile["features"].items():
            missing = summary["missing_rate"]
            values[name] = None if (index / n) < missing else summary["mean"]
        rng_rows.append(values)
    predictions = [profile["prediction"]["mean"]] * n
    report = drift.assess(profile, rng_rows, predictions)
    assert report.sufficient
    assert report.level == drift.NONE
    assert not report.warnings
    assert abs(report.prediction_shift_sd) < 1e-6


def test_drift_reports_shifts_and_insufficient_samples():
    profile = {
        "features": {"hr": {"mean": 80.0, "sd": 10.0, "missing_rate": 0.1}},
        "prediction": {"mean": 5.0, "sd": 2.0, "histogram": {"MODERATE": 1.0}},
    }
    short = drift.assess(profile, [{"hr": 80.0}] * 5, [5.0] * 5)
    assert not short.sufficient and short.note == drift.INSUFFICIENT_NOTE

    shifted = drift.assess(profile, [{"hr": 100.0}] * 30, [9.0] * 30)
    assert shifted.features["hr"].shift_sd == 2.0
    assert shifted.level == drift.WARNING
    assert any("hr" in w for w in shifted.warnings)

    sparse = drift.assess(profile, [{"hr": None}] * 20 + [{"hr": 80.0}] * 10, [5.0] * 30)
    assert sparse.features["hr"].missingness_change > 0.2
    assert sparse.level == drift.WATCH
    assert math.isclose(sparse.band_distance, 0.0)
