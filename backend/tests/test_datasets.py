import hashlib
import json
from pathlib import Path

import pytest

from backend.ai import quality
from dataset.synthetic import archetypes, generate, scenarios, storage
from knowledge import anatomy, confounders, medications, questions
from knowledge import context as context_module


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    destination = tmp_path_factory.mktemp("dataset")
    path, manifest = generate.write(500, seed=13, patients=100, destination=destination)
    return path, manifest, generate.load(path)


def test_the_manifest_lists_every_file_with_its_checksum(dataset):
    path, manifest, _ = dataset
    listed = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    on_disk = {
        str(p.relative_to(path))
        for p in path.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert set(listed) == on_disk
    for relative, digest in listed.items():
        assert hashlib.sha256((path / relative).read_bytes()).hexdigest() == digest
    assert manifest["warning"].startswith("SYNTHETIC DATA")
    assert manifest["feature_schema_version"]
    assert manifest["scenario_versions"] == scenarios.VERSIONS
    for name in (
        "anatomy/anatomy_master.parquet",
        "pain/pain_master.parquet",
        "clinical/clinical_master.parquet",
        "physiology/reference_ranges.parquet",
        "patients/patient_master.parquet",
        "assessments/assessment_master.parquet",
        "scenarios/scenarios.parquet",
        "integrated/train.parquet",
        "integrated/validation.parquet",
        "integrated/test.parquet",
        "quality/validation_report.json",
    ):
        assert name in listed, name


def test_the_assessment_count_matches(dataset):
    path, manifest, loaded = dataset
    assert manifest["counts"]["assessments"] == 500
    assert storage.row_count(path / "assessments" / "assessment_master.parquet") == 500
    assert len(loaded) == 500
    report = json.loads((path / "quality" / "validation_report.json").read_text())
    assert report["rows"] == 500
    assert report["patient_overlap_between_splits"] == 0
    assert not report["leakage_checks"]["target_in_feature_columns"]
    assert sum(report["split_rows"].values()) == 500


def test_every_context_round_trips(dataset):
    _, _, loaded = dataset
    for ctx in loaded.contexts:
        assert context_module.from_dict(context_module.to_dict(ctx)) == ctx


def test_sites_are_well_formed(dataset):
    _, _, loaded = dataset
    with_sites = 0
    for ctx in loaded.contexts:
        keys = {(site.code, site.side) for site in ctx.sites}
        for site in ctx.sites:
            structure = anatomy.BY_CODE[site.code]
            assert structure.accepts(site.side), (site.code, site.side)
            assert site.role in context_module.SITE_ROLES
            if site.radiation_from:
                code, _, side = site.radiation_from.partition("|")
                assert (code, side) in keys
        if ctx.sites:
            with_sites += 1
    assert with_sites > 0.6 * len(loaded)


def test_exactly_one_primary_site_outside_the_conflict_scenario(dataset):
    _, _, loaded = dataset
    for ctx, scenario in zip(loaded.contexts, loaded.scenarios):
        if ctx.sites and scenario != scenarios.H_CONFLICTING:
            assert len(ctx.sites_with_role("PRIMARY")) == 1


def test_codes_exist_in_the_knowledge_base(dataset):
    _, _, loaded = dataset
    for ctx in loaded.contexts:
        assert ctx.confounders <= set(confounders.BY_CODE)
        assert ctx.medication_classes <= set(medications.BY_CODE)
        for entry in ctx.medications:
            assert entry.dose_category in medications.DOSE_CODES
            assert entry.frequency in medications.FREQUENCY_CODES
            assert entry.pain_effect in medications.PAIN_EFFECT_CODES
            assert entry.sedation_effect in medications.SEDATION_CODES
        assert set(ctx.answers) <= set(questions.BY_CODE)
        assert ctx.timing <= set(context_module.TIMINGS) | {"AT_REST", "AFTER_ACTIVITY"}
        assert ctx.onset_speed in context_module.ONSET_SPEEDS
        for domain, score in ctx.functional_impact.items():
            assert domain in context_module.FUNCTIONAL_DOMAINS
            assert 0 <= score <= context_module.FUNCTIONAL_MAX


def test_archetypes_only_name_known_codes():
    for archetype in archetypes.ARCHETYPES:
        for code, _ in archetype.confounders:
            assert code in confounders.BY_CODE, (archetype.code, code)
        for code, _ in archetype.medications:
            assert code in medications.BY_CODE, (archetype.code, code)
        for spec, _ in (
            archetype.primary_sites + archetype.secondary_sites + archetype.referred_sites
        ):
            assert spec.partition("|")[0] in anatomy.BY_CODE, (archetype.code, spec)
        for chain in archetype.radiation_chains:
            for spec in chain:
                assert spec.partition("|")[0] in anatomy.BY_CODE, (archetype.code, spec)
        for code, value, _ in archetype.answers:
            question = questions.BY_CODE[code]
            if question.kind == "SINGLE":
                assert value in {option for option, _ in question.options}, code
            elif question.kind == "MULTI":
                assert set(value) <= {option for option, _ in question.options}, code
            elif question.kind == "BOOL":
                assert isinstance(value, bool), code


def test_the_hard_case_share_is_respected(dataset):
    _, manifest, loaded = dataset
    hard = sum(1 for s in loaded.scenarios if s != scenarios.STANDARD)
    share = hard / len(loaded)
    assert abs(share - generate.DEFAULT_HARD_CASE_SHARE) < 0.05
    assert set(loaded.scenarios) - {scenarios.STANDARD} <= set(scenarios.BY_CODE)
    assert manifest["distribution"]["scenarios"][scenarios.STANDARD] == len(loaded) - hard


def test_conflicting_records_trip_the_consistency_checker(dataset):
    _, _, loaded = dataset
    conflicting = [
        ctx for ctx, s in zip(loaded.contexts, loaded.scenarios) if s == scenarios.H_CONFLICTING
    ]
    assert conflicting
    tripped = sum(1 for ctx in conflicting if quality.assess(ctx).issues)
    assert tripped >= 0.8 * len(conflicting)


def test_the_no_pain_scenario_reports_low_scores(dataset):
    _, _, loaded = dataset
    scores = [n for n, s in zip(loaded.targets, loaded.scenarios) if s == scenarios.NO_PAIN]
    assert scores and max(scores) <= 3


def test_the_same_seed_reproduces_the_same_rows(tmp_path: Path):
    def digest(root: Path) -> str:
        path, _ = generate.write(150, seed=99, patients=30, destination=root, chunk_size=40)
        rows = list(storage.iter_rows(path / "assessments" / "assessment_master.parquet"))
        return hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ).hexdigest()

    assert digest(tmp_path / "first") == digest(tmp_path / "second")


def test_jsonl_is_still_offered_for_the_assessment_table(tmp_path: Path):
    path, _ = generate.write(
        40, seed=2, patients=8, destination=tmp_path, storage_format="jsonl"
    )
    lines = list(storage.iter_jsonl(path / "assessments" / "assessment_master.jsonl"))
    assert len(lines) == 40
    assert generate.TARGET_COLUMN in lines[0]
    assert len(generate.load(path)) == 40
