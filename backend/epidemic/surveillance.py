"""One schema for every surveillance series this pipeline collects.

The sources disagree about almost everything: WHO's COVID file is daily by country, the
influenza network reports ISO weeks, the Global Health Observatory is annual, OpenDengue
publishes a date range per record, and the US notifiable tables are MMWR weeks. They also
disagree about what a number *means* — a modelled tuberculosis incidence and a count of
reported cholera cases are not the same kind of fact.

So the table is long rather than wide, and carries two discriminators the sources
themselves only imply:

`observation_type` separates a confirmed count from a suspected count from a modelled
estimate. The dashboard never adds across it, and `REPORTED_TYPES` is the set that may be
described as a reported case count.

`period_type` records the reporting cadence, so a yearly figure is never plotted as though
it were a daily one, and `period_start`/`period_end` make the interval explicit instead of
leaving it to be inferred from the cadence.
"""

from __future__ import annotations

import pandas as pd

# Metrics. The vocabulary is closed on purpose: a normalizer that wants to emit something
# new has to add it here, which is the moment to decide what unit it carries and whether
# the dashboard may sum it.
NEW_CASES = "new_cases"
CUMULATIVE_CASES = "cumulative_cases"
NEW_DEATHS = "new_deaths"
CUMULATIVE_DEATHS = "cumulative_deaths"
LAB_CONFIRMED = "lab_confirmed_cases"
SPECIMENS_PROCESSED = "specimens_processed"
INCIDENCE_PER_100K = "incidence_per_100k"
MORTALITY_PER_100K = "mortality_per_100k"
CASE_FATALITY_PCT = "case_fatality_pct"
TREATMENT_SUCCESS_PCT = "treatment_success_pct"
VACCINE_COVERAGE_PCT = "vaccine_coverage_pct"
EPIDEMIC_DISTRICTS = "epidemic_districts"

COUNT = "count"
PER_100K = "per_100000"
PERCENT = "percent"

METRIC_UNITS = {
    NEW_CASES: COUNT,
    CUMULATIVE_CASES: COUNT,
    NEW_DEATHS: COUNT,
    CUMULATIVE_DEATHS: COUNT,
    LAB_CONFIRMED: COUNT,
    SPECIMENS_PROCESSED: COUNT,
    EPIDEMIC_DISTRICTS: COUNT,
    INCIDENCE_PER_100K: PER_100K,
    MORTALITY_PER_100K: PER_100K,
    CASE_FATALITY_PCT: PERCENT,
    TREATMENT_SUCCESS_PCT: PERCENT,
    VACCINE_COVERAGE_PCT: PERCENT,
}

#: Metrics that accumulate, so that a figure for a period is the period's last value and
#: never the sum of the periods inside it.
CUMULATIVE_METRICS = frozenset({CUMULATIVE_CASES, CUMULATIVE_DEATHS})

#: Metrics that are a rate or a proportion. Averaging them across countries without
#: weighting by population is misleading, so the dashboard reports them per country only.
RATE_METRICS = frozenset(
    {
        INCIDENCE_PER_100K,
        MORTALITY_PER_100K,
        CASE_FATALITY_PCT,
        TREATMENT_SUCCESS_PCT,
        VACCINE_COVERAGE_PCT,
    }
)

# How the number came to exist.
CONFIRMED = "confirmed"
PROBABLE = "probable"
SUSPECTED = "suspected"
REPORTED = "reported"
ESTIMATED = "estimated"
COVERAGE = "coverage"

OBSERVATION_TYPES = (CONFIRMED, PROBABLE, SUSPECTED, REPORTED, ESTIMATED, COVERAGE)

#: The observation types that may be presented as a case count a health authority reported.
#: `ESTIMATED` is excluded: WHO's tuberculosis incidence is a model output with a confidence
#: interval, and presenting it beside a notification count without saying so overstates both.
REPORTED_TYPES = frozenset({CONFIRMED, PROBABLE, SUSPECTED, REPORTED})

DAY = "day"
WEEK = "week"
MONTH = "month"
YEAR = "year"
RANGE = "range"

PERIOD_TYPES = (DAY, WEEK, MONTH, YEAR, RANGE)

NATIONAL = "national"
SUBNATIONAL = "subnational"
REGIONAL = "regional"
GLOBAL = "global"

COLUMNS: dict[str, str] = {
    "disease": "string",
    "dataset_id": "string",
    "source": "string",
    "country": "string",
    "iso3": "string",
    "who_region": "string",
    "admin_level": "string",
    "area": "string",
    "period_start": "datetime64[ns]",
    "period_end": "datetime64[ns]",
    "period_type": "string",
    "metric": "string",
    "value": "float64",
    "unit": "string",
    "observation_type": "string",
    "retrieved_at": "string",
}

KEY_COLUMNS = (
    "disease",
    "dataset_id",
    "iso3",
    "country",
    "area",
    "period_start",
    "period_end",
    "metric",
    "observation_type",
)


class SchemaError(ValueError):
    pass


def empty() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in COLUMNS.items()})


def conform(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce a normalizer's output onto the schema, rejecting anything undeclared.

    Vocabulary violations raise rather than being dropped: a metric name this module does
    not know is a bug in the normalizer, and silently discarding those rows would make a
    series look shorter than the source without saying why.
    """
    missing = [name for name in COLUMNS if name not in frame.columns and name != "area"]
    if missing:
        raise SchemaError(f"normalized frame is missing {', '.join(missing)}")

    out = frame.copy()
    if "area" not in out.columns:
        out["area"] = pd.NA

    for column, kind in (
        ("metric", METRIC_UNITS),
        ("observation_type", set(OBSERVATION_TYPES)),
        ("period_type", set(PERIOD_TYPES)),
    ):
        unknown = sorted(set(out[column].dropna().unique()) - set(kind))
        if unknown:
            raise SchemaError(f"unknown {column} value(s): {', '.join(map(str, unknown))}")

    out["unit"] = out["metric"].map(METRIC_UNITS).astype("string")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    for column in ("period_start", "period_end"):
        out[column] = pd.to_datetime(out[column], errors="coerce")

    out = out[out["value"].notna() & out["period_start"].notna()]
    for name, dtype in COLUMNS.items():
        if dtype == "string":
            out[name] = out[name].astype("string")
    return out[list(COLUMNS)].reset_index(drop=True)


def deduplicate(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop exact repeats of the same observation.

    Two sources reporting the same country-week differently is not a duplicate and is kept;
    both carry their `dataset_id`, and the dashboard picks one series per metric rather
    than averaging them. Only an identical key is collapsed, keeping the last row, which
    is how a re-download of a revised file supersedes the earlier value.
    """
    before = len(frame)
    kept = frame.drop_duplicates(subset=list(KEY_COLUMNS), keep="last")
    return kept.reset_index(drop=True), before - len(kept)
