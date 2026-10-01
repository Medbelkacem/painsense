"""Measuring what actually arrived, as opposed to what the publisher said would.

Everything in a `Profile` is read off the stored files. Row counts are counted, not taken
from a listing; column names come from the header; the target column is identified from
the data's own values, not from the dataset's title. That matters because the publisher's
description is the only evidence available at discovery time and it is routinely wrong —
a Kaggle page advertising "pain intensity" often ships a binary pain/no-pain flag.

Statistics are computed from a bounded sample while `rows` is the full count, and the two
are reported separately. Claiming a missing-value percentage over 200,000 of 4 million
rows as though it covered the file would be the same category of error this module exists
to catch, so `sampled_rows` always says what the figure was computed from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from database.models import Granularity

#: Enough rows for a column's shape to be clear, few enough to profile a multi-gigabyte
#: export without holding it in memory.
SAMPLE_ROWS = 200_000
TABULAR = ("parquet", "csv", "tsv", "jsonl", "ndjson", "json")

#: Column names that identify the person a row is about. Order matters: the first match
#: wins, and the more specific names come first so a file with both `subject_id` and a
#: generic `id` attributes rows to the subject.
SUBJECT_COLUMNS = (
    "subject_id",
    "participant_id",
    "patient_id",
    "subject",
    "participant",
    "patient",
    "person_id",
    "case_id",
    "record_id",
)

#: Column names that carry a pain rating. `label` and `target` are deliberately absent:
#: in a pain dataset they are as likely to be a stimulus class as a rating, and guessing
#: wrong produces a model trained on the wrong thing.
TARGET_COLUMNS = (
    "pain_intensity",
    "pain_score",
    "pain_level",
    "pain_rating",
    "pain_nrs",
    "nrs",
    "vas",
    "pain",
    "pain_label",
)

#: Column names typical of a table whose rows are places and periods rather than people.
AGGREGATE_COLUMNS = (
    "country",
    "spatialdim",
    "timedim",
    "iso3",
    "who_region",
    "year",
    "week",
    "mmwr_year",
    "mmwr_week",
    "reporting_area",
)

NRS = "nrs_0_10"
VAS = "vas_0_100"
BINARY = "binary"
UNKNOWN_SCALE = "unknown"


@dataclass
class Profile:
    file: str | None = None
    file_format: str = ""
    rows: int | None = None
    sampled_rows: int = 0
    columns: list[str] = field(default_factory=list)
    missing_value_pct: float | None = None
    subject_column: str | None = None
    subjects: int | None = None
    target_column: str | None = None
    target_scale: str = UNKNOWN_SCALE
    numeric_columns: list[str] = field(default_factory=list)
    granularity: Granularity = Granularity.UNKNOWN
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "file_format": self.file_format,
            "rows": self.rows,
            "sampled_rows": self.sampled_rows,
            "columns": self.columns,
            "missing_value_pct": self.missing_value_pct,
            "subject_column": self.subject_column,
            "subjects": self.subjects,
            "target_column": self.target_column,
            "target_scale": self.target_scale,
            "granularity": self.granularity.value,
            "notes": self.notes,
        }


def _largest_tabular(files: tuple[Path, ...]) -> Path | None:
    candidates = [
        path
        for path in files
        if path.is_file() and path.suffix.lower().lstrip(".") in TABULAR
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def _count_lines(path: Path, *, header: bool) -> int:
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            total += chunk.count(b"\n")
        handle.seek(max(0, path.stat().st_size - 1))
        if path.stat().st_size and handle.read(1) not in (b"\n", b""):
            total += 1
    return max(0, total - 1) if header else total


def _read_sample(path: Path, suffix: str) -> tuple[pd.DataFrame, int | None]:
    """A bounded sample plus the full row count where it can be had cheaply."""
    if suffix == "parquet":
        import pyarrow.parquet as pq

        handle = pq.ParquetFile(path)
        total = handle.metadata.num_rows
        batches = []
        taken = 0
        for batch in handle.iter_batches(batch_size=50_000):
            batches.append(batch.to_pandas())
            taken += len(batch)
            if taken >= SAMPLE_ROWS:
                break
        frame = pd.concat(batches, ignore_index=True) if batches else pd.DataFrame()
        return frame, total
    if suffix in ("jsonl", "ndjson"):
        rows = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                if len(rows) >= SAMPLE_ROWS:
                    break
        return pd.json_normalize(rows), _count_lines(path, header=False)
    if suffix == "json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return pd.DataFrame(), None
        if isinstance(payload, dict):
            payload = payload.get("value") or payload.get("data") or payload.get("results") or []
        if not isinstance(payload, list):
            return pd.DataFrame(), None
        frame = pd.json_normalize(payload[:SAMPLE_ROWS])
        return frame, len(payload)

    separator = "\t" if suffix == "tsv" else ","
    try:
        frame = pd.read_csv(
            path,
            sep=separator,
            nrows=SAMPLE_ROWS,
            low_memory=False,
            on_bad_lines="skip",
            encoding_errors="replace",
        )
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return pd.DataFrame(), None
    return frame, _count_lines(path, header=True)


def _pick(columns: list[str], wanted: tuple[str, ...]) -> str | None:
    lowered = {column.strip().casefold().replace(" ", "_"): column for column in columns}
    for name in wanted:
        if name in lowered:
            return lowered[name]
    return None


#: Column names that state the scale outright. Trusted over the distribution, because a
#: publisher naming a column `nrs` has told us more than its values can.
NAMED_SCALES = ((("nrs", "numeric_rating"), NRS), (("vas", "visual_analog"), VAS))


def _scale_of(values: pd.Series, column: str) -> str:
    """Infer the rating scale, from the column's name where it says, else its values.

    The distribution is read at the 1st and 99th percentile rather than at the extremes.
    Using min and max would make the scale a function of the outliers, so a column of
    0-10 ratings containing one corrupt 99 would be classified as 0-100 and that 99 would
    pass the range check it exists to fail. Percentiles let the bulk of the data decide
    what the scale is and leave the outliers to be judged against it.
    """
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return UNKNOWN_SCALE
    if numeric.nunique() <= 2 and numeric.min() >= 0 and numeric.max() <= 1:
        return BINARY

    name = column.strip().casefold().replace(" ", "_").replace("-", "_")
    for needles, scale in NAMED_SCALES:
        if any(needle in name for needle in needles):
            return scale

    low = float(numeric.quantile(0.01))
    high = float(numeric.quantile(0.99))
    if low >= 0 and high <= 10:
        return NRS
    if low >= 0 and high <= 100:
        return VAS
    return UNKNOWN_SCALE


def describe(files: tuple[Path, ...], *, declared_format: str = "") -> Profile:
    """Measure the stored files, returning what could be established and nothing more."""
    path = _largest_tabular(files)
    if path is None:
        others = sorted({p.suffix.lower().lstrip(".") for p in files if p.is_file()})
        return Profile(
            file_format=declared_format,
            notes=[
                "no tabular file was found among the stored files"
                + (f"; formats present: {', '.join(others)}" if others else "")
            ],
        )

    suffix = path.suffix.lower().lstrip(".")
    frame, total = _read_sample(path, suffix)
    profile = Profile(file=path.name, file_format=suffix, rows=total)
    if frame.empty:
        profile.notes.append(f"{path.name} could not be parsed as {suffix} or held no rows")
        return profile

    profile.sampled_rows = len(frame)
    profile.columns = [str(column) for column in frame.columns][:500]
    profile.rows = total if total is not None else len(frame)
    cells = frame.shape[0] * frame.shape[1]
    profile.missing_value_pct = (
        round(float(frame.isna().sum().sum()) / cells * 100, 4) if cells else None
    )
    profile.numeric_columns = [
        str(column)
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
    ][:200]

    profile.subject_column = _pick(profile.columns, SUBJECT_COLUMNS)
    if profile.subject_column:
        profile.subjects = int(frame[profile.subject_column].nunique(dropna=True))

    profile.target_column = _pick(profile.columns, TARGET_COLUMNS)
    if profile.target_column:
        profile.target_scale = _scale_of(frame[profile.target_column], profile.target_column)

    profile.granularity = _granularity(profile)
    if total is not None and total > profile.sampled_rows:
        profile.notes.append(
            f"column statistics were computed from the first {profile.sampled_rows:,} of "
            f"{total:,} rows"
        )
    return profile


def _granularity(profile: Profile) -> Granularity:
    """Whether rows describe people or populations.

    A subject identifier is taken as decisive. Otherwise the place-and-period column names
    are the signal: a table keyed by country and year is a population table whatever its
    title says. Neither present means unknown, which is a real answer and better than
    defaulting to the one that would let a dataset through the training gate.
    """
    if profile.subject_column:
        return Granularity.SUBJECT_LEVEL
    lowered = {column.casefold() for column in profile.columns}
    if lowered.intersection(AGGREGATE_COLUMNS):
        return Granularity.AGGREGATE
    return Granularity.UNKNOWN
