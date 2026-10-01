"""The external dataset API: what it returns, and who is allowed to ask."""

import pytest
from sqlalchemy import select

from database.models import (
    Availability,
    Disease,
    ExternalDataset,
    ExternalDatasetVersion,
    ExternalSource,
    Granularity,
    LicenceVerdict,
    QualityStatus,
    SourceAccess,
)


@pytest.fixture
def catalogue(db):
    """A source with one held dataset and one the publisher restricts."""
    db.add(
        ExternalSource(
            code="fx_api",
            label="Fixture publisher",
            organisation="Fixture",
            homepage="https://example.invalid",
            config={},
        )
    )
    db.add(
        Disease(
            code="DENGUE",
            label="Dengue fever",
            category="INFECTIOUS",
            pain_relevant=True,
            curated=False,
            origin="external_sync",
            source_ref="fx_api:open-set",
        )
    )
    db.flush()

    held = ExternalDataset(
        source_code="fx_api",
        external_id="open-set",
        name="Dengue case records",
        description="Per-case dengue records.",
        source_url="https://example.invalid/open",
        disease_code="DENGUE",
        dataset_type="case_surveillance",
        granularity=Granularity.SUBJECT_LEVEL,
        access_status=SourceAccess.OPEN,
        licence="CC0: Public Domain",
        licence_verdict=LicenceVerdict.PERMISSIVE,
        availability=Availability.AVAILABLE,
        metadata_fingerprint="a" * 64,
        relevance=5,
    )
    restricted = ExternalDataset(
        source_code="fx_api",
        external_id="locked-set",
        name="Credentialed pain corpus",
        description="Behind a data use agreement.",
        source_url="https://example.invalid/locked",
        dataset_type="text_corpus",
        access_status=SourceAccess.CREDENTIALED,
        access_procedure=["Create an account", "Complete credentialing"],
        licence="PhysioNet Credentialed Health Data License 1.5.0",
        licence_verdict=LicenceVerdict.RESTRICTED,
        availability=Availability.METADATA_ONLY,
        metadata_fingerprint="b" * 64,
        relevance=3,
    )
    db.add_all([held, restricted])
    db.flush()
    db.add(
        ExternalDatasetVersion(
            dataset_id=held.id,
            version="1",
            source_url="https://example.invalid/open.csv",
            licence="CC0: Public Domain",
            storage_key="fx_api/open-set/1",
            bytes=2048,
            sha256="c" * 64,
            file_format="csv",
            records=1200,
            columns=["subject_id", "pain_intensity"],
            quality_status=QualityStatus.PASSED,
            trainable=True,
        )
    )
    db.flush()
    return held, restricted


def test_listing_requires_a_research_account(client, catalogue, doctor_headers):
    assert client.get("/api/external-datasets").status_code == 401
    assert client.get("/api/external-datasets", headers=doctor_headers).status_code == 403


def test_admin_can_read_the_catalogue(client, catalogue, admin_headers):
    response = client.get("/api/external-datasets", headers=admin_headers)
    assert response.status_code == 200
    names = {row["external_id"] for row in response.json()}
    assert {"open-set", "locked-set"} <= names


def test_a_restricted_dataset_exposes_its_procedure_and_no_download_url(
    client, catalogue, admin_headers
):
    rows = client.get(
        "/api/external-datasets", params={"access": "CREDENTIALED"}, headers=admin_headers
    ).json()
    assert len(rows) == 1
    assert rows[0]["availability"] == "METADATA_ONLY"
    assert rows[0]["access_procedure"]
    assert rows[0]["download_url"] is None


def test_filters_narrow_the_catalogue(client, catalogue, admin_headers):
    by_disease = client.get(
        "/api/external-datasets", params={"disease": "DENGUE"}, headers=admin_headers
    ).json()
    assert [row["external_id"] for row in by_disease] == ["open-set"]

    by_availability = client.get(
        "/api/external-datasets", params={"availability": "AVAILABLE"}, headers=admin_headers
    ).json()
    assert [row["external_id"] for row in by_availability] == ["open-set"]

    by_search = client.get(
        "/api/external-datasets", params={"search": "credentialed"}, headers=admin_headers
    ).json()
    assert [row["external_id"] for row in by_search] == ["locked-set"]


def test_detail_includes_the_stored_versions(client, catalogue, admin_headers):
    held, _ = catalogue
    body = client.get(f"/api/external-datasets/{held.id}", headers=admin_headers).json()
    assert len(body["versions"]) == 1
    version = body["versions"][0]
    assert version["records"] == 1200
    assert version["sha256"] == "c" * 64
    assert version["licence"] == "CC0: Public Domain"


def test_unknown_dataset_is_404(client, catalogue, admin_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/external-datasets/{missing}", headers=admin_headers).status_code == 404


def test_overview_drives_the_dashboard_from_data(client, catalogue, admin_headers):
    body = client.get("/api/external-datasets/overview", headers=admin_headers).json()

    assert body["totals"]["datasets"] >= 2
    assert body["totals"]["available"] >= 1
    assert body["totals"]["metadata_only"] >= 1
    assert body["totals"]["bytes_held"] >= 2048
    assert body["notice"]

    dengue = next(row for row in body["diseases"] if row["code"] == "DENGUE")
    assert dengue["datasets"] == 1
    assert dengue["records_held"] == 1200
    assert dengue["curated"] is False
    assert dengue["origin"] == "external_sync"
    assert dengue["sources"] == ["fx_api"]


def test_overview_lists_every_configured_source(client, admin_headers):
    """The four real publishers are created on first read, not hand-registered."""
    body = client.get("/api/external-datasets/overview", headers=admin_headers).json()
    codes = {source["code"] for source in body["sources"]}
    assert {"who_gho", "cdc_socrata", "kaggle", "physionet"} <= codes


def test_source_rows_never_return_credentials(client, admin_headers):
    body = client.get("/api/external-datasets/sources", headers=admin_headers).json()
    kaggle = next(source for source in body if source["code"] == "kaggle")
    assert kaggle["uses_credentials"] is True
    assert kaggle["credentials_present"] is False
    assert "kaggle_key" not in str(body).casefold()
    assert "password" not in str(body).casefold()


def test_only_an_admin_may_change_a_source(client, admin_headers, doctor_headers):
    client.get("/api/external-datasets/sources", headers=admin_headers)
    payload = {"enabled": False, "poll_interval_minutes": 720}
    assert client.patch("/api/external-datasets/sources/kaggle", json=payload).status_code == 401
    assert (
        client.patch(
            "/api/external-datasets/sources/kaggle", json=payload, headers=doctor_headers
        ).status_code
        == 403
    )
    response = client.patch(
        "/api/external-datasets/sources/kaggle", json=payload, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["poll_interval_minutes"] == 720


def test_a_source_update_is_validated(client, admin_headers):
    client.get("/api/external-datasets/sources", headers=admin_headers)
    response = client.patch(
        "/api/external-datasets/sources/kaggle",
        json={"poll_interval_minutes": 1},
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_updating_an_unknown_source_is_404(client, admin_headers):
    response = client.patch(
        "/api/external-datasets/sources/nope", json={"enabled": True}, headers=admin_headers
    )
    assert response.status_code == 404


def test_only_an_admin_may_start_a_run(client, admin_headers, doctor_headers):
    assert client.post("/api/external-datasets/sync", json={}).status_code == 401
    assert (
        client.post("/api/external-datasets/sync", json={}, headers=doctor_headers).status_code
        == 403
    )
    response = client.post("/api/external-datasets/sync", json={}, headers=admin_headers)
    assert response.status_code == 202
    assert response.json()["kind"] == "sync_datasets"
    assert response.json()["status"] == "QUEUED"


def test_starting_a_run_for_an_unknown_source_is_404(client, admin_headers):
    response = client.post(
        "/api/external-datasets/sync", json={"source": "nope"}, headers=admin_headers
    )
    assert response.status_code == 404


def test_a_requested_run_is_written_to_the_audit_trail(client, db, admin_headers):
    from database.models import AuditLog

    client.post(
        "/api/external-datasets/sync", json={"source": "kaggle"}, headers=admin_headers
    )
    entry = db.scalar(
        select(AuditLog)
        .where(AuditLog.resource == "external_sync")
        .order_by(AuditLog.timestamp.desc())
    )
    assert entry is not None
    assert entry.meta["action"] == "sync_requested"


def test_the_clinical_disease_list_excludes_discovered_entries(client, catalogue, doctor_headers):
    """Regression guard: an imported disease must not reach a clinician's comorbidity picker."""
    codes = {row["code"] for row in client.get("/api/diseases", headers=doctor_headers).json()}
    assert "DENGUE" not in codes
    assert "MIGRAINE" in codes


def test_runs_and_events_are_readable(client, admin_headers):
    assert client.get("/api/external-datasets/runs", headers=admin_headers).status_code == 200
    assert client.get("/api/external-datasets/events", headers=admin_headers).status_code == 200
