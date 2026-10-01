"""What a source adapter has to provide.

Each adapter answers three separate questions, and keeping them separate is the point:

`declare()` is what the publisher says about the dataset — who publishes it, under what
terms, by what mechanism. It makes no network call, so the registry can be rebuilt and
read with no connectivity at all.

`probe()` asks whether the resource is reachable right now, and reads back whatever the
response says about the licence and the last update. It downloads nothing.

`fetch()` obtains the bytes. It writes under `raw/<source>/<dataset_id>/` and returns the
size and digest of what arrived. `normalize()` then reads that directory and maps it onto
the surveillance schema; it never touches the network, so normalization is reproducible
from `raw/` alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

from backend.epidemic import net, paths, registry
from backend.epidemic.diseases import SURVEILLANCE


@dataclass(frozen=True)
class Probe:
    reachable: bool
    detail: str
    status: int | None = None
    source_last_updated: str | None = None
    license: str | None = None
    license_url: str | None = None
    records_claimed: int | None = None
    bytes_available: int | None = None


@dataclass(frozen=True)
class Fetched:
    files: tuple[Path, ...]
    bytes: int
    sha256: str
    file_format: str
    version: str | None = None
    source_last_updated: str | None = None
    records: int | None = None


class Refused(RuntimeError):
    """The adapter declined to fetch, and the reason belongs in the registry.

    Raised for a licence that has not been reviewed and for a resource the publisher does
    not serve through a data interface. Both are states to record, not errors to retry.
    """


def http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def epoch_to_iso(value: object) -> str | None:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Source:
    dataset_id: str
    name: str
    diseases: tuple[str, ...]
    organisation: str
    source_url: str
    download_url: str | None = None
    download_mechanism: str = ""
    dataset_type: str = SURVEILLANCE
    file_format: str | None = None
    license: str | None = None
    license_url: str | None = None
    license_source: str = ""
    redistribution: str = "not redistributed by this pipeline"
    access_status: str = registry.ACCESS_OPEN
    access_procedure: str = ""
    license_review_required: bool = False
    records_claimed: int | None = None
    features: tuple[str, ...] = ()
    target_labels: tuple[str, ...] = ()
    notes: str = ""
    metrics: tuple[str, ...] = field(default=())

    # --- declaration -----------------------------------------------------------------

    @property
    def source_slug(self) -> str:
        return self.organisation.lower().replace(" ", "_").replace("/", "_")

    def raw_dir(self) -> Path:
        return paths.raw(self.source_slug, self.dataset_id)

    def declare(self) -> registry.Entry:
        return registry.Entry(
            dataset_id=self.dataset_id,
            name=self.name,
            diseases=list(self.diseases),
            dataset_type=self.dataset_type,
            source=self.organisation,
            source_url=self.source_url,
            access_status=self.access_status,
            download_url=self.download_url,
            download_mechanism=self.download_mechanism,
            license=self.license,
            license_url=self.license_url,
            redistribution=self.redistribution,
            file_format=self.file_format,
            features=list(self.features),
            target_labels=list(self.target_labels),
            access_procedure=self.access_procedure,
            notes=self.notes,
        )

    # --- availability ----------------------------------------------------------------

    def probe(self) -> Probe:
        """Default probe: a conditional read of the download URL's headers."""
        if not self.download_url:
            return Probe(False, "no download URL is published for this resource")
        try:
            headers = net.head(self.download_url)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        length = headers.get("content-length")
        return Probe(
            True,
            f"HTTP {headers.get('status')} {headers.get('content-type', 'unknown type')}",
            status=int(headers.get("status", 0)) or None,
            source_last_updated=http_date(headers.get("last-modified")),
            bytes_available=int(length) if length and length.isdigit() else None,
        )

    # --- acquisition -----------------------------------------------------------------

    def fetch(self) -> Fetched:
        raise NotImplementedError

    def normalize(self) -> pd.DataFrame | None:
        """Map what is in `raw_dir()` onto the surveillance schema.

        Returns None for a source that carries no surveillance series — the patient-level
        COVID file is handled by `app.epidemic.clinical` instead.
        """
        return None
