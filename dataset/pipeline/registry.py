from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = DATASET_ROOT / "raw"
SOURCES_DIR = DATASET_ROOT / "sources"
METADATA_DIR = DATASET_ROOT / "metadata"
PROFILE_DIR = METADATA_DIR / "profiles"
REPORTS_DIR = DATASET_ROOT / "reports"

UNIFIED_FILE = DATASET_ROOT / "dataset.parquet"
UNIFIED_PARTITIONED = DATASET_ROOT / "by_source"
MODEL_READY_FILE = DATASET_ROOT / "model_ready.parquet"

REGISTRY_PATH = METADATA_DIR / "dataset_registry.json"
LICENCE_PATH = METADATA_DIR / "licenses.json"
DOWNLOAD_LOG_PATH = METADATA_DIR / "download_log.json"
MANIFEST_PATH = METADATA_DIR / "source_manifest.json"
KAGGLE_CATALOG_PATH = METADATA_DIR / "kaggle_catalog.json"
PHYSIONET_ACCESS_REPORT = METADATA_DIR / "physionet_access_report.json"
BIOVID_ACCESS_REPORT = METADATA_DIR / "biovid_access_report.json"
TAME_PAIN_ACCESS_REPORT = METADATA_DIR / "tame_pain_access_report.json"
PIPELINE_RUN_REPORT = METADATA_DIR / "pipeline_run.json"
MERGE_REPORT_PATH = METADATA_DIR / "merge_report.json"
SCHEMA_DOC_PATH = METADATA_DIR / "normalized_schema.json"
VALIDATION_REPORT_PATH = METADATA_DIR / "dataset_validation_report.json"
LEAKAGE_REPORT_PATH = METADATA_DIR / "dataset_leakage_report.json"
STATISTICS_REPORT_PATH = METADATA_DIR / "dataset_statistics.json"

ACCESS_STATUSES = {
    "open",
    "registration_required",
    "credentialed",
    "restricted",
    "request_required",
    "unavailable",
    "local",
    "unknown",
}

ENTRY_FIELDS = (
    "dataset_id",
    "name",
    "source",
    "source_url",
    "download_url",
    "access_status",
    "license",
    "version",
    "retrieved_at",
    "local_path",
    "modalities",
    "subjects",
    "records",
    "pain_labels",
    "target_available",
    "notes",
)


def ensure(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def entry(
    dataset_id: str,
    name: str,
    source: str,
    source_url: str,
    access_status: str,
    *,
    download_url: str | None = None,
    license: str | None = None,
    version: str | None = None,
    retrieved_at: str | None = None,
    local_path: str | None = None,
    modalities: list[str] | None = None,
    subjects: int | None = None,
    records: int | None = None,
    pain_labels: list[str] | None = None,
    target_available: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    if access_status not in ACCESS_STATUSES:
        raise ValueError(f"unknown access status {access_status!r}")
    return {
        "dataset_id": dataset_id,
        "name": name,
        "source": source,
        "source_url": source_url,
        "download_url": download_url,
        "access_status": access_status,
        "license": license,
        "version": version,
        "retrieved_at": retrieved_at,
        "local_path": local_path,
        "modalities": modalities or [],
        "subjects": subjects,
        "records": records,
        "pain_labels": pain_labels or [],
        "target_available": target_available,
        "notes": notes,
    }


def _read(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write(path: Path, payload: Any) -> None:
    ensure(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_registry() -> list[dict[str, Any]]:
    records = _read(REGISTRY_PATH, [])
    return records if isinstance(records, list) else []


def _is_unknown(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)


def upsert(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {record["dataset_id"]: record for record in load_registry()}
    for incoming in entries:
        dataset_id = incoming["dataset_id"]
        current = existing.get(dataset_id)
        if current is None:
            existing[dataset_id] = dict(incoming)
            continue
        for field in ENTRY_FIELDS:
            value = incoming.get(field)
            if _is_unknown(value) and not _is_unknown(current.get(field)):
                continue
            current[field] = value
    merged = [existing[key] for key in sorted(existing)]
    _write(REGISTRY_PATH, merged)
    return merged


def write_manifest(source: str, entries: list[dict[str, Any]]) -> None:
    manifest = _read(MANIFEST_PATH, {})
    if not isinstance(manifest, dict) or "sources" not in manifest:
        manifest = {"generated_at": now(), "sources": {}}
    manifest["generated_at"] = now()
    manifest["sources"][source] = {"discovered_at": now(), "entries": entries}
    _write(MANIFEST_PATH, manifest)


def record_licence(
    dataset_id: str,
    *,
    name: str,
    license: str | None,
    license_url: str | None,
    source_url: str,
    redistribution: str,
    notes: str = "",
) -> None:
    index = _read(LICENCE_PATH, {})
    if not isinstance(index, dict):
        index = {}
    index[dataset_id] = {
        "dataset_id": dataset_id,
        "name": name,
        "license": license,
        "license_url": license_url,
        "source_url": source_url,
        "redistribution": redistribution,
        "recorded_at": now(),
        "notes": notes,
    }
    _write(LICENCE_PATH, dict(sorted(index.items())))


def log_download(record: dict[str, Any]) -> None:
    log = _read(DOWNLOAD_LOG_PATH, [])
    if not isinstance(log, list):
        log = []
    log.append({"logged_at": now(), **record})
    _write(DOWNLOAD_LOG_PATH, log)


def load_download_log() -> list[dict[str, Any]]:
    log = _read(DOWNLOAD_LOG_PATH, [])
    return log if isinstance(log, list) else []


def entries_from_download_log() -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in load_download_log():
        if record.get("status") == "downloaded":
            latest[record["dataset_id"]] = record

    from .sources import dataset_id_for_reference

    entries: list[dict[str, Any]] = []
    for reference, record in sorted(latest.items()):
        slug = reference.replace("/", "_").replace("-", "_")
        dataset_id = dataset_id_for_reference(reference) or (
            f"{record.get('source', 'unknown')}_{slug}"
        )
        entries.append(
            entry(
                dataset_id,
                reference,
                (record.get("source") or "unknown").title(),
                record.get("source_url") or "",
                "open",
                download_url=record.get("download_url"),
                license=record.get("license"),
                version=str(record["dataset_version"]) if record.get("dataset_version") else None,
                retrieved_at=record.get("downloaded_at"),
                local_path=record.get("local_path"),
                notes=(
                    f"Archive sha256 {str(record.get('archive_sha256'))[:16]}, "
                    f"{record.get('file_count')} file(s) extracted."
                ),
            )
        )
    return entries
