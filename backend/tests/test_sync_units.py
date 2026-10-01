"""Unit coverage for the parts of dataset synchronisation that make the decisions.

Nothing here touches the network. The connectors are exercised against recorded publisher
responses in `test_sync_pipeline.py`; what is checked here is the reasoning applied to
whatever a publisher says.
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from database.models import (
    Availability,
    Granularity,
    LicenceVerdict,
    QualityStatus,
    SourceAccess,
)
from backend.sync import fingerprint, licensing, profile, storage, suitability, validate
from backend.sync.sources.base import RemoteDataset

# --- licence and access gates --------------------------------------------------------


@pytest.mark.parametrize(
    ("licence", "expected"),
    [
        ("CC0: Public Domain", LicenceVerdict.PERMISSIVE),
        ("Apache 2.0", LicenceVerdict.PERMISSIVE),
        ("  cc   by   4.0  ", LicenceVerdict.PERMISSIVE),
        ("Attribution-NonCommercial 4.0 International", LicenceVerdict.RESEARCH_ONLY),
        (
            "WHO publishing and copyright policy (CC BY-NC-SA 3.0 IGO for GHO content)",
            LicenceVerdict.RESEARCH_ONLY,
        ),
        ("PhysioNet Credentialed Health Data License 1.5.0", LicenceVerdict.RESTRICTED),
        ("Some Bespoke Institutional Licence", LicenceVerdict.REVIEW_REQUIRED),
        ("Unknown", LicenceVerdict.UNKNOWN),
        (None, LicenceVerdict.UNKNOWN),
    ],
)
def test_licence_verdicts(licence, expected):
    assert licensing.verdict(licence) is expected


def test_restriction_outranks_non_commercial():
    """A licence that is both non-commercial and agreement-bound is restricted, not research."""
    verdict = licensing.verdict("Non-commercial use under a signed data use agreement")
    assert verdict is LicenceVerdict.RESTRICTED


def test_open_and_permissive_is_the_only_combination_that_downloads():
    assert licensing.refusal(SourceAccess.OPEN, LicenceVerdict.PERMISSIVE) is None
    assert licensing.refusal(SourceAccess.OPEN, LicenceVerdict.RESEARCH_ONLY) is None
    for access in (
        SourceAccess.CREDENTIALED,
        SourceAccess.AGREEMENT_REQUIRED,
        SourceAccess.REGISTRATION_REQUIRED,
        SourceAccess.DOCUMENT_ONLY,
        SourceAccess.UNKNOWN,
    ):
        assert licensing.refusal(access, LicenceVerdict.PERMISSIVE) is not None


def test_access_refusal_is_reported_before_licence():
    """A credentialed dataset is refused on access even when its licence is permissive."""
    message = licensing.refusal(SourceAccess.CREDENTIALED, LicenceVerdict.UNKNOWN)
    assert "restricts access" in message


def test_every_restricted_access_status_has_a_procedure():
    for access in SourceAccess:
        if access is SourceAccess.OPEN:
            continue
        assert licensing.procedure(access), f"{access} has no recorded procedure"


# --- fingerprints ---------------------------------------------------------------------


def test_metadata_fingerprint_ignores_key_order():
    assert fingerprint.of_metadata({"a": 1, "b": [1, 2]}) == fingerprint.of_metadata(
        {"b": [1, 2], "a": 1}
    )


def test_metadata_fingerprint_changes_with_a_revised_listing():
    base = RemoteDataset(external_id="x", name="A", source_url="https://example.org/a")
    revised = RemoteDataset(
        external_id="x", name="A", source_url="https://example.org/a", licence="CC0: Public Domain"
    )
    assert fingerprint.of_metadata(base.fingerprint_fields()) != fingerprint.of_metadata(
        revised.fingerprint_fields()
    )


def test_popularity_counters_do_not_count_as_a_change():
    """Kaggle's download count moves constantly and says nothing about the data."""
    before = RemoteDataset(external_id="x", name="A", source_url="https://e.org", relevance=4)
    after = RemoteDataset(external_id="x", name="A", source_url="https://e.org", relevance=9)
    assert fingerprint.of_metadata(before.fingerprint_fields()) == fingerprint.of_metadata(
        after.fingerprint_fields()
    )


def test_directory_fingerprint_notices_a_rename(tmp_path):
    first = tmp_path / "a"
    first.mkdir()
    (first / "one.csv").write_text("x\n1\n")
    before = fingerprint.of_directory(first)
    (first / "one.csv").rename(first / "two.csv")
    assert fingerprint.of_directory(first) != before


# --- archive safety --------------------------------------------------------------------


def test_archive_traversal_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.csv", "a,b\n1,2\n")
    with pytest.raises(storage.UnsafeArchive):
        storage.safe_extract(archive, tmp_path / "out", max_bytes=1 << 20)
    assert not (tmp_path / "escaped.csv").exists()


def test_absolute_archive_member_is_refused(tmp_path):
    archive = tmp_path / "abs.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("/etc/passwd", "root\n")
    with pytest.raises(storage.UnsafeArchive):
        storage.safe_extract(archive, tmp_path / "out", max_bytes=1 << 20)


def test_oversized_archive_is_refused_before_writing(tmp_path):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("big.txt", "0" * 2_000_000)
    destination = tmp_path / "out"
    with pytest.raises(storage.UnsafeArchive):
        storage.safe_extract(archive, destination, max_bytes=1000)
    assert not any(destination.rglob("*.txt"))


def test_storage_key_cannot_escape_the_root():
    with pytest.raises(storage.UnsafeArchive):
        storage.resolve("../../etc/passwd")


def test_slug_strips_path_separators():
    assert "/" not in storage.slug("owner/dataset-name")


# --- profiling -------------------------------------------------------------------------


def _csv(path: Path, frame: pd.DataFrame) -> tuple[Path, ...]:
    frame.to_csv(path, index=False)
    return (path,)


def test_profile_measures_a_subject_level_pain_table(tmp_path):
    frame = pd.DataFrame(
        {
            "subject_id": [f"s{i % 12}" for i in range(240)],
            "heart_rate": range(240),
            "eda": [i / 3 for i in range(240)],
            "pain_intensity": [i % 11 for i in range(240)],
        }
    )
    measured = profile.describe(_csv(tmp_path / "d.csv", frame))

    assert measured.rows == 240
    assert measured.subject_column == "subject_id"
    assert measured.subjects == 12
    assert measured.target_column == "pain_intensity"
    assert measured.target_scale == profile.NRS
    assert measured.granularity is Granularity.SUBJECT_LEVEL


def test_profile_reads_an_aggregate_table_as_aggregate(tmp_path):
    frame = pd.DataFrame(
        {"Country": ["DZ", "FR"] * 50, "Year": [2020, 2021] * 50, "Value": range(100)}
    )
    measured = profile.describe(_csv(tmp_path / "gho.csv", frame))

    assert measured.granularity is Granularity.AGGREGATE
    assert measured.target_column is None


def test_profile_detects_a_binary_flag_rather_than_an_intensity(tmp_path):
    frame = pd.DataFrame(
        {"subject_id": [f"s{i}" for i in range(100)], "x": range(100), "pain": [0, 1] * 50}
    )
    measured = profile.describe(_csv(tmp_path / "b.csv", frame))
    assert measured.target_scale == profile.BINARY


def test_profile_reports_no_tabular_file(tmp_path):
    image = tmp_path / "scan.png"
    image.write_bytes(b"\x89PNG\r\n")
    measured = profile.describe((image,))
    assert measured.file is None
    assert measured.notes


def test_row_count_is_full_while_statistics_are_sampled(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "SAMPLE_ROWS", 50)
    frame = pd.DataFrame({"subject_id": [f"s{i%9}" for i in range(400)], "v": range(400)})
    measured = profile.describe(_csv(tmp_path / "wide.csv", frame))
    assert measured.rows == 400
    assert measured.sampled_rows == 50
    assert any("computed from the first" in note for note in measured.notes)


# --- suitability -------------------------------------------------------------------------


def _profile(**kwargs) -> profile.Profile:
    base = {
        "file": "d.csv",
        "rows": 1000,
        "sampled_rows": 1000,
        "columns": ["subject_id", "hr", "eda", "pain_intensity"],
        "numeric_columns": ["hr", "eda", "pain_intensity"],
        "subject_column": "subject_id",
        "subjects": 30,
        "target_column": "pain_intensity",
        "target_scale": profile.NRS,
        "granularity": Granularity.SUBJECT_LEVEL,
    }
    return profile.Profile(**{**base, **kwargs})


def test_a_well_formed_subject_level_pain_table_is_trainable():
    verdict = suitability.assess(_profile())
    assert verdict.trainable
    assert verdict.clinically_usable is False


def test_aggregate_data_is_never_trainable():
    verdict = suitability.assess(
        _profile(granularity=Granularity.AGGREGATE, subject_column=None, subjects=None)
    )
    assert not verdict.trainable
    assert any("places and periods" in reason for reason in verdict.reasons)


def test_a_binary_label_is_refused_for_the_regression_task():
    verdict = suitability.assess(_profile(target_scale=profile.BINARY))
    assert not verdict.trainable
    assert any("binary" in reason for reason in verdict.reasons)


def test_missing_subject_identifier_is_refused_as_leakage():
    verdict = suitability.assess(
        _profile(subject_column=None, subjects=None, granularity=Granularity.UNKNOWN)
    )
    assert not verdict.trainable
    assert any("leakage" in reason for reason in verdict.reasons)


def test_too_few_subjects_is_refused():
    verdict = suitability.assess(_profile(subjects=3))
    assert not verdict.trainable


def test_too_few_rows_is_refused():
    verdict = suitability.assess(_profile(rows=20))
    assert not verdict.trainable


def test_a_verdict_always_explains_itself():
    verdict = suitability.assess(_profile(target_column=None, target_scale=profile.UNKNOWN_SCALE))
    assert verdict.reasons
    assert verdict.as_dict()["note"]


# --- validation --------------------------------------------------------------------------


def test_validation_flags_a_rating_outside_its_own_scale(tmp_path):
    frame = pd.DataFrame(
        {"subject_id": [f"s{i%10}" for i in range(300)], "pain_intensity": [5] * 299 + [99]}
    )
    files = _csv(tmp_path / "bad.csv", frame)
    measured = profile.describe(files)
    report = validate.check(files, measured)

    assert report.status is QualityStatus.FAILED
    assert any(f.check == "target_range" for f in report.findings)


def test_validation_flags_a_constant_target(tmp_path):
    frame = pd.DataFrame(
        {"subject_id": [f"s{i%10}" for i in range(300)], "pain_intensity": [5.0] * 300}
    )
    files = _csv(tmp_path / "flat.csv", frame)
    report = validate.check(files, profile.describe(files))
    assert any(f.check == "target_variation" for f in report.findings)


def test_duplicates_are_dropped_from_the_copy_not_the_original(tmp_path):
    frame = pd.DataFrame({"subject_id": ["s1"] * 10, "v": [1] * 10})
    source = tmp_path / "dupes.csv"
    files = _csv(source, frame)
    original = source.read_text()
    report = validate.check(files, profile.describe(files))

    assert report.duplicate_rows == 9
    assert len(report.cleaned) == 1
    assert source.read_text() == original


def test_an_empty_table_fails_validation(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_text("a,b\n")
    report = validate.check((source,), profile.describe((source,)))
    assert report.status is QualityStatus.FAILED


def test_preprocessed_copy_normalises_headers(tmp_path):
    frame = pd.DataFrame({"Subject ID": ["s1", "s2"], "Pain-Intensity": [1, 2]})
    out = validate.write_preprocessed(frame, tmp_path / "p.parquet")
    assert list(pd.read_parquet(out).columns) == ["subject_id", "pain_intensity"]


def test_availability_and_access_are_separate_vocabularies():
    """Regression guard: conflating the two is the failure this schema exists to prevent."""
    assert not {a.value for a in Availability} & {s.value for s in SourceAccess}
