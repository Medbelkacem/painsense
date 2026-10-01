import numpy as np
import pandas as pd
import pytest

from dataset.pipeline import checks, schema
from dataset.pipeline.schema import CARRIED, TARGET, Encoder
from dataset.pipeline.sources import SOURCES


def _repeated_measures(patients: int = 150, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(patients):
        baseline = rng.uniform(0, 10)
        for visit in range(int(rng.integers(2, 8))):
            rows.append({
                "patient_id": f"P{index:04d}",
                "assessment_id": f"P{index:04d}-{visit}",
                TARGET: float(np.clip(baseline + rng.normal(0, 0.5), 0, 10)),
                "heart_rate": float(rng.normal(80, 10)),
            })
    return pd.DataFrame(rows)


def test_no_patient_lands_in_two_splits():
    frame = _repeated_measures()
    frame["split"], _ = schema.assign(frame)
    assert not checks.check_patient_split_overlap(frame)
    assert frame.groupby("patient_id")["split"].nunique().max() == 1


def test_every_patient_is_assigned_exactly_once():
    frame = _repeated_measures()
    splits, description = schema.assign(frame)
    assert description["unit_of_assignment"] == "patient"
    assert description["patients_assigned"] == frame["patient_id"].nunique()
    assert splits.notna().all()


def test_the_same_seed_reproduces_the_same_split():
    frame = _repeated_measures()
    first, _ = schema.assign(frame, seed=42)
    second, _ = schema.assign(frame, seed=42)
    assert first.equals(second)


def test_a_different_seed_gives_a_different_split():
    frame = _repeated_measures()
    first, _ = schema.assign(frame, seed=42)
    second, _ = schema.assign(frame, seed=7)
    assert not first.equals(second)


def test_record_level_splitting_is_detected_as_a_leak():
    frame = _repeated_measures()
    rng = np.random.default_rng(3)
    frame["split"] = rng.choice(["train", "validation", "test"], len(frame))
    findings = checks.check_patient_split_overlap(frame)
    assert checks.has_blocking(findings)
    assert findings[0]["patients_affected"] > 0


def test_stratification_keeps_the_label_distribution_comparable():
    frame = _repeated_measures(patients=400, seed=5)
    frame["split"], _ = schema.assign(frame)
    means = [frame.loc[frame["split"] == name, TARGET].mean() for name in schema.SPLIT_NAMES]
    assert max(means) - min(means) < 0.75


def test_records_without_a_patient_identifier_are_not_assigned():
    frame = _repeated_measures(patients=30)
    frame.loc[0:4, "patient_id"] = None
    splits, description = schema.assign(frame)
    assert description["records_unassigned"] == 5
    assert splits.isna().sum() == 5


def test_encoder_statistics_come_from_the_training_split_only():
    frame = _repeated_measures(patients=120, seed=11)
    frame["split"], _ = schema.assign(frame)
    encoder = Encoder().fit(frame[frame["split"] == "train"])
    baseline = dict(encoder.means)

    moved = frame.copy()
    held_out = moved["split"] != "train"
    moved.loc[held_out, "heart_rate"] = moved.loc[held_out, "heart_rate"] + 500
    refitted = Encoder().fit(moved[moved["split"] == "train"])
    assert refitted.means == baseline


def test_the_built_split_has_no_patient_overlap(model_ready):
    assert model_ready.groupby("patient_id")["split"].nunique().max() == 1
    assert not checks.check_patient_split_overlap(model_ready)


def test_every_label_field_is_excluded_from_candidate_features():
    numeric, categorical, multi = schema.candidate_features()
    candidates = set(numeric) | set(categorical) | set(multi)
    labels = {name for name, (_, group) in schema.FIELDS.items() if group == "label"}
    assert labels, "the schema must mark its label fields"
    assert not candidates & labels, f"label fields offered as features: {candidates & labels}"


def test_pain_present_is_a_label_not_an_observation():
    assert schema.FIELDS["pain_present"][1] == "label"


def test_the_target_itself_is_rejected_by_name():
    findings = checks.check_feature_names([TARGET])
    assert findings and checks.has_blocking(findings)


@pytest.mark.parametrize(
    "name",
    ["self_reported_nrs", "pain_score", "nrs_value", "pain_intensity", "vas", "target",
     "predicted_pain", "ai_pain_score", "followup_pain", "pain_category"],
)
def test_names_that_restate_the_target_are_rejected(name):
    assert checks.has_blocking(checks.check_feature_names([name]))


def test_a_renamed_derived_target_is_caught_by_correlation():
    rng = np.random.default_rng(0)
    target = rng.integers(0, 11, 400).astype(float)
    frame = pd.DataFrame({
        TARGET: target,
        "clinical_observation_index": target * 1.7 - 2.0,
        "heart_rate": rng.normal(80, 12, 400),
    })
    assert not checks.check_feature_names(["clinical_observation_index"])
    findings = checks.check_target_correlation(
        frame, ["clinical_observation_index", "heart_rate"]
    )
    assert {item["column"] for item in findings} == {"clinical_observation_index"}
    assert checks.has_blocking(findings)


def test_an_unrelated_feature_is_not_flagged():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({
        TARGET: rng.integers(0, 11, 400).astype(float),
        "heart_rate": rng.normal(80, 12, 400),
    })
    assert not checks.check_target_correlation(frame, ["heart_rate"])


def test_a_source_without_a_documented_nrs_scale_cannot_populate_the_target():
    for source in SOURCES.values():
        if source.nrs_mapping == "direct":
            continue
        assert source.nrs_mapping_reason, f"{source.dataset_id} must say why it has no mapping"
        if not source.root.exists():
            continue
        for chunk in source.chunks():
            conformed = schema.conform(chunk, dataset_id=source.dataset_id)
            assert conformed[TARGET].isna().all(), source.dataset_id
            assert conformed["original_pain_score"].notna().any(), source.dataset_id
            break


def test_the_built_feature_matrix_leaks_nothing(model_ready):
    reserved = {*CARRIED, TARGET}
    features = [column for column in model_ready.columns if column not in reserved]
    assert features, "the model-ready matrix must carry features"
    findings = checks.audit_features(model_ready, features)
    assert not findings, [item["detail"] for item in findings]


def test_the_encoder_never_emits_a_label_column():
    frame = pd.DataFrame({
        "patient_id": ["p1", "p2", "p3"],
        "assessment_id": ["a1", "a2", "a3"],
        "dataset_id": ["d"] * 3,
        "data_source": ["s"] * 3,
        "synthetic": [True] * 3,
        "split": ["train"] * 3,
        TARGET: [1.0, 5.0, 9.0],
        "original_pain_score": [1.0, 5.0, 9.0],
        "pain_present": [True, True, True],
        "heart_rate": [70.0, 85.0, 100.0],
    })
    encoder = Encoder().fit(frame)
    encoded = encoder.transform(frame)
    features = encoder.feature_columns(encoded)
    assert "original_pain_score" not in features
    assert "pain_present" not in features
    assert not checks.audit_features(encoded, features)
