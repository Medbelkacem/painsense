"""The dataset registry: one entry per dataset this pipeline knows about.

An entry exists from the moment a dataset is *considered*, not from the moment it is
obtained. A dataset whose publisher requires a signed agreement, or whose series is only
published as a PDF bulletin, therefore appears in the registry with its real access status
and the procedure a person would have to follow, rather than being quietly absent.

Two fields carry the weight here:

`access_status` is what the publisher permits. `availability` is what this pipeline
actually has on disk. They are different questions and conflating them is how a dashboard
ends up claiming a dataset it never downloaded.

Counts follow the same rule as the pain pipeline next door: `records` is a measurement
taken from the file when the file exists, and `records_claimed` is the publisher's stated
figure when it does not. The two never overwrite each other.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.epidemic import paths
from backend.epidemic.diseases import DATASET_TYPES

# What the publisher permits.
ACCESS_OPEN = "open"
ACCESS_REGISTRATION = "registration_required"
ACCESS_CREDENTIALED = "credentialed"
ACCESS_AGREEMENT = "agreement_required"
ACCESS_DOCUMENT_ONLY = "document_only"
ACCESS_UNKNOWN = "unknown"

ACCESS_STATUSES = (
    ACCESS_OPEN,
    ACCESS_REGISTRATION,
    ACCESS_CREDENTIALED,
    ACCESS_AGREEMENT,
    ACCESS_DOCUMENT_ONLY,
    ACCESS_UNKNOWN,
)

# What this pipeline holds.
AVAILABLE = "available"
UNAVAILABLE = "unavailable"
MANUAL_IMPORT_REQUIRED = "manual_import_required"
NOT_ATTEMPTED = "not_attempted"
FAILED = "acquisition_failed"

AVAILABILITY = (AVAILABLE, UNAVAILABLE, MANUAL_IMPORT_REQUIRED, NOT_ATTEMPTED, FAILED)

# Outcome of the validation pass.
QUALITY_PASSED = "passed"
QUALITY_WARNINGS = "passed_with_warnings"
QUALITY_FAILED = "failed"
QUALITY_UNKNOWN = "not_assessed"

QUALITY_STATUSES = (QUALITY_PASSED, QUALITY_WARNINGS, QUALITY_FAILED, QUALITY_UNKNOWN)

REGISTRY_PATH_NAME = "dataset_registry.json"
LICENCE_PATH_NAME = "licenses.json"
ACQUISITION_LOG_NAME = "acquisition_log.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Entry:
    dataset_id: str
    name: str
    diseases: list[str]
    dataset_type: str
    source: str
    source_url: str
    access_status: str = ACCESS_UNKNOWN
    availability: str = NOT_ATTEMPTED

    download_url: str | None = None
    download_mechanism: str = ""
    license: str | None = None
    license_url: str | None = None
    redistribution: str = "unknown"

    file_format: str | None = None
    version: str | None = None
    downloaded_at: str | None = None
    source_last_updated: str | None = None
    raw_path: str | None = None
    processed_path: str | None = None
    bytes: int | None = None
    sha256: str | None = None

    records: int | None = None
    records_claimed: int | None = None
    columns: int | None = None
    features: list[str] = field(default_factory=list)
    target_labels: list[str] = field(default_factory=list)
    missing_value_pct: float | None = None
    quality_status: str = QUALITY_UNKNOWN
    quality_findings: list[str] = field(default_factory=list)

    trainable: bool = False
    access_procedure: str = ""
    error: str | None = None
    notes: str = ""
    checked_at: str = field(default_factory=now)

    def __post_init__(self) -> None:
        if self.dataset_type not in DATASET_TYPES:
            raise ValueError(f"unknown dataset type {self.dataset_type!r}")
        if self.access_status not in ACCESS_STATUSES:
            raise ValueError(f"unknown access status {self.access_status!r}")
        if self.availability not in AVAILABILITY:
            raise ValueError(f"unknown availability {self.availability!r}")
        if self.quality_status not in QUALITY_STATUSES:
            raise ValueError(f"unknown quality status {self.quality_status!r}")

    @property
    def record_count(self) -> int | None:
        """The measured count where there is one, otherwise the publisher's figure."""
        return self.records if self.records is not None else self.records_claimed

    @property
    def record_count_is_measured(self) -> bool:
        return self.records is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


FIELD_NAMES = tuple(f.name for f in fields(Entry))


def _registry_path() -> Path:
    return paths.metadata(REGISTRY_PATH_NAME)


def _read(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write(path: Path, payload: Any) -> None:
    paths.ensure(path.parent)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load() -> list[Entry]:
    rows = _read(_registry_path(), [])
    if not isinstance(rows, list):
        return []
    entries = []
    for row in rows:
        known = {key: value for key, value in row.items() if key in FIELD_NAMES}
        try:
            entries.append(Entry(**known))
        except (TypeError, ValueError):
            continue
    return entries


def load_dict() -> dict[str, Entry]:
    return {entry.dataset_id: entry for entry in load()}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)


def upsert(incoming: Iterable[Entry]) -> list[Entry]:
    """Merge entries into the registry, preserving what the caller did not measure.

    A discovery run knows the licence and the access status but not the row count; a
    download run knows the checksum; a validation run knows the quality findings. Each
    writes what it established and leaves the rest alone, so running one step does not
    erase what another step found. A field the caller did set wins, including a reset to a
    default like `quality_status=not_assessed`, because re-running validation on a changed
    file has to be able to clear the previous verdict.
    """
    existing = load_dict()
    for entry in incoming:
        current = existing.get(entry.dataset_id)
        if current is None:
            existing[entry.dataset_id] = entry
            continue
        merged = current.as_dict()
        for name, value in entry.as_dict().items():
            if _is_empty(value) and not _is_empty(merged.get(name)):
                continue
            merged[name] = value
        existing[entry.dataset_id] = Entry(**merged)
    ordered = [existing[key] for key in sorted(existing)]
    _write(_registry_path(), [entry.as_dict() for entry in ordered])
    return ordered


def get(dataset_id: str) -> Entry | None:
    return load_dict().get(dataset_id)


def for_disease(code: str) -> list[Entry]:
    return [entry for entry in load() if code in entry.diseases]


def record_licence(entry: Entry) -> None:
    index = _read(paths.metadata(LICENCE_PATH_NAME), {})
    if not isinstance(index, dict):
        index = {}
    index[entry.dataset_id] = {
        "dataset_id": entry.dataset_id,
        "name": entry.name,
        "license": entry.license,
        "license_url": entry.license_url,
        "source": entry.source,
        "source_url": entry.source_url,
        "redistribution": entry.redistribution,
        "access_status": entry.access_status,
        "recorded_at": now(),
    }
    _write(paths.metadata(LICENCE_PATH_NAME), dict(sorted(index.items())))


def log_acquisition(record: dict[str, Any]) -> None:
    """Append one acquisition attempt, successful or not.

    This is the audit trail for section 10 of the brief: every attempt is recorded with
    its outcome, so a dataset that is missing from `raw/` has a reason on file rather than
    simply not being there.
    """
    path = paths.metadata(ACQUISITION_LOG_NAME)
    log = _read(path, [])
    if not isinstance(log, list):
        log = []
    log.append({"logged_at": now(), **record})
    _write(path, log)


def acquisition_log() -> list[dict[str, Any]]:
    log = _read(paths.metadata(ACQUISITION_LOG_NAME), [])
    return log if isinstance(log, list) else []
