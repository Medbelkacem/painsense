from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from . import registry
from .registry import PROFILE_DIR, ensure
from .sources import SOURCES

TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".json", ".jsonl", ".xlsx", ".xls"}
SIGNAL_SUFFIXES = {".wav", ".edf", ".dat", ".hea", ".mat", ".npy", ".flac"}

SUBJECT_COLUMN_HINTS = (
    "patient_id", "subject_id", "person_id", "participant_id", "subject", "patient",
    "person_id", "id_patient", "pid", "record_id", "case_id",
)
LABEL_COLUMN_HINTS = (
    "pain", "nrs", "vas", "intensity", "severity", "class_value", "class_label",
    "target", "label", "score",
)
TIMESTAMP_COLUMN_HINTS = ("timestamp", "time", "date", "datetime", "recorded_at")

MAX_CATEGORY_LEVELS = 25

MIN_UNIFORMITY_SAMPLE = 50
MAX_UNIFORMITY_SAMPLE = 5_000
UNIFORMITY_SIMULATIONS = 400
UNIFORMITY_SEED = 20260101


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".jsonl":
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"no reader for {path.suffix!r}")


def find_column(columns: list[str], hints: tuple[str, ...]) -> str | None:
    normalised = {_norm(column): column for column in columns}
    for hint in hints:
        if hint in normalised:
            return normalised[hint]
        for key, original in normalised.items():
            if hint in key:
                return original
    return None


def _scaled_ks(sample: np.ndarray) -> float:
    low, high = float(sample.min()), float(sample.max())
    if high <= low:
        return 0.0
    return float(stats.kstest((sample - low) / (high - low), "uniform").statistic)


@lru_cache(maxsize=32)
def _uniformity_critical_value(size: int) -> float:
    rng = np.random.default_rng(UNIFORMITY_SEED)
    statistics = [
        _scaled_ks(rng.uniform(0.0, 1.0, size)) for _ in range(UNIFORMITY_SIMULATIONS)
    ]
    return float(np.quantile(statistics, 0.95))


def uniformity(values: pd.Series) -> dict[str, Any] | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if len(numeric) < MIN_UNIFORMITY_SAMPLE or numeric.nunique() < 20:
        return None
    array = numeric.to_numpy(dtype=float)
    if len(array) > MAX_UNIFORMITY_SAMPLE:
        rng = np.random.default_rng(UNIFORMITY_SEED)
        array = rng.choice(array, MAX_UNIFORMITY_SAMPLE, replace=False)
    if array.max() <= array.min():
        return None

    statistic = _scaled_ks(array)
    critical = _uniformity_critical_value(len(array))
    return {
        "method": (
            "Kolmogorov-Smirnov distance from uniform after scaling onto the observed range, "
            "compared against a simulated null distribution for this sample size"
        ),
        "sample_size": len(array),
        "ks_statistic": round(statistic, 4),
        "critical_value_95": round(critical, 4),
        "consistent_with_uniform": bool(statistic <= critical),
    }


def profile_column(series: pd.Series) -> dict[str, Any]:
    total = len(series)
    if series.map(lambda value: isinstance(value, (list, dict, set))).any():
        return {
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "missing": int(total - series.notna().sum()),
            "note": "nested values; not summarised further",
        }
    missing = int(series.isna().sum())
    summary: dict[str, Any] = {
        "dtype": str(series.dtype),
        "non_null": total - missing,
        "missing": missing,
        "missing_fraction": round(missing / total, 6) if total else None,
        "unique": int(series.nunique(dropna=True)),
    }
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() and not pd.api.types.is_bool_dtype(series):
        summary["min"] = float(numeric.min())
        summary["max"] = float(numeric.max())
        summary["mean"] = round(float(numeric.mean()), 6)
        summary["std"] = round(float(numeric.std()), 6) if numeric.notna().sum() > 1 else None
        verdict = uniformity(series)
        if verdict:
            summary["uniformity_test"] = verdict
    if summary["unique"] <= MAX_CATEGORY_LEVELS:
        counts = series.value_counts(dropna=True)
        summary["value_counts"] = {str(k): int(v) for k, v in counts.items()}
    return summary


def _duplicate_rows(frame: pd.DataFrame) -> tuple[int | None, list[str]]:
    unhashable = [
        str(name) for name in frame.columns
        if frame[name].map(lambda value: isinstance(value, (list, dict, set))).any()
    ]
    comparable = frame.drop(columns=unhashable)
    if comparable.empty or not len(comparable.columns):
        return None, unhashable
    return int(comparable.duplicated().sum()), unhashable


def profile_table(frame: pd.DataFrame, *, source_path: str) -> dict[str, Any]:
    columns = list(frame.columns)
    subject_column = find_column(columns, SUBJECT_COLUMN_HINTS)
    label_column = find_column(columns, LABEL_COLUMN_HINTS)
    timestamp_column = find_column(columns, TIMESTAMP_COLUMN_HINTS)
    duplicate_rows, unhashable = _duplicate_rows(frame)

    profile: dict[str, Any] = {
        "file": source_path,
        "records": len(frame),
        "column_count": len(columns),
        "columns": columns,
        "duplicate_rows": duplicate_rows,
        "columns_excluded_from_duplicate_check": unhashable,
        "subject_column": subject_column,
        "subjects": int(frame[subject_column].nunique()) if subject_column else None,
        "repeated_measures": None,
        "timestamp_column": timestamp_column,
        "label_column": label_column,
        "column_profiles": {name: profile_column(frame[name]) for name in columns},
    }
    if subject_column:
        per_subject = frame.groupby(subject_column, dropna=True).size()
        profile["repeated_measures"] = bool((per_subject > 1).any())
        profile["records_per_subject"] = {
            "min": int(per_subject.min()),
            "max": int(per_subject.max()),
            "mean": round(float(per_subject.mean()), 3),
        }
        profile["duplicate_subject_ids"] = int((per_subject > 1).sum())
    if label_column:
        counts = frame[label_column].value_counts(dropna=True)
        profile["label_distribution"] = (
            {str(k): int(v) for k, v in counts.items()} if len(counts) <= MAX_CATEGORY_LEVELS
            else {"levels": len(counts), "note": "too many levels to enumerate"}
        )
    return profile


def profile_dataset(root: Path, *, dataset_id: str) -> dict[str, Any]:
    if not root.exists():
        return {
            "dataset_id": dataset_id,
            "path": str(root),
            "exists": False,
            "has_tabular_data": False,
            "notes": "The path does not exist locally; nothing was profiled.",
        }

    files = sorted(path for path in root.rglob("*") if path.is_file())
    by_suffix: dict[str, int] = {}
    for path in files:
        suffix = path.suffix.lower() or "(none)"
        by_suffix[suffix] = by_suffix.get(suffix, 0) + 1

    tables: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    documents: list[dict[str, str]] = []
    for path in files:
        if path.suffix.lower() not in TABULAR_SUFFIXES:
            continue
        relative = str(path.relative_to(root))
        try:
            frame = read_table(path)
        except Exception as exc:  # noqa: BLE001 - a profile reports every unreadable file
            record = {"file": relative, "error": f"{type(exc).__name__}: {exc}"}
            (documents if path.suffix.lower() == ".json" else unreadable).append(record)
            continue
        tables.append(profile_table(frame, source_path=relative))

    signal_files = [p for p in files if p.suffix.lower() in SIGNAL_SUFFIXES]
    return {
        "dataset_id": dataset_id,
        "path": str(root),
        "exists": True,
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "files_by_suffix": dict(sorted(by_suffix.items())),
        "has_tabular_data": bool(tables),
        "tables": tables,
        "unreadable_files": unreadable,
        "non_tabular_documents": documents,
        "signal_files": len(signal_files),
        "sampling_rate_hz": None,
        "sampling_rate_note": (
            "Sampling rate is only reported when a file header states it; none of the "
            "profiled files carried a header this profiler reads."
        ),
        "records_by_table": {table["file"]: table["records"] for table in tables},
        "records_total_across_tables": sum(table["records"] for table in tables),
        "record_count_note": (
            "records_total_across_tables adds every table in the directory. For a dataset "
            "whose tables are separate entities, or whose splits restate the same rows, that "
            "total is not the dataset's record count; read records_by_table instead."
        ) if len(tables) > 1 else None,
        "records": tables[0]["records"] if len(tables) == 1 else None,
        "subjects": max((table["subjects"] or 0 for table in tables), default=0) or None,
    }


def to_markdown(profile: dict[str, Any]) -> str:
    lines = [f"# Dataset profile: {profile['dataset_id']}", ""]
    if not profile.get("exists"):
        lines += [f"Path `{profile['path']}` does not exist locally. Nothing was profiled.", ""]
        return "\n".join(lines)

    lines += [
        f"- Path: `{profile['path']}`",
        f"- Files: {profile['file_count']} ({profile['total_bytes']:,} bytes)",
        f"- File types: {', '.join(f'{k} x{v}' for k, v in profile['files_by_suffix'].items())}",
        f"- Machine-readable tables: {len(profile['tables'])}",
        f"- Records: {profile['records']:,}" if profile.get("records") is not None
        else "- Records by table: "
        + ", ".join(f"{k} = {v:,}" for k, v in profile["records_by_table"].items()),
        f"- Subjects: {profile['subjects'] if profile['subjects'] else 'no subject column found'}",
        "",
    ]
    if profile.get("record_count_note"):
        lines += [profile["record_count_note"], ""]
    if profile.get("non_tabular_documents"):
        lines += ["## Non-tabular documents", ""]
        lines += [f"- `{item['file']}`" for item in profile["non_tabular_documents"]]
        lines.append("")
    if profile["unreadable_files"]:
        lines += ["## Unreadable files", ""]
        lines += [f"- `{item['file']}`: {item['error']}" for item in profile["unreadable_files"]]
        lines.append("")
    if not profile["has_tabular_data"]:
        lines += [
            "## No tabular data",
            "",
            "The dataset directory holds no machine-readable table, so no records could be",
            "extracted from it. It is registered with `records: null`.",
            "",
        ]
    for table in profile["tables"]:
        lines += [
            f"## `{table['file']}`",
            "",
            f"- Records: {table['records']:,}",
            f"- Columns: {table['column_count']}",
            f"- Duplicate rows: {table['duplicate_rows']}",
            f"- Subject column: {table['subject_column'] or 'none found'}",
            f"- Subjects: {table['subjects'] if table['subjects'] is not None else 'n/a'}",
            f"- Repeated measures per subject: {table['repeated_measures']}",
            f"- Timestamp column: {table['timestamp_column'] or 'none found'}",
            f"- Label column: {table['label_column'] or 'none found'}",
            "",
            "| column | dtype | non-null | missing | unique | min | max | mean |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for name, column in table["column_profiles"].items():
            lines.append(
                f"| `{name}` | {column['dtype']} | {column['non_null']} | {column['missing']} | "
                f"{column.get('unique', '')} | {column.get('min', '')} | {column.get('max', '')} | "
                f"{column.get('mean', '')} |"
            )
        lines.append("")
        flagged = [
            name for name, column in table["column_profiles"].items()
            if column.get("uniformity_test", {}).get("consistent_with_uniform")
        ]
        if flagged:
            lines += [
                ("Columns indistinguishable from a uniform distribution over their own range "
                f"(Kolmogorov-Smirnov, p > 0.05): {', '.join(f'`{n}`' for n in flagged)}."),
                "",
            ]
    return "\n".join(lines)


def write_profile(root: Path, dataset_id: str, out_dir: Path) -> dict[str, Any]:
    profile = profile_dataset(root, dataset_id=dataset_id)
    ensure(out_dir)
    (out_dir / f"{dataset_id}.json").write_text(
        json.dumps(profile, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / f"{dataset_id}.md").write_text(to_markdown(profile), encoding="utf-8")
    return profile


def profile_targets() -> list[tuple[str, Path]]:
    found: dict[str, Path] = {
        source.dataset_id: source.root for source in SOURCES.values() if source.root.exists()
    }
    claimed = {path.resolve() for path in found.values()}
    for record in registry.load_download_log():
        if record.get("status") != "downloaded" or not record.get("local_path"):
            continue
        path = Path(record["local_path"])
        if not path.exists() or path.resolve() in claimed:
            continue
        key = f"{record.get('source', 'unknown')}_{record['dataset_id']}"
        found[key.replace("/", "_").replace("-", "_")] = path
        claimed.add(path.resolve())
    return sorted(found.items())


def register_measurements(dataset_id: str, profile: dict[str, Any]) -> None:
    registry.upsert([
        registry.entry(
            dataset_id,
            dataset_id,
            "unknown",
            "",
            "unknown",
            local_path=profile.get("path") if profile.get("exists") else None,
            records=profile.get("records"),
            subjects=profile.get("subjects"),
        )
    ])


def inspect_one(path: Path, dataset_id: str | None, out_dir: Path = PROFILE_DIR) -> dict[str, Any]:
    profile = write_profile(path, dataset_id or path.resolve().name, out_dir)
    return {k: v for k, v in profile.items() if k not in {"tables", "column_profiles"}}


def inspect_all(out_dir: Path = PROFILE_DIR) -> dict[str, Any]:
    summary = []
    for dataset_id, root in profile_targets():
        profile = write_profile(root, dataset_id, out_dir)
        register_measurements(dataset_id, profile)
        summary.append({
            "dataset_id": dataset_id,
            "has_tabular_data": profile.get("has_tabular_data"),
            "files": profile.get("file_count"),
            "records": profile.get("records"),
            "subjects": profile.get("subjects"),
            "unreadable_files": len(profile.get("unreadable_files", [])),
        })
    return {"out_dir": str(out_dir), "profiled": summary}
