"""The synchronisation pipeline end to end, against connectors that serve local files.

A real publisher is not reachable from a test run and should not be, so these use a
connector that returns listings from memory and writes files from a fixture. Everything
between discovery and the training verdict is the production code path: the same catalogue
upsert, the same licence gate, the same profiler, the same suitability rules.
"""

import uuid

import pandas as pd
import pytest
from sqlalchemy import select

from backend.sync import service
from backend.sync import sources as connectors
from backend.sync.fingerprint import of_directory
from backend.sync.sources.base import Acquired, Connector, RemoteDataset
from database.models import (
    Availability,
    Disease,
    ExternalDataset,
    ExternalDatasetVersion,
    ExternalSource,
    Granularity,
    JobStatus,
    LicenceVerdict,
    SourceAccess,
    SyncEvent,
    SyncOutcome,
    SyncRun,
    SyncStage,
)


def _pain_frame(rows: int = 400, subjects: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "subject_id": [f"s{i % subjects}" for i in range(rows)],
            "heart_rate": [60 + (i % 40) for i in range(rows)],
            "eda_tonic": [(i % 17) / 2 for i in range(rows)],
            "skin_temp_c": [32 + (i % 50) / 10 for i in range(rows)],
            "pain_intensity": [i % 11 for i in range(rows)],
        }
    )


class FakeConnector(Connector):
    """Serves listings from memory and writes a CSV, with no network access at all."""

    def __init__(self, code, listings, frame=None, fail_with=None):
        super().__init__(
            code=code,
            label=f"Fake {code}",
            organisation="Fixture publisher",
            homepage="https://example.invalid",
            hosts=("example.invalid",),
            default_config={},
        )
        self.listings = listings
        self.frame = frame if frame is not None else _pain_frame()
        self.fail_with = fail_with
        self.fetches: list[str] = []

    def discover(self, config):
        if self.fail_with:
            raise self.fail_with
        return list(self.listings)

    def fetch(self, dataset, destination, *, max_bytes):
        self.fetches.append(dataset.external_id)
        target = destination / "records.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        self.frame.to_csv(target, index=False)
        return Acquired(
            files=(target,),
            bytes=target.stat().st_size,
            sha256=of_directory(destination),
            file_format="csv",
            version=dataset.publisher_version or "2026-01-01",
            retrieved_from="https://example.invalid/records.csv",
        )


def _listing(external_id="fixture/pain-study", **overrides) -> RemoteDataset:
    base = {
        "external_id": external_id,
        "name": "Chronic pain intensity recordings",
        "description": "Per-subject pain intensity with physiological signals.",
        "source_url": "https://example.invalid/d/1",
        "download_url": "https://example.invalid/d/1.csv",
        "access_status": SourceAccess.OPEN,
        "licence": "CC0: Public Domain",
        "publisher_version": "1",
        "relevance": 5,
    }
    return RemoteDataset(**{**base, **overrides})


@pytest.fixture
def register(db, monkeypatch):
    """Install a fake connector and give it a configured source row."""
    installed = []

    def _install(connector: FakeConnector) -> FakeConnector:
        monkeypatch.setitem(connectors.BY_CODE, connector.code, connector)
        monkeypatch.setattr(
            connectors, "CONNECTORS", (*connectors.CONNECTORS, connector), raising=False
        )
        db.add(
            ExternalSource(
                code=connector.code,
                label=connector.label,
                organisation=connector.organisation,
                homepage=connector.homepage,
                enabled=True,
                poll_interval_minutes=360,
                config={},
            )
        )
        db.flush()
        installed.append(connector)
        return connector

    return _install


def _events(db, run_id, stage):
    return db.scalars(
        select(SyncEvent).where(SyncEvent.run_id == run_id, SyncEvent.stage == stage)
    ).all()


# --- the happy path ---------------------------------------------------------------------


def test_open_permissive_dataset_is_catalogued_stored_and_assessed(db, register):
    register(FakeConnector("fx_open", [_listing()]))
    summary = service.run_source(db, "fx_open", trigger="manual", acquire=True)

    assert summary.discovered == 1
    assert summary.created == 1
    assert summary.acquired == 1

    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_open"))
    assert row.availability is Availability.AVAILABLE
    assert row.licence_verdict is LicenceVerdict.PERMISSIVE
    assert row.granularity is Granularity.SUBJECT_LEVEL

    version = db.scalar(
        select(ExternalDatasetVersion).where(ExternalDatasetVersion.dataset_id == row.id)
    )
    assert version.records == 400
    assert version.sha256
    assert "pain_intensity" in version.columns
    assert version.preprocessed_key
    assert version.trainable is True
    assert version.suitability["clinically_usable"] is False


def test_provenance_is_preserved_on_the_stored_version(db, register):
    register(FakeConnector("fx_prov", [_listing()]))
    service.run_source(db, "fx_prov", trigger="manual", acquire=True)

    version = db.scalar(
        select(ExternalDatasetVersion).join(ExternalDataset).where(
            ExternalDataset.source_code == "fx_prov"
        )
    )
    assert version.licence == "CC0: Public Domain"
    assert version.source_url.startswith("https://")
    assert version.acquired_at is not None
    assert version.version == "1"
    assert version.manifest and version.manifest[0]["sha256"]


def test_every_stage_is_written_to_the_synchronisation_log(db, register):
    register(FakeConnector("fx_log", [_listing()]))
    summary = service.run_source(db, "fx_log", trigger="manual", acquire=True)
    run_id = uuid.UUID(summary.run_id)

    for stage in (
        SyncStage.DISCOVER,
        SyncStage.IDENTIFY_DISEASE,
        SyncStage.ACQUIRE,
        SyncStage.VALIDATE,
        SyncStage.PREPROCESS,
        SyncStage.SUITABILITY,
    ):
        assert _events(db, run_id, stage), f"no event recorded for {stage}"


# --- access restrictions ------------------------------------------------------------------


@pytest.mark.parametrize(
    "access",
    [
        SourceAccess.CREDENTIALED,
        SourceAccess.AGREEMENT_REQUIRED,
        SourceAccess.REGISTRATION_REQUIRED,
        SourceAccess.DOCUMENT_ONLY,
    ],
)
def test_a_restricted_dataset_is_catalogued_but_never_fetched(db, register, access):
    connector = register(
        FakeConnector(f"fx_{access.value.lower()}", [_listing(access_status=access)])
    )
    summary = service.run_source(db, connector.code, trigger="manual", acquire=True)

    assert connector.fetches == [], "a restricted dataset must not be downloaded"
    assert summary.metadata_only == 1
    row = db.scalar(
        select(ExternalDataset).where(ExternalDataset.source_code == connector.code)
    )
    assert row.availability is Availability.METADATA_ONLY
    assert row.access_procedure, "a refused dataset must record how a person would obtain it"
    assert not db.scalars(
        select(ExternalDatasetVersion).where(ExternalDatasetVersion.dataset_id == row.id)
    ).all()


def test_an_unreviewed_licence_blocks_the_download(db, register):
    connector = register(
        FakeConnector("fx_lic", [_listing(licence="Bespoke Institutional Terms v2")])
    )
    service.run_source(db, "fx_lic", trigger="manual", acquire=True)

    assert connector.fetches == []
    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_lic"))
    assert row.licence_verdict is LicenceVerdict.REVIEW_REQUIRED
    assert row.availability is Availability.METADATA_ONLY


def test_a_research_only_licence_is_retrieved_and_marked_non_redistributable(db, register):
    connector = register(
        FakeConnector("fx_nc", [_listing(licence="Attribution-NonCommercial 4.0 International")])
    )
    service.run_source(db, "fx_nc", trigger="manual", acquire=True)

    assert connector.fetches == ["fixture/pain-study"]
    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_nc"))
    assert row.licence_verdict is LicenceVerdict.RESEARCH_ONLY
    assert "no redistribution" in row.redistribution


# --- change, duplicate and retry behaviour --------------------------------------------------


def test_an_unchanged_listing_is_not_downloaded_twice(db, register):
    connector = register(FakeConnector("fx_same", [_listing()]))
    service.run_source(db, "fx_same", trigger="manual", acquire=True)
    assert connector.fetches == ["fixture/pain-study"]

    second = service.run_source(db, "fx_same", trigger="manual", acquire=True)
    assert second.unchanged == 1
    assert connector.fetches == ["fixture/pain-study"], "an unchanged listing was re-fetched"


def test_identical_bytes_under_a_new_version_are_not_stored_again(db, register):
    connector = register(FakeConnector("fx_dupe", [_listing(publisher_version="1")]))
    service.run_source(db, "fx_dupe", trigger="manual", acquire=True)

    connector.listings = [_listing(publisher_version="2")]
    summary = service.run_source(db, "fx_dupe", trigger="manual", acquire=True)

    assert summary.updated == 1
    assert summary.duplicates == 1
    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_dupe"))
    versions = db.scalars(
        select(ExternalDatasetVersion).where(ExternalDatasetVersion.dataset_id == row.id)
    ).all()
    assert len(versions) == 1, "the same bytes were stored under two versions"


def test_changed_content_is_stored_as_a_second_version(db, register):
    connector = register(FakeConnector("fx_rev", [_listing(publisher_version="1")]))
    service.run_source(db, "fx_rev", trigger="manual", acquire=True)

    connector.listings = [_listing(publisher_version="2")]
    connector.frame = _pain_frame(rows=600, subjects=25)
    service.run_source(db, "fx_rev", trigger="manual", acquire=True)

    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_rev"))
    versions = db.scalars(
        select(ExternalDatasetVersion).where(ExternalDatasetVersion.dataset_id == row.id)
    ).all()
    assert {v.version for v in versions} == {"1", "2"}
    assert {v.records for v in versions} == {400, 600}


def test_a_failed_acquisition_is_recorded_and_backed_off(db, register):
    class Broken(FakeConnector):
        def fetch(self, dataset, destination, *, max_bytes):
            raise connectors.Unavailable("the publisher returned a sign-in page")

    register(Broken("fx_fail", [_listing()]))
    summary = service.run_source(db, "fx_fail", trigger="manual", acquire=True)

    assert summary.failed == 1
    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_fail"))
    assert row.availability is Availability.FAILED
    assert row.attempts == 1
    assert row.next_attempt_at is not None
    assert "sign-in page" in row.last_error


def test_a_discovery_failure_marks_the_run_without_losing_the_catalogue(db, register):
    register(FakeConnector("fx_down", [], fail_with=connectors.Unavailable("host unreachable")))
    summary = service.run_source(db, "fx_down", trigger="manual", acquire=True)

    assert summary.errors
    run = db.scalar(select(SyncRun).where(SyncRun.source_code == "fx_down"))
    assert run.status.value == "FAILED"
    source = db.get(ExternalSource, "fx_down")
    assert source.consecutive_failures == 1
    assert source.next_run_at is not None, "a failing source must still be rescheduled"


def test_the_acquisition_budget_is_respected(db, register):
    listings = [_listing(external_id=f"fixture/d{i}") for i in range(5)]
    connector = register(FakeConnector("fx_budget", listings))
    summary = service.run_source(db, "fx_budget", trigger="manual", acquire=True, limit=2)

    assert len(connector.fetches) == 2
    assert summary.created == 5
    skipped = [
        event
        for event in db.scalars(
            select(SyncEvent).where(
                SyncEvent.source_code == "fx_budget", SyncEvent.stage == SyncStage.ACQUIRE
            )
        )
        if event.outcome is SyncOutcome.SKIPPED
    ]
    assert any("budget" in event.message for event in skipped)


def test_discovery_only_mode_stores_nothing(db, register):
    connector = register(FakeConnector("fx_dry", [_listing()]))
    summary = service.run_source(db, "fx_dry", trigger="manual", acquire=False)

    assert summary.created == 1
    assert connector.fetches == []
    assert summary.acquired == 0


# --- disease identification -----------------------------------------------------------------


def test_a_known_disease_is_reused_rather_than_duplicated(db, register):
    before = db.scalar(select(Disease).where(Disease.code == "MIGRAINE"))
    assert before is not None

    register(
        FakeConnector(
            "fx_known",
            [_listing(name="Migraine symptom records", description="Migraine attack diary.")],
        )
    )
    service.run_source(db, "fx_known", trigger="manual", acquire=False)

    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_known"))
    assert row.disease_code == "MIGRAINE"
    assert db.get(Disease, "MIGRAINE").curated is True


def test_an_unknown_disease_is_created_uncurated_with_provenance(db, register):
    assert db.get(Disease, "CHOLERA") is None

    register(
        FakeConnector(
            "fx_new",
            [_listing(name="Cholera reported cases", description="Cholera cases per country.")],
        )
    )
    summary = service.run_source(db, "fx_new", trigger="manual", acquire=False)

    assert summary.diseases_created == 1
    created = db.get(Disease, "CHOLERA")
    assert created is not None
    assert created.curated is False, "a discovered disease must not enter the clinical list"
    assert created.origin == "external_sync"
    assert created.source_ref == "fx_new:fixture/pain-study"
    assert created.discovered_at is not None


def test_a_dataset_naming_no_disease_is_left_unattributed(db, register):
    register(
        FakeConnector(
            "fx_none",
            [_listing(name="Biosignal recordings", description="Sensor traces from volunteers.")],
        )
    )
    service.run_source(db, "fx_none", trigger="manual", acquire=False)

    row = db.scalar(select(ExternalDataset).where(ExternalDataset.source_code == "fx_none"))
    assert row.disease_code is None
    assert row.disease_match["basis"]


# --- the training gate --------------------------------------------------------------------


def test_an_aggregate_dataset_does_not_queue_training(db, register):
    aggregate = pd.DataFrame(
        {"country": ["DZ", "FR"] * 150, "year": [2020, 2021] * 150, "value": range(300)}
    )
    register(FakeConnector("fx_agg", [_listing()], frame=aggregate))
    summary = service.run_source(db, "fx_agg", trigger="manual", acquire=True)

    assert summary.training_queued == 0
    version = db.scalar(
        select(ExternalDatasetVersion).join(ExternalDataset).where(
            ExternalDataset.source_code == "fx_agg"
        )
    )
    assert version.trainable is False
    assert version.suitability["reasons"]


def test_a_suitable_dataset_queues_a_baseline_job(db, register):
    from database.models import BackgroundJob

    register(FakeConnector("fx_train", [_listing()]))
    summary = service.run_source(db, "fx_train", trigger="manual", acquire=True)

    assert summary.training_queued == 1
    version = db.scalar(
        select(ExternalDatasetVersion).join(ExternalDataset).where(
            ExternalDataset.source_code == "fx_train"
        )
    )
    job = db.get(BackgroundJob, version.training_job_id)
    assert job.kind == "train_external_baseline"
    assert job.status is JobStatus.QUEUED


def test_the_baseline_trains_and_is_recorded_inactive(db, register):
    from database.models import ModelVersion

    register(FakeConnector("fx_fit", [_listing()]))
    service.run_source(db, "fx_fit", trigger="manual", acquire=True)
    version = db.scalar(
        select(ExternalDatasetVersion).join(ExternalDataset).where(
            ExternalDataset.source_code == "fx_fit"
        )
    )

    result = service.train_external_baseline(db, version.id)
    assert result["n_test"] > 0
    assert result["cv_folds"] >= 2

    model = db.scalar(
        select(ModelVersion).where(ModelVersion.version == result["model_version"])
    )
    assert model.is_active is False, "an external baseline must never become the active model"
    assert model.model_name.startswith("external-baseline:")
    assert "not usable for a clinical estimate" in model.notes.casefold()


def test_the_baseline_splits_by_subject(db, register):
    """No subject may appear on both sides of the split, or the score is leakage."""
    from backend.sync import training as external_training

    frame = _pain_frame(rows=600, subjects=24)
    result, _model = external_training.train(frame, target="pain_intensity", subject="subject_id")
    assert result.n_subjects == 24
    assert result.n_train + result.n_test == len(frame)
    assert result.cv_folds >= 2
    assert "subject_id" not in result.features
    assert "pain_intensity" not in result.features
