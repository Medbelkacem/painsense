from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import checks, registry
from .registry import (
    LEAKAGE_REPORT_PATH,
    METADATA_DIR,
    MODEL_READY_FILE,
    PROFILE_DIR,
    REPORTS_DIR,
    UNIFIED_FILE,
    VALIDATION_REPORT_PATH,
    ensure,
)
from .schema import CARRIED, TARGET
from .sources import SYNTHETIC_ROOT

ANATOMY_REFERENCE = SYNTHETIC_ROOT / "anatomy" / "anatomy_master.parquet"
VALIDATION_MARKDOWN = REPORTS_DIR / "validation.md"
LEAKAGE_MARKDOWN = REPORTS_DIR / "leakage.md"


def unreadable_files() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        for item in profile.get("unreadable_files", []):
            found.append({"dataset_id": profile.get("dataset_id"), **item})
    return found


def validate_per_source(frame: pd.DataFrame, anatomy: set[str] | None) -> list[dict[str, Any]]:
    results = []
    for dataset_id, subset in frame.groupby("dataset_id", dropna=True):
        issues = checks.validate(subset, anatomy=anatomy)
        results.append({
            "dataset_id": str(dataset_id),
            "records": len(subset),
            "patients": int(subset["patient_id"].nunique()),
            "counts": checks.counts(issues),
            "issues": issues,
        })
    return results


def leakage_audit(unified: pd.DataFrame) -> dict[str, Any]:
    patient_findings = checks.audit_dataset(unified) if "split" in unified.columns else [{
        "check": "split_absent_from_unified",
        "severity": "warning",
        "column": "split",
        "detail": (
            "The unified table carries no split column; the split is assigned when the "
            "model-ready matrix is built and is audited there."
        ),
    }]

    if not MODEL_READY_FILE.exists():
        return {
            "model_ready_present": False,
            "patient_findings": patient_findings,
            "feature_findings": [],
            "feature_count": 0,
            "notes": f"{MODEL_READY_FILE} does not exist; run the merge step first.",
        }

    encoded = pd.read_parquet(MODEL_READY_FILE)
    reserved = {*CARRIED, TARGET}
    feature_columns = [column for column in encoded.columns if column not in reserved]
    return {
        "model_ready_present": True,
        "patient_findings": checks.audit_dataset(encoded),
        "feature_findings": checks.audit_features(encoded, feature_columns),
        "feature_count": len(feature_columns),
        "forbidden_patterns": [
            {"pattern": pattern, "reason": reason}
            for pattern, reason in checks.FORBIDDEN_PATTERNS
        ],
        "correlation_threshold": checks.CORRELATION_THRESHOLD,
        "split_summary": {
            name: int((encoded["split"] == name).sum())
            for name in sorted(encoded["split"].dropna().unique())
        },
    }


def validation_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Dataset validation report",
        "",
        f"Generated {report['generated_at']} by `dataset.pipeline validate`.",
        "",
        ("Every figure below is computed from the files on disk. No record was altered or "
        "removed by validation: a value that cannot be true is reported and kept, because "
        "deciding whether an improbable reading is a transcription error or a genuinely "
        "unusual patient is a clinical judgement."),
        "",
        "## Summary",
        "",
        f"- Records validated: {report['records']:,}",
        f"- Patients: {report['patients']:,}",
        f"- Sources: {len(report['per_source'])}",
        f"- Checks of severity error: {report['counts']['error']}",
        f"- Checks of severity warning: {report['counts']['warning']}",
        f"- Unreadable files found during profiling: {len(report['unreadable_files'])}",
        "",
    ]
    if report["unreadable_files"]:
        lines += ["### Unreadable files", ""]
        lines += [
            f"- `{item['dataset_id']}`: `{item['file']}` — {item['error']}"
            for item in report["unreadable_files"]
        ]
        lines.append("")

    lines += ["## Findings across the unified dataset", ""]
    if not report["issues"]:
        lines += ["No check fired.", ""]
    else:
        lines += ["| severity | check | column | detail |", "| --- | --- | --- | --- |"]
        for issue in report["issues"]:
            lines.append(
                f"| {issue['severity']} | `{issue['check']}` | "
                f"`{issue['column'] or ''}` | {issue['detail']} |"
            )
        lines.append("")

    lines += ["## Findings per source", ""]
    for source in report["per_source"]:
        lines += [
            f"### `{source['dataset_id']}`",
            "",
            (f"{source['records']:,} record(s), {source['patients']:,} patient(s). "
            f"{source['counts']['error']} error(s), {source['counts']['warning']} warning(s)."),
            "",
        ]
        if source["issues"]:
            lines += ["| severity | check | detail |", "| --- | --- | --- |"]
            for issue in source["issues"]:
                lines.append(f"| {issue['severity']} | `{issue['check']}` | {issue['detail']} |")
            lines.append("")
    return "\n".join(lines)


def leakage_markdown(report: dict[str, Any]) -> str:
    audit = report["audit"]
    lines = [
        "# Dataset leakage report",
        "",
        f"Generated {report['generated_at']} by `dataset.pipeline validate`.",
        "",
        ("Two failures are checked separately. **Target leakage** is the target, or anything "
        "derived from it, reaching the model as an input. **Patient leakage** is one patient's "
        "records appearing on both sides of a train/test boundary, which turns a test score "
        "into a measure of memorisation."),
        "",
        "## Result",
        "",
        f"- Model-ready matrix present: {audit['model_ready_present']}",
        f"- Features audited: {audit['feature_count']}",
        f"- Target-leakage findings: {len(audit['feature_findings'])}",
        f"- Patient-leakage findings: {len(audit['patient_findings'])}",
        f"- Blocking: {report['blocking']}",
        "",
        "## How target leakage is detected",
        "",
        ("Two independent checks, because either alone is evadable. A name check rejects a "
        "feature whose name matches a forbidden pattern. A correlation check rejects a feature "
        "whose Spearman correlation with the target reaches "
        f"{audit.get('correlation_threshold', 'n/a')}, which catches a derived target that has "
        "been renamed to something innocuous and so passes the name check."),
        "",
        ("Structurally, the target cannot reach the feature matrix in the first place: every "
        "field in the schema's `label` group is excluded from the candidate features. That "
        "group holds `self_reported_nrs`, `self_reported_vas`, `original_pain_score`, "
        "`original_pain_scale` and `pain_present`. The last matters most — it is derived from "
        "the score, so it would otherwise pass as an ordinary clinical observation."),
        "",
    ]
    if audit.get("forbidden_patterns"):
        lines += [
            "### Forbidden feature-name patterns",
            "",
            "| pattern | why it is refused |",
            "| --- | --- |",
        ]
        lines += [
            f"| `{item['pattern']}` | {item['reason']} |" for item in audit["forbidden_patterns"]
        ]
        lines.append("")

    lines += [
        "## How patient leakage is prevented",
        "",
        ("The unit of split assignment is the patient, never the record. Patients are "
        "stratified by their own mean label and then dealt into train, validation and test, "
        "so every assessment belonging to one patient lands in exactly one split. After "
        "assignment the split is audited: any patient found in more than one split is a "
        "blocking finding."),
        "",
    ]
    if audit.get("split_summary"):
        lines += ["| split | records |", "| --- | --- |"]
        lines += [f"| {name} | {count:,} |" for name, count in audit["split_summary"].items()]
        lines.append("")

    findings = audit["feature_findings"] + audit["patient_findings"]
    lines += ["## Findings", ""]
    if not findings:
        lines += ["No leakage finding. Neither check fired.", ""]
    else:
        lines += ["| severity | check | column | detail |", "| --- | --- | --- | --- |"]
        for item in findings:
            lines.append(
                f"| {item['severity']} | `{item['check']}` | `{item.get('column') or ''}` | "
                f"{item['detail']} |"
            )
        lines.append("")

    lines += [
        "## Limits of these checks",
        "",
        ("The correlation check needs at least thirty rows carrying the target and only sees a "
        "monotone relationship; a feature encoding the target non-monotonically would pass it. "
        "A source with no subject identifier cannot be split safely at all, and is reported "
        "rather than guessed at. Neither check can detect leakage that happened before the "
        "data reached this pipeline, such as a published label that was itself derived from a "
        "feature."),
        "",
    ]
    return "\n".join(lines)


def validate(unified_path: Path = UNIFIED_FILE) -> tuple[dict[str, Any], bool]:
    unified = pd.read_parquet(unified_path)
    anatomy = checks.anatomy_reference(ANATOMY_REFERENCE)
    issues = checks.validate(unified, anatomy=anatomy)
    per_source = validate_per_source(unified, anatomy)
    unreadable = unreadable_files()
    if unreadable:
        issues.append({
            "check": "unreadable_file",
            "severity": "error",
            "column": None,
            "detail": f"{len(unreadable)} file(s) could not be read during profiling",
            "files": unreadable,
        })

    validation_report = {
        "generated_at": registry.now(),
        "unified_path": str(unified_path),
        "records": len(unified),
        "patients": int(unified["patient_id"].nunique()),
        "anatomy_reference": str(ANATOMY_REFERENCE) if anatomy else None,
        "anatomy_structures": len(anatomy) if anatomy else None,
        "counts": checks.counts(issues),
        "issues": issues,
        "per_source": per_source,
        "unreadable_files": unreadable,
        "policy": "checks report; no record is altered or removed by validation",
    }

    audit = leakage_audit(unified)
    blocking = checks.has_blocking(audit["feature_findings"]) or checks.has_blocking(
        audit["patient_findings"]
    )
    leakage_report = {
        "generated_at": registry.now(),
        "target": TARGET,
        "audit": audit,
        "blocking": blocking,
    }

    ensure(METADATA_DIR)
    ensure(REPORTS_DIR)
    VALIDATION_REPORT_PATH.write_text(
        json.dumps(validation_report, indent=2) + "\n", encoding="utf-8"
    )
    LEAKAGE_REPORT_PATH.write_text(json.dumps(leakage_report, indent=2) + "\n", encoding="utf-8")
    VALIDATION_MARKDOWN.write_text(validation_markdown(validation_report), encoding="utf-8")
    LEAKAGE_MARKDOWN.write_text(leakage_markdown(leakage_report), encoding="utf-8")

    failed = bool(validation_report["counts"].get("error", 0)) or blocking
    summary = {
        "validation_report": str(VALIDATION_MARKDOWN),
        "leakage_report": str(LEAKAGE_MARKDOWN),
        "records": validation_report["records"],
        "patients": validation_report["patients"],
        "counts": validation_report["counts"],
        "per_source": [
            {"dataset_id": item["dataset_id"], "counts": item["counts"]} for item in per_source
        ],
        "target_leakage_findings": len(audit["feature_findings"]),
        "patient_leakage_findings": len(audit["patient_findings"]),
        "leakage_blocking": blocking,
    }
    return summary, failed
