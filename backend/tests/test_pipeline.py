import dataclasses
import inspect
import math
from dataclasses import replace

from backend.ai import confounders, estimator, features, inputs, model, quality, uncertainty
from database.models import DataQuality
from knowledge.context import ClinicalContext


def complete_case(**overrides) -> ClinicalContext:
    values = {
        "age": 58,
        "sex": "M",
        "pain_locations": frozenset({"CHEST_CENTRAL"}),
        "qualities": frozenset({"PRESSURE", "TIGHTNESS"}),
        "symptoms": frozenset({"SWEATING", "DYSPNOEA"}),
        "conditions": frozenset({"CAD"}),
        "factors": frozenset({"EXERCISE", "REST"}),
        "onset": "SUDDEN",
        "pattern": "INTERMITTENT",
        "course": "WORSENING",
        "duration_hours": 4.0,
        "radiates": True,
        "functional_impact": {
            "mobility": 3,
            "sleep": 3,
            "work": 4,
            "daily_activity": 3,
            "self_care": 2,
        },
        "medications": (),
        "vitals": {"hr": 96.0, "resp_rate": 18.0, "sbp": 148.0, "dbp": 88.0, "spo2": 97.0},
        "answers": {
            "FIRST_EPISODE": True,
            "REGULAR_MEDICATION": False,
            "CHEST_WALL_TENDER": False,
            "CHEST_EXERTIONAL": True,
        },
    }
    values.update(overrides)
    return ClinicalContext(**values)


def test_a_model_fitted_on_another_feature_set_is_refused(db, monkeypatch):
    bundle, row = model.active(db)
    stale = replace(bundle, feature_names=bundle.feature_names[:-1])
    monkeypatch.setattr(model, "active", lambda _db: (stale, row))

    result = estimator.estimate(db, complete_case())
    assert result.refused
    assert "different set of features" in result.refusal_reason

    assert result.priority.score is not None


def test_no_feature_reads_a_self_reported_score():
    # The argument is structural rather than textual. Features are a function of a
    # ClinicalContext and nothing else; a ClinicalContext has no field that could hold a
    # score; and inputs is the only bridge from a stored assessment to a context, so if it
    # never touches the reference, nothing downstream can.
    held = {field.name for field in dataclasses.fields(ClinicalContext)}
    assert not [name for name in held if "nrs" in name or "score" in name]

    extractors = inspect.signature(features.vector).parameters
    assert [p.annotation for p in extractors.values()] == [ClinicalContext]

    bridge = inspect.getsource(inputs)
    assert "self_report" not in bridge
    assert "nrs" not in bridge


def test_a_missing_measurement_stays_missing():
    vector = features.vector(complete_case(vitals={"hr": 96.0}))
    index = features.NAMES.index("spo2")
    assert math.isnan(vector[index])


def test_the_vector_matches_the_feature_list():
    assert len(features.vector(complete_case())) == len(features.NAMES)


def test_a_complete_record_is_good_quality():
    report = quality.assess(complete_case())
    assert report.level is DataQuality.GOOD
    assert report.sufficient


def test_a_thin_record_blocks_the_estimate():
    report = quality.assess(ClinicalContext(pain_locations=frozenset({"KNEE"})))
    assert report.level is DataQuality.INSUFFICIENT
    assert not report.sufficient
    assert report.blocking


def test_an_impossible_measurement_blocks_the_estimate():
    report = quality.assess(complete_case(vitals={"hr": 420.0, "spo2": 98.0}))
    assert not report.sufficient
    assert any("plausible range" in reason for reason in report.blocking)


def test_contradictions_are_reported_not_resolved():
    ctx = complete_case(pattern="CONSTANT", episodes_per_day=4)
    report = quality.assess(ctx)
    assert any("constant" in issue for issue in report.issues)
    assert ctx.episodes_per_day == 4


def test_missing_fields_are_named():
    report = quality.assess(complete_case(symptoms=frozenset()))
    assert any("symptom" in field.lower() for field in report.missing)


def test_crossed_quantiles_are_sorted_rather_than_reported_as_given():
    interval = uncertainty.build(7.0, 8.5, 6.0)
    assert interval.low <= interval.point <= interval.high


def test_the_interval_stays_inside_the_scale():
    interval = uncertainty.build(9.9, 9.5, 12.0, widening=0.5)
    assert interval.low >= 0.0
    assert interval.high <= 10.0


def test_coverage_counts_targets_inside_their_interval():
    assert uncertainty.coverage([5, 5, 5], [4, 6, 4], [6, 7, 6]) == round(2 / 3, 3)


def test_context_widens_the_interval_only_when_a_vital_is_contested():
    settled = complete_case(
        confounders=frozenset({"ANXIETY"}),
        vitals={"hr": 78.0, "resp_rate": 16.0, "sbp": 128.0, "dbp": 80.0, "spo2": 98.0},
    )
    assert confounders.analyse(settled).widening == 0.0

    contested = confounders.analyse(
        complete_case(confounders=frozenset({"ANXIETY"}), vitals={"hr": 124.0, "spo2": 97.0}),
        influential_features=["hr"],
    )
    assert contested.widening > 0.0
    assert contested.any_vital_contested


def test_the_estimate_is_withheld_when_the_record_is_too_thin(db):
    result = estimator.estimate(db, ClinicalContext(pain_locations=frozenset({"KNEE"})))
    assert result.refused
    assert result.interval is None
    assert "cannot be responsibly generated" in result.refusal_reason


def test_red_flags_still_run_when_the_estimate_is_withheld(db):
    thin = ClinicalContext(pain_locations=frozenset({"KNEE"}), vitals={"spo2": 85.0})
    result = estimator.estimate(db, thin)
    assert result.refused
    assert any(alert.code == "SPO2_LOW" for alert in result.alerts)


def test_a_complete_record_produces_an_explained_estimate(db):
    result = estimator.estimate(db, complete_case())
    assert not result.refused
    assert 0.0 <= result.interval.point <= 10.0
    assert result.interval.low <= result.interval.point <= result.interval.high
    assert result.band_code in ("NONE", "MILD", "MODERATE", "SEVERE", "EXTREME")
    assert result.contributions
    assert all(item.magnitude in ("HIGH", "MODERATE", "LOW") for item in result.contributions)
    assert result.model_version


def test_the_reported_coverage_is_the_measured_one(db):
    result = estimator.estimate(db, complete_case())
    assert 0.0 < result.interval.observed_coverage <= 1.0
    assert result.interval.nominal_level == uncertainty.NOMINAL_LEVEL
