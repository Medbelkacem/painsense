"""US Centers for Disease Control and Prevention, over the Socrata open data service.

Discovery uses Socrata's own catalogue API rather than a hand-maintained list of dataset
identifiers, so a dataset CDC publishes tomorrow is found tomorrow. The catalogue returns
the licence, the row count and the update time CDC currently states, and those are
recorded as the publisher's figures.

Acquisition takes the CSV export of the view. Two things are worth knowing about it. The
export is the whole view, which for the larger case-surveillance files is gigabytes, so
the byte cap does real work here and a dataset that exceeds it is recorded as too large
rather than half-downloaded. And `rowsUpdatedAt` is the only version identifier Socrata
offers, so that timestamp is the version.

Most CDC datasets are US Government works in the public domain, but the per-dataset
licence field is frequently null. Where it is, the domain-wide position is recorded with a
note saying it came from the site policy and not from the dataset's own metadata.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from backend.sync import http
from backend.sync.sources.base import (
    AGGREGATE_STATISTICS,
    CASE_SURVEILLANCE,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
    extension_of,
)
from database.models import Granularity, SourceAccess

CATALOGUE = "https://api.us.socrata.com/api/catalog/v1"
DOMAIN = "data.cdc.gov"
DOMAIN_LICENCE = "Public Domain U.S. Government"
DOMAIN_TERMS = "https://www.usa.gov/government-works"
LICENCE_FROM_DOMAIN = (
    "the dataset's own Socrata metadata declares no licence; recorded from the "
    "data.cdc.gov domain position for US Government works"
)

DEFAULT_QUERIES = ("pain", "opioid", "notifiable disease", "covid-19 case surveillance")

#: Socrata describes a view's shape nowhere machine-readably, so the distinction between a
#: per-case file and a summary table is drawn from the name. It is a weaker signal than
#: reading the file, and `app.sync.profile` corrects it once the rows are on disk.
CASE_LEVEL_MARKERS = ("case surveillance", "patient-level", "individual record", "line list")


def _parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


class CdcSocrata(Connector):
    def discover(self, config: dict) -> list[RemoteDataset]:
        queries = tuple(config.get("queries") or DEFAULT_QUERIES)
        per_query = int(config.get("per_query", 15))
        client = self.client()

        found: dict[str, RemoteDataset] = {}
        failures: list[str] = []
        for query in queries:
            url = (
                f"{CATALOGUE}?domains={DOMAIN}&search_context={DOMAIN}"
                f"&q={urllib.parse.quote(query)}&only=dataset&limit={per_query}"
            )
            try:
                payload = client.get_json(url, max_bytes=16 << 20)
            except http.TransferError as exc:
                failures.append(f"{query}: {exc}")
                continue
            for item in payload.get("results", []) if isinstance(payload, dict) else []:
                entry = self._describe(item)
                if entry is not None:
                    found.setdefault(entry.external_id, entry)
        if not found and failures:
            raise Unavailable("the Socrata catalogue could not be read: " + "; ".join(failures))
        return list(found.values())

    @staticmethod
    def _describe(item: dict) -> RemoteDataset | None:
        resource = item.get("resource") or {}
        identifier = (resource.get("id") or "").strip()
        name = (resource.get("name") or "").strip()
        if not identifier or not name:
            return None
        description = " ".join((resource.get("description") or "").split())[:4000]
        licence = (item.get("metadata") or {}).get("license") or resource.get("license")
        haystack = f"{name} {description}".casefold()
        case_level = any(marker in haystack for marker in CASE_LEVEL_MARKERS)
        return RemoteDataset(
            external_id=identifier,
            name=name,
            description=description,
            source_url=(item.get("permalink") or f"https://{DOMAIN}/d/{identifier}"),
            download_url=f"https://{DOMAIN}/api/views/{identifier}/rows.csv?accessType=DOWNLOAD",
            download_mechanism="Socrata CSV export",
            dataset_type=CASE_SURVEILLANCE if case_level else AGGREGATE_STATISTICS,
            granularity=Granularity.SUBJECT_LEVEL if case_level else Granularity.AGGREGATE,
            modalities=("tabular_clinical",) if case_level else ("tabular_aggregate",),
            access_status=SourceAccess.OPEN,
            licence=licence or DOMAIN_LICENCE,
            licence_url=DOMAIN_TERMS,
            publisher_updated_at=_parsed_time(resource.get("updatedAt")),
            records_claimed=None,
            relevance=2,
            notes="" if licence else LICENCE_FROM_DOMAIN,
        )

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        if not dataset.download_url:
            raise Unavailable("this view publishes no export URL")
        client = self.client()

        version = None
        try:
            view = client.get_json(
                f"https://{DOMAIN}/api/views/{dataset.external_id}.json", max_bytes=8 << 20
            )
            updated = _epoch(view.get("rowsUpdatedAt"))
            version = updated.strftime("%Y-%m-%d") if updated else None
        except (http.TransferError, AttributeError):
            # The view metadata is a convenience: it supplies a better version string than
            # the acquisition date. Losing it is not a reason to abandon the download.
            version = None

        target = destination / f"{dataset.external_id}.csv"
        try:
            downloaded = client.download(dataset.download_url, target, max_bytes=max_bytes)
        except http.TransferError as exc:
            raise Unavailable(str(exc)) from exc
        if downloaded.bytes == 0:
            target.unlink(missing_ok=True)
            raise Unavailable("the Socrata export returned an empty file")

        return Acquired(
            files=(target,),
            bytes=downloaded.bytes,
            sha256=downloaded.sha256,
            file_format=extension_of(target),
            version=version or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            retrieved_from=downloaded.url,
            notes=(
                "Version taken from the Socrata view's rowsUpdatedAt."
                if version
                else "Socrata published no update time for this view, so the version "
                "records the acquisition date."
            ),
        )


CDC_SOCRATA = CdcSocrata(
    code="cdc_socrata",
    label="CDC open data",
    organisation="Centers for Disease Control and Prevention",
    homepage="https://data.cdc.gov",
    hosts=("data.cdc.gov", "api.us.socrata.com"),
    default_config={"queries": list(DEFAULT_QUERIES), "per_query": 15},
)
