"""Quality checks over an acquired dataset, and the normalised copy they run against.

The checks report; they do not edit the stored file. `raw/` is what arrived and stays that
way, because a run is only reproducible if the bytes the digest was taken over are still
there. Preprocessing writes a separate parquet copy alongside it.

A finding is an `error` only where the data cannot be what it claims to be — no rows at
all, a pain rating outside its own scale, a column of entirely missing values. Anything
else is a `warning`: recorded against the version and shown next to it in the interface,
not treated as a reason to discard a dataset. Publishers revise data, leave columns
sparse and ship odd encodings, and a pipeline that refused all of it would hold nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from database.models import QualityStatus
from backend.sync import profile as profiling

ERROR = "error"
WARNING = "warning"

#: Below this, a supervised split by subject leaves too little in each fold for a metric
#: to carry meaning. It is a warning at the validation stage and a refusal at the
#: suitability stage.
THIN_ROWS = 200


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    rows: int = 0

    def as_dict(self) -> dict:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "rows": self.rows,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    #: The de-duplicated table, held in memory for the caller to write where it chooses.
    #: None when the file could not be re-read, which is itself a recorded finding.
    cleaned: pd.DataFrame | None = None
    duplicate_rows: int = 0

    @property
    def status(self) -> QualityStatus:
        if any(finding.severity == ERROR for finding in self.findings):
            return QualityStatus.FAILED
        if self.findings:
            return QualityStatus.PASSED_WITH_WARNINGS
        return QualityStatus.PASSED

    def as_dicts(self) -> list[dict]:
        return [finding.as_dict() for finding in self.findings]


SCALE_BOUNDS = {
    profiling.NRS: (0.0, 10.0),
    profiling.VAS: (0.0, 100.0),
    profiling.BINARY: (0.0, 1.0),
}


def check(files: tuple[Path, ...], measured: profiling.Profile) -> Report:
    report = Report()

    if measured.file is None:
        report.findings.append(
            Finding(
                "tabular_content",
                WARNING,
                "no tabular file was found, so the dataset is catalogued and stored but "
                "not profiled; it cannot be assessed for training from here",
            )
        )
        return report

    if not measured.rows:
        report.findings.append(
            Finding("non_empty", ERROR, f"{measured.file} holds no readable rows")
        )
        return report

    if measured.rows < THIN_ROWS:
        report.findings.append(
            Finding(
                "row_count",
                WARNING,
                f"the table holds {measured.rows:,} row(s), too few to evaluate a model on",
                measured.rows,
            )
        )

    if measured.missing_value_pct is not None and measured.missing_value_pct > 40:
        report.findings.append(
            Finding(
                "missing_values",
                WARNING,
                f"{measured.missing_value_pct:.1f}% of sampled cells are blank",
                measured.sampled_rows,
            )
        )

    frame = _load(files, measured)
    if frame is None:
        report.findings.append(
            Finding(
                "readable",
                WARNING,
                f"{measured.file} was counted but could not be re-read for preprocessing",
            )
        )
        return report

    report.findings.extend(_column_findings(frame))
    report.findings.extend(_target_findings(frame, measured))

    before = len(frame)
    frame = frame.drop_duplicates()
    report.duplicate_rows = before - len(frame)
    if report.duplicate_rows:
        report.findings.append(
            Finding(
                "duplicate_rows",
                WARNING,
                f"{report.duplicate_rows:,} exact repeat row(s) were dropped from the "
                "preprocessed copy; the stored original is unchanged",
                report.duplicate_rows,
            )
        )
    report.cleaned = frame
    return report


def _load(files: tuple[Path, ...], measured: profiling.Profile) -> pd.DataFrame | None:
    for path in files:
        if path.name == measured.file:
            frame, _ = profiling._read_sample(path, measured.file_format)
            return None if frame.empty else frame
    return None


def _column_findings(frame: pd.DataFrame) -> list[Finding]:
    findings = []
    empty = [str(column) for column in frame.columns if frame[column].isna().all()]
    if empty:
        shown = ", ".join(empty[:8]) + ("…" if len(empty) > 8 else "")
        findings.append(
            Finding(
                "empty_columns",
                WARNING,
                f"{len(empty)} column(s) are entirely blank: {shown}",
                len(empty),
            )
        )
    unnamed = [c for c in frame.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        findings.append(
            Finding(
                "unnamed_columns",
                WARNING,
                f"{len(unnamed)} column(s) have no header, which usually means a stray "
                "index column in the publisher's export",
                len(unnamed),
            )
        )
    return findings


def _target_findings(frame: pd.DataFrame, measured: profiling.Profile) -> list[Finding]:
    column = measured.target_column
    if not column or column not in frame.columns:
        return []
    findings = []
    values = pd.to_numeric(frame[column], errors="coerce")
    blank = int(values.isna().sum())
    if blank:
        findings.append(
            Finding(
                "target_present",
                WARNING if blank < len(frame) else ERROR,
                f"the rating column {column!r} is missing or non-numeric on {blank:,} row(s)",
                blank,
            )
        )
    bounds = SCALE_BOUNDS.get(measured.target_scale)
    if bounds is not None:
        low, high = bounds
        out = int(((values < low) | (values > high)).sum())
        if out:
            findings.append(
                Finding(
                    "target_range",
                    ERROR,
                    f"{out:,} value(s) in {column!r} fall outside the {measured.target_scale} "
                    f"range {low:g}-{high:g} the column's own values implied",
                    out,
                )
            )
    if values.notna().any() and values.nunique(dropna=True) == 1:
        findings.append(
            Finding(
                "target_variation",
                ERROR,
                f"every row carries the same value in {column!r}, so there is nothing to learn",
                len(frame),
            )
        )
    return findings


def write_preprocessed(frame: pd.DataFrame, destination: Path) -> Path:
    """Write the cleaned table as parquet next to the stored original.

    Column names are normalised to lower snake case so a downstream reader does not have
    to cope with four publishers' header conventions. Nothing else about the values is
    altered: no imputation, no rescaling, no row dropped beyond exact duplicates.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    renamed = frame.rename(
        columns={
            column: str(column).strip().casefold().replace(" ", "_").replace("-", "_")
            for column in frame.columns
        }
    )
    # Mixed-type object columns are what pyarrow refuses most often; the publisher's own
    # text is preserved by casting those to string rather than dropping the column.
    for column in renamed.columns:
        if renamed[column].dtype == object:
            renamed[column] = renamed[column].astype("string")
    renamed.to_parquet(destination, index=False, compression="zstd")
    return destination
