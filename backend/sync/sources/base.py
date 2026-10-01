"""What a publisher connector has to provide.

Two methods, kept apart on purpose.

`discover()` asks the publisher what it has. It reads catalogues and project pages, and it
downloads no dataset files, so a discovery pass is cheap enough to run on a schedule and
safe to run against a publisher whose licences have not been reviewed. What it returns is
the publisher's description of a dataset, including the publisher's own words about
access and licensing — never this module's opinion of them.

`fetch()` obtains the bytes for one dataset, and is called only after `app.sync.licensing`
has agreed that both the access gate and the licence gate are open. It writes into the
directory it is handed and returns what arrived.

A connector never decides whether it is allowed to download. It reports what the publisher
says and does what it is told, which keeps the access policy in one readable place instead
of spread across four adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backend.sync import http
from database.models import Granularity, SourceAccess

#: Dataset shapes these publishers hand out. `AGGREGATE_STATISTICS` exists because most of
#: what WHO and CDC publish is counts per country-week, not records per person, and calling
#: that a "clinical dataset" would misdescribe it to everything downstream.
AGGREGATE_STATISTICS = "aggregate_statistics"
CASE_SURVEILLANCE = "case_surveillance"
CLINICAL_RECORDS = "clinical_records"
PHYSIOLOGICAL_SIGNALS = "physiological_signals"
IMAGING = "imaging"
TEXT_CORPUS = "text_corpus"
SOURCE_CODE = "source_code"
UNKNOWN_TYPE = "unknown"


@dataclass(frozen=True)
class RemoteDataset:
    """One dataset as the publisher currently describes it.

    Every field here is either read from the publisher's response or derived from it by
    the adapter. Nothing in this object reflects a decision made by this platform; those
    live on the `ExternalDataset` row.
    """

    external_id: str
    name: str
    source_url: str
    description: str = ""
    download_url: str | None = None
    download_mechanism: str = ""
    dataset_type: str = UNKNOWN_TYPE
    granularity: Granularity = Granularity.UNKNOWN
    modalities: tuple[str, ...] = ()
    target_labels: tuple[str, ...] = ()
    access_status: SourceAccess = SourceAccess.UNKNOWN
    licence: str | None = None
    licence_url: str | None = None
    publisher_version: str | None = None
    publisher_updated_at: datetime | None = None
    records_claimed: int | None = None
    bytes_claimed: int | None = None
    relevance: int = 0
    notes: str = ""

    def fingerprint_fields(self) -> dict:
        """The publisher-stated facts whose change means "this listing was revised".

        Deliberately excludes anything this platform computes, and excludes volatile
        popularity counters such as download totals, which would otherwise make every
        Kaggle dataset look freshly changed on every pass.
        """
        return {
            "external_id": self.external_id,
            "name": self.name,
            "description": self.description,
            "download_url": self.download_url,
            "licence": self.licence,
            "access_status": self.access_status.value,
            "publisher_version": self.publisher_version,
            "publisher_updated_at": (
                self.publisher_updated_at.isoformat() if self.publisher_updated_at else None
            ),
            "records_claimed": self.records_claimed,
            "bytes_claimed": self.bytes_claimed,
        }

    @property
    def search_text(self) -> str:
        return f"{self.name} {self.description}"


@dataclass(frozen=True)
class Acquired:
    """What arrived, measured rather than asserted."""

    files: tuple[Path, ...]
    bytes: int
    sha256: str
    file_format: str
    version: str
    retrieved_from: str
    notes: str = ""


class Unavailable(RuntimeError):
    """The publisher could not be reached, or did not serve what it advertised."""


@dataclass
class Connector:
    code: str
    label: str
    organisation: str
    homepage: str
    hosts: tuple[str, ...]
    #: Defaults written into the `external_sources` row the first time it is created. A
    #: deployment edits the row; the code is not the place to configure a search.
    default_config: dict = field(default_factory=dict)
    #: True when the publisher needs credentials for part of what this connector does. The
    #: connector still works without them, with a narrower reach.
    uses_credentials: bool = False

    def client(self, **kwargs) -> http.Client:
        return http.Client(allowed_hosts=self.hosts, **kwargs)

    def discover(self, config: dict) -> list[RemoteDataset]:
        raise NotImplementedError

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        raise NotImplementedError


def extension_of(path: Path) -> str:
    return path.suffix.lower().lstrip(".")[:16]


def dominant_format(files: tuple[Path, ...]) -> str:
    """The format to label a multi-file dataset with: the extension carrying the most bytes.

    A CSV dataset shipped with a README and a licence file should read as `csv`, not as
    whichever file happens to sort first.
    """
    weights: dict[str, int] = {}
    for path in files:
        if path.is_file():
            weights[extension_of(path)] = weights.get(extension_of(path), 0) + path.stat().st_size
    if not weights:
        return ""
    return max(weights.items(), key=lambda item: item[1])[0]
