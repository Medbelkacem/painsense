import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from dataset.pipeline import acquire, checks, registry, schema
from dataset.pipeline.profile import profile_dataset, uniformity


@pytest.fixture
def registry_in(tmp_path, monkeypatch):
    for name in ("REGISTRY_PATH", "LICENCE_PATH", "DOWNLOAD_LOG_PATH", "MANIFEST_PATH"):
        monkeypatch.setattr(registry, name, tmp_path / f"{name.lower()}.json")
    return tmp_path


def test_upsert_revises_an_entry_instead_of_appending_a_second(registry_in):
    first = registry.entry("d", "Name", "Src", "https://example.test", "unknown")
    registry.upsert([first])
    registry.upsert([registry.entry("d", "Name", "Src", "https://example.test", "open")])
    rows = registry.load_registry()
    assert len(rows) == 1
    assert rows[0]["access_status"] == "open"


def test_upsert_does_not_let_an_unknown_erase_a_known_value(registry_in):
    registry.upsert([
        registry.entry("d", "Name", "Src", "https://example.test", "open", subjects=51,
                       license="CC0")
    ])
    registry.upsert([registry.entry("d", "Name", "Src", "https://example.test", "open")])
    row = registry.load_registry()[0]
    assert row["subjects"] == 51
    assert row["license"] == "CC0"


def test_upsert_treats_zero_and_false_as_information(registry_in):
    registry.upsert([
        registry.entry("d", "Name", "Src", "https://example.test", "open", subjects=51,
                       target_available=True)
    ])
    registry.upsert([
        registry.entry("d", "Name", "Src", "https://example.test", "open", subjects=0,
                       target_available=False)
    ])
    row = registry.load_registry()[0]
    assert row["subjects"] == 0
    assert row["target_available"] is False


def test_an_unknown_access_status_is_refused():
    with pytest.raises(ValueError):
        registry.entry("d", "Name", "Src", "https://example.test", "probably_fine")


def test_the_download_log_keeps_refusals_as_well_as_successes(registry_in):
    registry.log_download({"dataset_id": "a", "status": "downloaded"})
    registry.log_download({"dataset_id": "b", "status": "skipped", "reason": "licence"})
    log = registry.load_download_log()
    assert [item["status"] for item in log] == ["downloaded", "skipped"]
    assert all("logged_at" in item for item in log)


def test_only_downloaded_datasets_rebuild_into_the_registry(registry_in):
    registry.log_download({
        "dataset_id": "owner/set", "status": "downloaded", "source": "kaggle",
        "source_url": "https://example.test", "archive_sha256": "a" * 64, "file_count": 2,
    })
    registry.log_download({"dataset_id": "owner/other", "status": "skipped", "source": "kaggle"})
    entries = registry.entries_from_download_log()
    assert [item["name"] for item in entries] == ["owner/set"]


def test_conform_drops_an_unreviewed_column_and_keeps_the_schema_order():
    frame = pd.DataFrame({
        "patient_id": ["p"], "assessment_id": ["a"], "data_source": ["s"],
        "dataset_id": ["d"], "synthetic": [True], "mystery_feature": [1.0],
    })
    assert schema.dropped_columns(frame) == ["mystery_feature"]
    conformed = schema.conform(frame, dataset_id="d")
    assert "mystery_feature" not in conformed.columns
    assert list(conformed.columns) == list(schema.FIELDS)


def test_conform_refuses_a_frame_missing_a_required_field():
    with pytest.raises(ValueError, match="missing"):
        schema.conform(pd.DataFrame({"patient_id": ["p"]}), dataset_id="d")


def _frame(**overrides) -> pd.DataFrame:
    base = {
        "patient_id": ["p1", "p2"],
        "assessment_id": ["a1", "a2"],
        "data_source": ["s", "s"],
        "dataset_id": ["d", "d"],
        "synthetic": [False, False],
    }
    base.update(overrides)
    return schema.conform(pd.DataFrame(base), dataset_id="d")


def test_an_impossible_reading_is_reported_as_an_error():
    issues = checks.check_plausible_ranges(_frame(heart_rate=[80, 400]))
    assert [item["severity"] for item in issues] == ["error"]
    assert issues[0]["examples"] == ["a2"]


def test_an_out_of_range_target_is_reported():
    issues = checks.check_plausible_ranges(_frame(self_reported_nrs=[5, 42]))
    assert any(item["column"] == "self_reported_nrs" for item in issues)


def test_validation_does_not_modify_the_frame():
    frame = _frame(heart_rate=[80, 400])
    before = frame.copy()
    checks.validate(frame)
    pd.testing.assert_frame_equal(frame, before)


def test_a_repeated_assessment_id_is_an_error():
    frame = _frame()
    frame.loc[1, "assessment_id"] = "a1"
    issues = checks.check_identity(frame)
    assert any(item["check"] == "duplicate_assessment_id" for item in issues)
    assert all(item["severity"] == "error" for item in issues
               if item["check"] == "duplicate_assessment_id")


def test_an_anatomy_token_outside_the_ontology_is_an_error():
    frame = _frame(anatomy_id=["JOINT_KNEE", "NOT_A_STRUCTURE"])
    issues = checks.check_anatomy(frame, {"JOINT_KNEE"})
    assert issues and issues[0]["severity"] == "error"
    assert "NOT_A_STRUCTURE" in issues[0]["unknown_tokens"]


def test_conflicting_pain_scales_within_one_source_are_an_error():
    frame = _frame()
    frame.loc[0, "original_pain_scale"] = "NRS 0-10"
    frame.loc[1, "original_pain_scale"] = "four-level ordinal"
    issues = checks.check_label_consistency(frame)
    assert any(item["check"] == "conflicting_pain_scales" for item in issues)


def test_a_zip_with_a_traversing_member_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.csv", "a,b\n1,2\n")
    with pytest.raises(ValueError, match="unsafe path"):
        acquire.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.csv").exists()


def test_a_well_formed_zip_extracts_and_checksums(tmp_path):
    archive = tmp_path / "fine.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/data.csv", "a,b\n1,2\n")
    extracted = acquire.safe_extract(archive, tmp_path / "out")
    assert [path.name for path in extracted] == ["data.csv"]
    assert len(acquire.sha256_of(archive)) == 64


def test_a_licence_needing_review_is_refused_without_a_recorded_reason(tmp_path, monkeypatch):
    catalog = tmp_path / "kaggle_catalog.json"
    catalog.write_text(json.dumps({
        "results": [{
            "dataset_id": "owner/set", "dataset_name": "Set",
            "license": "All Rights Reserved", "license_verdict": "review_required",
        }]
    }))
    monkeypatch.setattr(acquire, "KAGGLE_CATALOG_PATH", catalog)
    with pytest.raises(PermissionError, match="accept-reviewed-license"):
        acquire.download_kaggle("owner/set", force=False, licence_override=None)


def test_a_restricted_physionet_resource_is_refused(tmp_path, monkeypatch):
    report = tmp_path / "physionet_access_report.json"
    report.write_text(json.dumps({
        "resources": [{
            "slug": "tame-pain", "access_status": "restricted", "version": "1.0.0",
            "access_sentence": (
                "Only registered users who sign the specified data use agreement can access "
                "the files"
            ),
        }]
    }))
    monkeypatch.setattr(acquire, "PHYSIONET_ACCESS_REPORT", report)
    with pytest.raises(PermissionError, match="restricted"):
        acquire.download_physionet("tame-pain", force=False)


def test_an_undiscovered_physionet_resource_is_refused(tmp_path, monkeypatch):
    report = tmp_path / "physionet_access_report.json"
    report.write_text(json.dumps({"resources": []}))
    monkeypatch.setattr(acquire, "PHYSIONET_ACCESS_REPORT", report)
    with pytest.raises(LookupError, match="discovery"):
        acquire.download_physionet("tame-pain", force=False)


def test_profiling_reports_a_directory_with_no_table_as_having_no_data(tmp_path):
    (tmp_path / "figure.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "analysis.py").write_text("print('hello')\n")
    profile = profile_dataset(tmp_path, dataset_id="no_data")
    assert profile["has_tabular_data"] is False
    assert profile["records"] is None
    assert profile["file_count"] == 2


def test_the_uniformity_test_separates_uniform_data_from_clinical_shaped_data():
    uniform_flagged = 0
    normal_flagged = 0
    draws = 40
    for seed in range(draws):
        rng = np.random.default_rng(seed)
        uniform_flagged += uniformity(
            pd.Series(rng.uniform(0, 100, 500))
        )["consistent_with_uniform"]
        normal_flagged += uniformity(
            pd.Series(rng.normal(80, 10, 500))
        )["consistent_with_uniform"]

    assert uniform_flagged >= draws * 0.85, f"only {uniform_flagged}/{draws} uniform draws flagged"
    assert normal_flagged == 0, f"{normal_flagged}/{draws} normal draws wrongly flagged"


def test_profiling_reports_the_uniformity_verdict_per_column(tmp_path):
    rng = np.random.default_rng(0)
    pd.DataFrame({
        "subject_id": [f"s{i}" for i in range(500)],
        "uniform_column": rng.uniform(0, 100, 500),
        "clinical_column": rng.normal(80, 10, 500),
    }).to_csv(tmp_path / "data.csv", index=False)
    profiles = profile_dataset(tmp_path, dataset_id="shape")["tables"][0]["column_profiles"]
    for column in ("uniform_column", "clinical_column"):
        verdict = profiles[column]["uniformity_test"]
        assert verdict["sample_size"] == 500
        assert verdict["critical_value_95"] > 0
        assert isinstance(verdict["consistent_with_uniform"], bool)
    assert (
        profiles["uniform_column"]["uniformity_test"]["ks_statistic"]
        < profiles["clinical_column"]["uniformity_test"]["ks_statistic"]
    )
