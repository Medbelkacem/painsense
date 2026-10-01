from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from . import checks, registry, schema
from .registry import (
    MERGE_REPORT_PATH,
    MODEL_READY_FILE,
    SCHEMA_DOC_PATH,
    SOURCES_DIR,
    UNIFIED_FILE,
    UNIFIED_PARTITIONED,
    ensure,
)
from .schema import DEFAULT_SEED, SPLIT_NAMES, Encoder, assign, summarise
from .sources import SOURCES, Source

PARTITION_ABOVE = 2_000_000
DATA_SOURCE_CHOICES = ("all", "real", "synthetic")


def _provenance_for(source: Source) -> tuple[str | None, str | None]:
    for record in registry.load_registry():
        local = record.get("local_path")
        if local and Path(local).resolve() == source.root.resolve():
            return record.get("version"), record.get("retrieved_at")
    return None, None


def normalize_source(source: Source, *, out_root: Path) -> dict[str, Any]:
    version, retrieved_at = _provenance_for(source)
    out_dir = ensure(out_root / source.dataset_id)
    records_path = out_dir / "records.parquet"
    features_path = out_dir / "source_features.parquet"

    records_writer: pq.ParquetWriter | None = None
    features_writer: pq.ParquetWriter | None = None
    rows = 0
    with_target = 0
    patients: set[str] = set()
    source_columns: list[str] = []

    try:
        for chunk in source.chunks(version=version, retrieved_at=retrieved_at):
            extra = schema.dropped_columns(chunk)
            conformed = schema.conform(chunk, dataset_id=source.dataset_id)
            rows += len(conformed)
            with_target += int(conformed[schema.TARGET].notna().sum())
            patients.update(conformed["patient_id"].dropna().astype(str))

            table = pa.Table.from_pandas(conformed, preserve_index=False)
            if records_writer is None:
                records_writer = pq.ParquetWriter(records_path, table.schema, compression="zstd")
            records_writer.write_table(table)

            if extra:
                source_columns = extra
                features = chunk[["assessment_id", *extra]].copy()
                features["assessment_id"] = features["assessment_id"].astype("string")
                feature_table = pa.Table.from_pandas(features, preserve_index=False)
                if features_writer is None:
                    features_writer = pq.ParquetWriter(
                        features_path, feature_table.schema, compression="zstd"
                    )
                features_writer.write_table(feature_table)
    finally:
        if records_writer is not None:
            records_writer.close()
        if features_writer is not None:
            features_writer.close()

    report = {
        "dataset_id": source.dataset_id,
        "name": source.name,
        "data_source": source.data_source,
        "source_url": source.source_url,
        "license": source.license,
        "dataset_version": version,
        "retrieved_at": retrieved_at,
        "synthetic": source.synthetic,
        "raw_path": str(source.root),
        "records": rows,
        "patients": len(patients),
        "records_with_nrs_target": with_target,
        "original_pain_scale": source.original_pain_scale,
        "nrs_mapping": source.nrs_mapping or "none",
        "nrs_mapping_reason": source.nrs_mapping_reason,
        "unified_columns": len(schema.FIELDS),
        "source_specific_columns": source_columns,
        "records_path": str(records_path),
        "source_features_path": str(features_path) if source_columns else None,
        "normalized_at": registry.now(),
        "provenance_notes": source.provenance_notes,
    }
    (out_dir / "normalization_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def normalize(
    dataset_ids: list[str] | None = None, out_root: Path = SOURCES_DIR
) -> dict[str, Any]:
    ensure(SCHEMA_DOC_PATH.parent)
    SCHEMA_DOC_PATH.write_text(json.dumps(schema.describe(), indent=2) + "\n", encoding="utf-8")

    reports: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for dataset_id in dataset_ids or list(SOURCES):
        source = SOURCES.get(dataset_id)
        if source is None:
            skipped.append({"dataset_id": dataset_id, "reason": "no normalizer is registered"})
            continue
        if not source.root.exists():
            skipped.append({
                "dataset_id": dataset_id,
                "reason": f"raw data is not present at {source.root}",
            })
            continue
        reports.append(normalize_source(source, out_root=out_root))

    registry.upsert([
        registry.entry(
            report["dataset_id"],
            report["name"],
            report["data_source"],
            report["source_url"],
            "local" if report["synthetic"] else "open",
            license=report["license"],
            version=report["dataset_version"],
            retrieved_at=report["retrieved_at"],
            local_path=report["raw_path"],
            subjects=report["patients"],
            records=report["records"],
            pain_labels=[report["original_pain_scale"]],
            target_available=report["records_with_nrs_target"] > 0,
            notes=(
                f"Normalized to the unified schema: {report['records']:,} record(s), "
                f"{report['records_with_nrs_target']:,} with an NRS target. "
                f"NRS mapping: {report['nrs_mapping']}."
            ),
        )
        for report in reports
    ])

    return {
        "schema_document": str(SCHEMA_DOC_PATH),
        "normalized": [
            {
                "dataset_id": report["dataset_id"],
                "records": report["records"],
                "patients": report["patients"],
                "records_with_nrs_target": report["records_with_nrs_target"],
                "nrs_mapping": report["nrs_mapping"],
                "source_specific_columns": len(report["source_specific_columns"]),
            }
            for report in reports
        ],
        "skipped": skipped,
    }


def normalized_tables(root: Path) -> list[Path]:
    return sorted(root.glob("*/records.parquet"))


def load_unified(tables: list[Path], *, data_source: str) -> pd.DataFrame:
    frames = []
    for path in tables:
        frame = pd.read_parquet(path)
        if data_source == "real":
            frame = frame[frame["synthetic"].eq(False)]
        elif data_source == "synthetic":
            frame = frame[frame["synthetic"].eq(True)]
        if len(frame):
            frames.append(frame)
    if not frames:
        return schema.empty_frame()
    return pd.concat(frames, ignore_index=True)


def write_unified(frame: pd.DataFrame) -> dict[str, Any]:
    ensure(UNIFIED_FILE.parent)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if len(frame) > PARTITION_ABOVE:
        if UNIFIED_FILE.exists():
            UNIFIED_FILE.unlink()
        ds.write_dataset(
            table,
            UNIFIED_PARTITIONED,
            format="parquet",
            partitioning=ds.partitioning(
                pa.schema([("data_source", pa.string())]), flavor="hive"
            ),
            existing_data_behavior="delete_matching",
            basename_template="part-{i}.parquet",
        )
        return {
            "layout": "partitioned",
            "path": str(UNIFIED_PARTITIONED),
            "partitioned_on": "data_source",
            "reason": (
                f"{len(frame):,} rows exceeds the {PARTITION_ABOVE:,} row single-file threshold"
            ),
        }
    pq.write_table(table, UNIFIED_FILE, compression="zstd")
    return {
        "layout": "single_file",
        "path": str(UNIFIED_FILE),
        "reason": f"{len(frame):,} rows is within the {PARTITION_ABOVE:,} row single-file threshold",
    }


def build_model_ready(frame: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    assigned = frame[frame["patient_id"].notna()].copy()
    dropped = len(frame) - len(assigned)
    splits, split_description = assign(assigned, seed=seed)
    assigned["split"] = splits
    split_description["records_dropped_without_patient_id"] = dropped

    patient_findings = checks.audit_dataset(assigned)
    if checks.has_blocking(patient_findings):
        raise SystemExit(
            "patient-level split failed its own leakage check:\n"
            + "\n".join(f"  - {item['detail']}" for item in patient_findings)
        )

    encoder = Encoder().fit(assigned[assigned["split"] == "train"])
    encoded = encoder.transform(assigned)
    feature_columns = encoder.feature_columns(encoded)

    feature_findings = checks.audit_features(encoded, feature_columns)
    if checks.has_blocking(feature_findings):
        raise SystemExit(
            "the encoded feature matrix leaks the target:\n"
            + "\n".join(f"  - {item['detail']}" for item in feature_findings)
        )

    ensure(MODEL_READY_FILE.parent)
    pq.write_table(
        pa.Table.from_pandas(encoded, preserve_index=False), MODEL_READY_FILE, compression="zstd"
    )
    written = {
        name: {"records": int((encoded["split"] == name).sum())} for name in SPLIT_NAMES
    }

    return {
        "model_ready_path": str(MODEL_READY_FILE),
        "splits": written,
        "feature_count": len(feature_columns),
        "split": split_description,
        "split_summary": summarise(assigned),
        "encoding": encoder.describe(),
        "patient_leakage_findings": patient_findings,
        "target_leakage_findings": feature_findings,
    }


def _write_merge_report(report: dict[str, Any]) -> None:
    ensure(MERGE_REPORT_PATH.parent)
    MERGE_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def merge(
    *, data_source: str = "all", seed: int = DEFAULT_SEED, sources_root: Path = SOURCES_DIR
) -> dict[str, Any]:
    tables = normalized_tables(sources_root)
    if not tables:
        report = {
            "generated_at": registry.now(),
            "status": "no_input",
            "reason": (
                f"no normalized records under {sources_root}; run the normalize step first"
            ),
        }
        _write_merge_report(report)
        return report

    unified = load_unified(tables, data_source=data_source)
    if unified.empty:
        report = {
            "generated_at": registry.now(),
            "status": "no_matching_records",
            "data_source_filter": data_source,
            "inputs": [str(path) for path in tables],
        }
        _write_merge_report(report)
        return report

    unified_info = write_unified(unified)
    model_ready = build_model_ready(unified, seed=seed)

    report = {
        "generated_at": registry.now(),
        "status": "ok",
        "data_source_filter": data_source,
        "inputs": [str(path) for path in tables],
        "records": len(unified),
        "patients": int(unified["patient_id"].nunique()),
        "sources": sorted(unified["dataset_id"].dropna().unique().tolist()),
        "records_with_nrs_target": int(unified[schema.TARGET].notna().sum()),
        "unified": unified_info,
        **model_ready,
    }
    _write_merge_report(report)

    return {
        "status": report["status"],
        "records": report["records"],
        "patients": report["patients"],
        "records_with_nrs_target": report["records_with_nrs_target"],
        "unified": unified_info,
        "feature_count": report["feature_count"],
        "splits": {name: item["records"] for name, item in report["splits"].items()},
        "split_summary": report["split_summary"],
        "target_leakage_findings": len(report["target_leakage_findings"]),
        "patient_leakage_findings": len(report["patient_leakage_findings"]),
    }
