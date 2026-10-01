from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import registry
from .registry import (
    METADATA_DIR,
    MODEL_READY_FILE,
    REPORTS_DIR,
    STATISTICS_REPORT_PATH,
    UNIFIED_FILE,
    ensure,
)
from .schema import FIELDS, TARGET

STATISTICS_MARKDOWN = REPORTS_DIR / "statistics.md"

PHYSIOLOGY_FIELDS = tuple(
    name for name, (_, group) in FIELDS.items() if group in {"physiology", "biosignal"}
)
TOP_N = 15

NOTES = (
    "Computed from the unified parquet. A field no source populates shows a missingness of 1.0 "
    "and no summary; it is part of the schema because the platform records it, not because this "
    "data contains it."
)


def _distribution(series: pd.Series, *, limit: int = TOP_N) -> dict[str, int]:
    counts = series.value_counts(dropna=True)
    return {str(key): int(value) for key, value in counts.head(limit).items()}


def _token_distribution(series: pd.Series, *, limit: int = TOP_N) -> dict[str, int]:
    tokens = series.astype("string").dropna().str.split(";").explode().str.strip()
    return _distribution(tokens[tokens != ""], limit=limit)


def _numeric_summary(series: pd.Series) -> dict[str, Any] | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return {
        "count": len(values),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": round(float(values.mean()), 4),
        "std": round(float(values.std()), 4) if len(values) > 1 else None,
        "median": float(values.median()),
    }


def compute(unified: pd.DataFrame, splits: pd.DataFrame | None) -> dict[str, Any]:
    synthetic = unified["synthetic"].fillna(False)
    target = pd.to_numeric(unified[TARGET], errors="coerce")
    pain_present = unified["pain_present"]

    missingness = {
        name: round(float(unified[name].isna().mean()), 6)
        for name in FIELDS
        if name in unified.columns
    }

    per_source = {}
    for dataset_id, subset in unified.groupby("dataset_id", dropna=True):
        subset_target = pd.to_numeric(subset[TARGET], errors="coerce")
        per_source[str(dataset_id)] = {
            "records": len(subset),
            "patients": int(subset["patient_id"].nunique()),
            "synthetic": bool(subset["synthetic"].iloc[0]),
            "license": str(subset["license"].iloc[0]),
            "records_with_nrs_target": int(subset_target.notna().sum()),
            "original_pain_scale": str(subset["original_pain_scale"].iloc[0]),
            "original_pain_score": _numeric_summary(subset["original_pain_score"]),
            "nrs": _numeric_summary(subset[TARGET]),
            "repeated_measures_max": int(subset.groupby("patient_id").size().max()),
        }

    report: dict[str, Any] = {
        "generated_at": registry.now(),
        "unified_path": str(UNIFIED_FILE),
        "total_records": len(unified),
        "unique_patients": int(unified["patient_id"].nunique()),
        "datasets_represented": int(unified["dataset_id"].nunique()),
        "real_vs_synthetic": {
            "real_records": int((~synthetic).sum()),
            "synthetic_records": int(synthetic.sum()),
            "real_patients": int(unified.loc[~synthetic, "patient_id"].nunique()),
            "synthetic_patients": int(unified.loc[synthetic, "patient_id"].nunique()),
        },
        "pain_present_distribution": {
            "pain": int(pain_present.eq(True).sum()),
            "no_pain": int(pain_present.eq(False).sum()),
            "not_recorded": int(pain_present.isna().sum()),
        },
        "nrs_target": {
            "records_with_target": int(target.notna().sum()),
            "records_without_target": int(target.isna().sum()),
            "summary": _numeric_summary(unified[TARGET]),
            "distribution": _distribution(target.dropna().astype(int).astype(str), limit=11),
        },
        "pain_type_distribution": _distribution(unified["pain_type"]),
        "pain_region_distribution": _distribution(unified["pain_region"]),
        "anatomy_distribution": _token_distribution(unified["anatomy_id"]),
        "pain_quality_distribution": _token_distribution(unified["pain_quality"]),
        "physiological_signal_availability": {
            name: {
                "records_present": int(unified[name].notna().sum()),
                "fraction_present": round(float(unified[name].notna().mean()), 6),
                "summary": _numeric_summary(unified[name]),
            }
            for name in PHYSIOLOGY_FIELDS
            if name in unified.columns
        },
        "missingness_by_field": dict(sorted(missingness.items(), key=lambda kv: -kv[1])),
        "demographics": {
            "age": _numeric_summary(unified["age"]),
            "sex": _distribution(unified["sex"]),
        },
        "source_distribution": _distribution(unified["data_source"], limit=50),
        "license_distribution": _distribution(unified["license"], limit=50),
        "per_source": per_source,
        "split_assignment": None,
        "notes": NOTES,
    }

    if splits is not None and "split" in splits.columns:
        split_target = pd.to_numeric(splits[TARGET], errors="coerce")
        report["split_assignment"] = {
            name: {
                "records": int((splits["split"] == name).sum()),
                "patients": int(splits.loc[splits["split"] == name, "patient_id"].nunique()),
                "records_with_target": int(split_target[splits["split"] == name].notna().sum()),
                "target_mean": round(
                    float(split_target[splits["split"] == name].mean()), 4
                ) if split_target[splits["split"] == name].notna().any() else None,
            }
            for name in sorted(splits["split"].dropna().unique())
        }
    return report


def _table(title: str, rows: dict[str, Any], *, headers: tuple[str, str]) -> list[str]:
    if not rows:
        return [f"### {title}", "", "No values recorded.", ""]
    lines = [f"### {title}", "", f"| {headers[0]} | {headers[1]} |", "| --- | --- |"]
    lines += [
        f"| `{key}` | {value:,} |" if isinstance(value, int) else f"| `{key}` | {value} |"
        for key, value in rows.items()
    ]
    lines.append("")
    return lines


def markdown(report: dict[str, Any]) -> str:
    real = report["real_vs_synthetic"]
    lines = [
        "# Dataset statistics",
        "",
        f"Generated {report['generated_at']} by `dataset.pipeline statistics` from "
        f"`{Path(report['unified_path']).name}`.",
        "",
        "Every figure here is computed from the parquet on disk. No statistic is carried over "
        "from a publisher's description of their data.",
        "",
        "## Totals",
        "",
        f"- Records: **{report['total_records']:,}**",
        f"- Unique patients: **{report['unique_patients']:,}**",
        f"- Sources represented: **{report['datasets_represented']}**",
        f"- Real records: **{real['real_records']:,}** across {real['real_patients']:,} patients",
        f"- Synthetic records: **{real['synthetic_records']:,}** across "
        f"{real['synthetic_patients']:,} patients",
        "",
        "## The regression target",
        "",
        f"- Records carrying `{TARGET}`: **{report['nrs_target']['records_with_target']:,}**",
        f"- Records without it: **{report['nrs_target']['records_without_target']:,}**",
        "",
        "A record carries the target only where its publisher documents the pain label as a "
        "0-10 numeric rating scale. Where they document a different scale, the published value "
        "is kept verbatim in `original_pain_score` and the target stays null, because no "
        "conversion between scales is invented.",
        "",
    ]
    summary = report["nrs_target"]["summary"]
    if summary:
        lines += [
            f"- Target range {summary['min']} to {summary['max']}, mean {summary['mean']}, "
            f"standard deviation {summary['std']}, median {summary['median']}",
            "",
        ]
    lines += _table(
        "Target distribution", report["nrs_target"]["distribution"], headers=("NRS", "records")
    )

    lines += [
        "## Per source",
        "",
        "| source | records | patients | synthetic | with target | licence | max repeats |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for dataset_id, item in report["per_source"].items():
        lines.append(
            f"| `{dataset_id}` | {item['records']:,} | {item['patients']:,} | "
            f"{item['synthetic']} | {item['records_with_nrs_target']:,} | {item['license']} | "
            f"{item['repeated_measures_max']} |"
        )
    lines.append("")
    lines += ["### Pain scale recorded by each source", ""]
    for dataset_id, item in report["per_source"].items():
        lines.append(f"- `{dataset_id}`: {item['original_pain_scale']}")
    lines.append("")

    if report["split_assignment"]:
        lines += [
            "## Patient-level split",
            "",
            "| split | records | patients | with target | target mean |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, item in report["split_assignment"].items():
            lines.append(
                f"| {name} | {item['records']:,} | {item['patients']:,} | "
                f"{item['records_with_target']:,} | {item['target_mean']} |"
            )
        lines.append("")

    presence = report["pain_present_distribution"]
    lines += [
        "## Pain and no pain",
        "",
        f"- Pain recorded: {presence['pain']:,}",
        f"- No pain recorded: {presence['no_pain']:,}",
        f"- Not recorded: {presence['not_recorded']:,}",
        "",
    ]

    lines += _table("Pain type", report["pain_type_distribution"], headers=("type", "records"))
    lines += _table(
        "Pain region", report["pain_region_distribution"], headers=("region", "records")
    )
    lines += _table(
        f"Anatomy, top {TOP_N} structures", report["anatomy_distribution"],
        headers=("structure", "records"),
    )
    lines += _table(
        f"Pain quality, top {TOP_N}", report["pain_quality_distribution"],
        headers=("quality", "records"),
    )

    lines += [
        "## Physiological signal availability",
        "",
        "| signal | records present | fraction | mean | min | max |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, item in report["physiological_signal_availability"].items():
        values = item["summary"]
        lines.append(
            f"| `{name}` | {item['records_present']:,} | {item['fraction_present']:.3f} | "
            f"{values['mean'] if values else ''} | {values['min'] if values else ''} | "
            f"{values['max'] if values else ''} |"
        )
    lines.append("")

    demographics = report["demographics"]
    lines += ["## Demographics", ""]
    if demographics["age"]:
        age = demographics["age"]
        lines += [
            f"- Age present on {age['count']:,} records, range {age['min']} to {age['max']}, "
            f"mean {age['mean']}",
            "",
        ]
    lines += _table("Sex", demographics["sex"], headers=("sex", "records"))
    lines += _table("Source", report["source_distribution"], headers=("data source", "records"))
    lines += _table("Licence", report["license_distribution"], headers=("licence", "records"))

    lines += [
        "## Missingness by field",
        "",
        "Fraction of records where the field is null, highest first.",
        "",
        "| field | missing fraction |",
        "| --- | --- |",
    ]
    lines += [
        f"| `{name}` | {value:.4f} |" for name, value in report["missingness_by_field"].items()
    ]
    lines += ["", report["notes"], ""]
    return "\n".join(lines)


def generate(unified_path: Path = UNIFIED_FILE) -> dict[str, Any]:
    unified = pd.read_parquet(unified_path)
    splits = None
    if MODEL_READY_FILE.exists():
        splits = pd.read_parquet(MODEL_READY_FILE, columns=["patient_id", "split", TARGET])

    report = compute(unified, splits)
    ensure(METADATA_DIR)
    ensure(REPORTS_DIR)
    STATISTICS_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    STATISTICS_MARKDOWN.write_text(markdown(report), encoding="utf-8")

    return {
        "statistics_markdown": str(STATISTICS_MARKDOWN),
        "statistics_json": str(STATISTICS_REPORT_PATH),
        "total_records": report["total_records"],
        "unique_patients": report["unique_patients"],
        "real_vs_synthetic": report["real_vs_synthetic"],
        "records_with_target": report["nrs_target"]["records_with_target"],
        "split_assignment": report["split_assignment"],
    }
