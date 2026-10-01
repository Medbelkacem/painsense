from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import FIELDS, PLAUSIBLE_RANGES, TARGET

LATERALITY_VALUES = {"LEFT", "RIGHT", "BILATERAL", "MIDLINE", "NOT_APPLICABLE"}
OUTLIER_IQR_MULTIPLIER = 3.0
MAX_EXAMPLES = 10

FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^self_reported_nrs$", "the regression target itself"),
    (r"^self_reported_vas$", "the target on its other recording scale"),
    (r"^original_pain_score$", "the verbatim published pain label, which is the target"),
    (r"^original_pain_scale$", "names the target's scale and so identifies the label source"),
    (r"nrs", "a numeric rating scale value, which is the target's instrument"),
    (r"\bvas\b", "a visual analogue scale value, which is the target's instrument"),
    (r"pain_score", "a recorded pain score, which is the target under another name"),
    (r"pain_level", "a recorded pain level, which is the target under another name"),
    (r"pain_intensity", "a recorded pain intensity, which is the target under another name"),
    (r"pain_severity", "a recorded pain severity, which is the target under another name"),
    (r"pain_class", "a binned form of the target"),
    (r"pain_category", "a binned form of the target"),
    (r"^target", "a column named as the prediction target"),
    (r"^label$", "a column named as the prediction label"),
    (r"predicted", "a model output, not an observation"),
    (r"prediction", "a model output, not an observation"),
    (r"ai_pain", "a model output, not an observation"),
    (r"_outcome$", "recorded after the assessment it would predict"),
    (r"followup|follow_up", "recorded after the assessment it would predict"),
    (r"discharge", "recorded after the assessment it would predict"),
    (r"next_visit|future_", "a measurement from after the assessment"),
)

CORRELATION_THRESHOLD = 0.98


def _issue(
    check: str, severity: str, detail: str, *, column: str | None = None, **extra: Any
) -> dict[str, Any]:
    return {"check": check, "severity": severity, "column": column, "detail": detail, **extra}


def _examples(frame: pd.DataFrame, mask: pd.Series) -> list[str]:
    ids = frame.loc[mask.fillna(False), "assessment_id"].astype("string").dropna()
    return ids.head(MAX_EXAMPLES).tolist()


def check_plausible_ranges(frame: pd.DataFrame) -> list[dict[str, Any]]:
    issues = []
    for column, (low, high) in PLAUSIBLE_RANGES.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        mask = values.notna() & ((values < low) | (values > high))
        count = int(mask.sum())
        if count:
            issues.append(_issue(
                "implausible_value", "error",
                f"{count} record(s) hold a {column} outside the plausible range {low}-{high} "
                f"(observed {values[mask].min()} to {values[mask].max()}); the values are kept "
                "and listed, not corrected",
                column=column, records=count, examples=_examples(frame, mask),
            ))
    return issues


def check_target(frame: pd.DataFrame) -> list[dict[str, Any]]:
    issues = []
    if TARGET not in frame.columns:
        return [_issue("missing_target_column", "error", f"{TARGET!r} is absent")]
    values = pd.to_numeric(frame[TARGET], errors="coerce")
    missing = int(values.isna().sum())
    if missing:
        issues.append(_issue(
            "missing_target", "warning",
            f"{missing} of {len(frame)} record(s) carry no {TARGET}; they cannot train or "
            "evaluate the regression and are excluded from it by the filter on the target",
            column=TARGET, records=missing,
        ))
    non_integer = values.notna() & (values != values.round())
    if int(non_integer.sum()):
        issues.append(_issue(
            "non_integer_target", "warning",
            f"{int(non_integer.sum())} record(s) hold a non-integer {TARGET}; a numeric rating "
            "scale is normally recorded as a whole number",
            column=TARGET, records=int(non_integer.sum()),
        ))
    return issues


def check_identity(frame: pd.DataFrame) -> list[dict[str, Any]]:
    issues = []
    duplicated = frame["assessment_id"].dropna().duplicated()
    if int(duplicated.sum()):
        issues.append(_issue(
            "duplicate_assessment_id", "error",
            f"{int(duplicated.sum())} record(s) repeat an assessment_id",
            column="assessment_id", records=int(duplicated.sum()),
        ))
    comparable = frame.drop(columns=[c for c in ("retrieved_at",) if c in frame.columns])
    duplicate_rows = int(comparable.astype("string").duplicated().sum())
    if duplicate_rows:
        issues.append(_issue(
            "duplicate_record", "warning",
            f"{duplicate_rows} record(s) are identical to another record in every field",
            records=duplicate_rows,
        ))
    missing_patient = int(frame["patient_id"].isna().sum())
    if missing_patient:
        issues.append(_issue(
            "missing_patient_id", "error",
            f"{missing_patient} record(s) carry no patient_id and cannot be split at patient "
            "level",
            column="patient_id", records=missing_patient,
        ))
    return issues


def check_repeated_measures(frame: pd.DataFrame) -> list[dict[str, Any]]:
    per_patient = frame.groupby("patient_id", dropna=True).size()
    repeated = int((per_patient > 1).sum())
    if not repeated:
        return []
    return [_issue(
        "repeated_measures_present", "warning",
        f"{repeated} patient(s) contribute more than one assessment, up to "
        f"{int(per_patient.max())}; any train/test split must therefore group on patient_id",
        column="patient_id", patients=repeated,
    )]


def check_timestamps(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "timestamp" not in frame.columns:
        return []
    stamps = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    if stamps.notna().sum() == 0:
        return [_issue(
            "no_timestamps", "warning",
            "no record carries a timestamp, so no temporal ordering or future-information "
            "check is possible for this data",
            column="timestamp",
        )]
    issues = []
    future = stamps.notna() & (stamps > pd.Timestamp.now(tz="UTC"))
    if int(future.sum()):
        issues.append(_issue(
            "timestamp_in_future", "error",
            f"{int(future.sum())} record(s) are stamped later than now",
            column="timestamp", records=int(future.sum()),
        ))
    return issues


def check_laterality(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "laterality" not in frame.columns:
        return []
    tokens = frame["laterality"].astype("string").dropna().str.split(";").explode().str.strip()
    unexpected = sorted(set(tokens[(tokens != "") & ~tokens.isin(LATERALITY_VALUES)]))
    if not unexpected:
        return []
    return [_issue(
        "unexpected_laterality", "warning",
        f"{len(unexpected)} laterality value(s) fall outside "
        f"{sorted(LATERALITY_VALUES)}: {unexpected[:8]}",
        column="laterality", values=unexpected[:50],
    )]


def check_anatomy(frame: pd.DataFrame, reference: set[str] | None) -> list[dict[str, Any]]:
    if "anatomy_id" not in frame.columns:
        return []
    tokens = frame["anatomy_id"].astype("string").dropna().str.split(";").explode().str.strip()
    tokens = tokens[tokens != ""]
    if tokens.empty:
        return [_issue(
            "no_anatomy_ids", "warning",
            "no record carries an anatomy_id, so pain location cannot be resolved to a "
            "structure in the ontology",
            column="anatomy_id",
        )]
    if reference is None:
        return [_issue(
            "anatomy_reference_unavailable", "warning",
            f"{tokens.nunique()} distinct anatomy token(s) are present but no ontology was "
            "available to validate them against",
            column="anatomy_id",
        )]
    unknown = sorted(set(tokens) - reference)
    if not unknown:
        return []
    return [_issue(
        "unknown_anatomy_id", "error",
        f"{len(unknown)} anatomy token(s) are not in the ontology of {len(reference)} "
        f"structures: {unknown[:8]}",
        column="anatomy_id", unknown_tokens=unknown[:50],
    )]


def check_outliers(frame: pd.DataFrame) -> list[dict[str, Any]]:
    issues = []
    numeric_fields = [
        name for name, (dtype, group) in FIELDS.items()
        if dtype == "Float64" and group in {"physiology", "biosignal", "demographics"}
    ]
    for column in numeric_fields:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(values) < 50:
            continue
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        spread = q3 - q1
        if spread <= 0:
            continue
        low = q1 - OUTLIER_IQR_MULTIPLIER * spread
        high = q3 + OUTLIER_IQR_MULTIPLIER * spread
        count = int(((values < low) | (values > high)).sum())
        if count:
            issues.append(_issue(
                "extreme_outlier", "warning",
                f"{count} of {len(values)} {column} value(s) lie beyond "
                f"{OUTLIER_IQR_MULTIPLIER} interquartile ranges from the quartiles "
                f"({low:.1f} to {high:.1f}); flagged, not removed",
                column=column, records=count,
            ))
    return issues


def check_label_consistency(frame: pd.DataFrame) -> list[dict[str, Any]]:
    issues = []
    by_source = frame.groupby("dataset_id", dropna=True)["original_pain_scale"].nunique()
    conflicted = by_source[by_source > 1]
    if not conflicted.empty:
        issues.append(_issue(
            "conflicting_pain_scales", "error",
            f"{len(conflicted)} source(s) record more than one original_pain_scale, so a "
            f"published score cannot be interpreted unambiguously: {list(conflicted.index)}",
            column="original_pain_scale",
        ))
    both = frame[TARGET].notna() & frame["original_pain_score"].notna()
    disagreeing = both & (
        pd.to_numeric(frame[TARGET], errors="coerce")
        != pd.to_numeric(frame["original_pain_score"], errors="coerce")
    )
    if int(disagreeing.sum()):
        issues.append(_issue(
            "target_disagrees_with_published_score", "warning",
            f"{int(disagreeing.sum())} record(s) hold a {TARGET} different from the verbatim "
            "original_pain_score they were mapped from",
            records=int(disagreeing.sum()),
        ))
    return issues


def anatomy_reference(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    try:
        return set(pd.read_parquet(path)["code"].astype("string").dropna())
    except Exception:  # noqa: BLE001 - an unreadable reference means no reference, not a crash
        return None


def validate(frame: pd.DataFrame, *, anatomy: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        *check_identity(frame),
        *check_target(frame),
        *check_plausible_ranges(frame),
        *check_repeated_measures(frame),
        *check_timestamps(frame),
        *check_laterality(frame),
        *check_anatomy(frame, anatomy),
        *check_outliers(frame),
        *check_label_consistency(frame),
    ]


def counts(issues: Iterable[dict[str, Any]]) -> dict[str, int]:
    tally = {"error": 0, "warning": 0}
    for issue in issues:
        tally[issue["severity"]] = tally.get(issue["severity"], 0) + 1
    return tally


def check_feature_names(columns: Iterable[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for column in columns:
        lowered = column.strip().lower()
        for pattern, reason in FORBIDDEN_PATTERNS:
            if re.search(pattern, lowered):
                findings.append(_issue(
                    "target_leakage_by_name", "blocking",
                    f"feature {column!r} matches /{pattern}/: {reason}",
                    column=column, pattern=pattern,
                ))
                break
    return findings


def check_target_correlation(
    frame: pd.DataFrame, feature_columns: Sequence[str], *, target: str = TARGET
) -> list[dict[str, Any]]:
    if target not in frame.columns:
        return []
    labels = pd.to_numeric(frame[target], errors="coerce")
    if labels.notna().sum() < 30:
        return []

    findings: list[dict[str, Any]] = []
    for column in feature_columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        pair = pd.concat([values, labels], axis=1).dropna()
        if len(pair) < 30 or pair.iloc[:, 0].nunique() < 2:
            continue
        correlation = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
        if correlation is not None and abs(correlation) >= CORRELATION_THRESHOLD:
            findings.append(_issue(
                "target_leakage_by_correlation", "blocking",
                f"feature {column!r} has Spearman correlation {correlation:.4f} with "
                f"{target!r} over {len(pair)} rows, which is consistent with it being "
                "derived from the target rather than observed independently",
                column=column, spearman=round(float(correlation), 4), rows=len(pair),
            ))
    return findings


def check_patient_split_overlap(
    frame: pd.DataFrame, *, patient_column: str = "patient_id", split_column: str = "split"
) -> list[dict[str, Any]]:
    if patient_column not in frame.columns or split_column not in frame.columns:
        return [_issue(
            "patient_leakage", "blocking",
            f"cannot check patient leakage: {patient_column!r} or {split_column!r} is absent",
        )]
    present = frame[[patient_column, split_column]].dropna()
    splits_per_patient = present.groupby(patient_column)[split_column].nunique()
    offenders = splits_per_patient[splits_per_patient > 1]
    if offenders.empty:
        return []
    return [_issue(
        "patient_leakage", "blocking",
        f"{len(offenders)} patient(s) appear in more than one split; the split must be "
        "taken at patient level, not at record level",
        patients_affected=len(offenders),
        examples=sorted(offenders.index.astype(str))[:10],
    )]


def check_duplicate_assessments(
    frame: pd.DataFrame, *, assessment_column: str = "assessment_id"
) -> list[dict[str, Any]]:
    if assessment_column not in frame.columns:
        return []
    count = int(frame[assessment_column].dropna().duplicated().sum())
    if not count:
        return []
    return [_issue(
        "duplicate_assessment_id", "blocking",
        f"{count} record(s) repeat an {assessment_column!r} already used, so the same "
        "assessment could be counted twice and could straddle a split",
        duplicates=count,
    )]


def check_subject_identifier(
    frame: pd.DataFrame, *, patient_column: str = "patient_id"
) -> list[dict[str, Any]]:
    if patient_column not in frame.columns:
        return [_issue(
            "no_subject_identifier", "blocking", f"{patient_column!r} is absent from the frame"
        )]
    missing = int(frame[patient_column].isna().sum())
    if not missing:
        return []
    return [_issue(
        "no_subject_identifier", "warning",
        f"{missing} record(s) carry no {patient_column!r}; they cannot be assigned to a "
        "patient-level split and are excluded from the model-ready table",
        records=missing,
    )]


def audit_features(
    frame: pd.DataFrame, feature_columns: Sequence[str], *, target: str = TARGET
) -> list[dict[str, Any]]:
    return check_feature_names(feature_columns) + check_target_correlation(
        frame, feature_columns, target=target
    )


def audit_dataset(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return (
        check_subject_identifier(frame)
        + check_duplicate_assessments(frame)
        + check_patient_split_overlap(frame)
    )


def has_blocking(findings: Iterable[dict[str, Any]]) -> bool:
    return any(finding["severity"] == "blocking" for finding in findings)
