"""Data-quality checks over a normalized surveillance table.

The checks report; they never edit. A country-week whose cumulative total went down is
named and kept, because a surveillance series being revised downwards is normal and
deciding whether a particular drop is a revision or a transcription error is a judgement
this code is not in a position to make.

A finding is an `error` only where the value cannot be what the schema says it is — a
negative case count, a percentage above 100, a reporting window that ends before it starts.
Everything else is a `warning`, which is recorded against the dataset and shown next to it
in the interface rather than stopping the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.epidemic import registry, surveillance


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
    dataset_id: str
    rows: int
    findings: list[Finding] = field(default_factory=list)
    missing_value_pct: float = 0.0
    duplicates_removed: int = 0

    @property
    def status(self) -> str:
        if any(finding.severity == "error" for finding in self.findings):
            return registry.QUALITY_FAILED
        if any(finding.severity == "warning" for finding in self.findings):
            return registry.QUALITY_WARNINGS
        return registry.QUALITY_PASSED

    def as_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "rows": self.rows,
            "status": self.status,
            "missing_value_pct": self.missing_value_pct,
            "duplicates_removed": self.duplicates_removed,
            "findings": [finding.as_dict() for finding in self.findings],
        }

    def summary_lines(self) -> list[str]:
        return [f"[{finding.severity}] {finding.message}" for finding in self.findings]


#: Columns that may legitimately be absent for some sources. `iso3` is null for a territory
#: that is outside the ISO mapping and for OWID's continent aggregates; `area` is null for
#: everything except subnational rows; `who_region` is null wherever the publisher omits it.
OPTIONAL_COLUMNS = frozenset({"iso3", "who_region", "area"})


def check(frame: pd.DataFrame, dataset_id: str, *, duplicates_removed: int = 0) -> Report:
    report = Report(dataset_id, len(frame), duplicates_removed=duplicates_removed)

    if frame.empty:
        report.findings.append(
            Finding("non_empty", "error", "the normalized table has no rows", 0)
        )
        return report

    required = [name for name in surveillance.COLUMNS if name not in OPTIONAL_COLUMNS]
    for column in required:
        blank = int(frame[column].isna().sum())
        if blank:
            report.findings.append(
                Finding(
                    "required_columns",
                    "error",
                    f"{column} is blank on {blank} row(s)",
                    blank,
                )
            )

    counts = frame[frame["unit"] == surveillance.COUNT]
    negative = int((counts["value"] < 0).sum())
    if negative:
        report.findings.append(
            Finding(
                "non_negative_counts",
                "error",
                f"{negative} row(s) report a negative count",
                negative,
            )
        )

    percents = frame[frame["unit"] == surveillance.PERCENT]
    out_of_range = int(((percents["value"] < 0) | (percents["value"] > 100)).sum())
    if out_of_range:
        report.findings.append(
            Finding(
                "percent_range",
                "error",
                f"{out_of_range} percentage value(s) fall outside 0-100",
                out_of_range,
            )
        )

    reversed_window = int((frame["period_end"] < frame["period_start"]).sum())
    if reversed_window:
        report.findings.append(
            Finding(
                "period_order",
                "error",
                f"{reversed_window} row(s) end before they start",
                reversed_window,
            )
        )

    future = int((frame["period_start"] > pd.Timestamp.utcnow().tz_localize(None)).sum())
    if future:
        report.findings.append(
            Finding(
                "not_in_future",
                "warning",
                f"{future} row(s) are dated in the future, which usually means a parsing "
                "problem in the publisher's date column",
                future,
            )
        )

    report.missing_value_pct = _missing_pct(frame)
    report.findings.extend(_cumulative_findings(frame))
    report.findings.extend(_coverage_findings(frame))
    if duplicates_removed:
        report.findings.append(
            Finding(
                "duplicates",
                "warning",
                f"{duplicates_removed} exact repeat(s) of the same observation were "
                "collapsed, keeping the last",
                duplicates_removed,
            )
        )
    return report


def _missing_pct(frame: pd.DataFrame) -> float:
    """Share of blank cells across the columns that are meant to be populated.

    The optional columns are excluded: counting a null `area` on a national row as missing
    data would put every country-level source at a permanent few per cent and make the
    figure useless for comparing sources.
    """
    columns = [name for name in surveillance.COLUMNS if name not in OPTIONAL_COLUMNS]
    cells = len(frame) * len(columns)
    if not cells:
        return 0.0
    return round(float(frame[columns].isna().sum().sum()) / cells * 100, 4)


def _cumulative_findings(frame: pd.DataFrame) -> list[Finding]:
    cumulative = frame[frame["metric"].isin(surveillance.CUMULATIVE_METRICS)]
    if cumulative.empty:
        return []
    ordered = cumulative.sort_values("period_start")
    grouped = ordered.groupby(["country", "metric"], dropna=False)["value"]
    drops = int((grouped.diff() < 0).sum())
    if not drops:
        return []
    return [
        Finding(
            "cumulative_monotonic",
            "warning",
            f"{drops} point(s) in a cumulative series are lower than the point before "
            "them. Downward revisions are routine in surveillance data and the values are "
            "kept as published",
            drops,
        )
    ]


def _coverage_findings(frame: pd.DataFrame) -> list[Finding]:
    findings = []
    span = frame["period_start"].max() - frame["period_start"].min()
    if pd.notna(span) and span.days < 30:
        findings.append(
            Finding(
                "temporal_coverage",
                "warning",
                f"the series spans only {span.days} day(s), which is too short to read a "
                "trend from",
                len(frame),
            )
        )
    countries = frame["country"].nunique(dropna=True)
    if countries <= 1:
        findings.append(
            Finding(
                "spatial_coverage",
                "warning",
                f"the series covers {countries} reporting area(s), so it describes one "
                "place and not a global picture",
                len(frame),
            )
        )
    return findings
