"""World Health Organization sources.

Four different WHO interfaces, because WHO does not have one:

* the Global Health Observatory OData service, for the annual country series;
* a published CSV on WHO's content delivery storage, for the COVID-19 daily file;
* the Global Tuberculosis Programme's CSV export, which names its own vintage in the
  Content-Disposition header;
* the xMart public OData service, which carries the influenza laboratory network's
  subtype-level counts.

The licence recorded for all four is WHO's own publishing policy rather than a per-dataset
statement, because that is what WHO actually publishes; `license_source` says so, so the
registry does not imply a per-dataset licence file that does not exist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd

from backend.epidemic import countries, net, paths, surveillance
from backend.epidemic.diseases import EPIDEMIOLOGICAL, LABORATORY, SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Probe, Source, http_date

WHO = "World Health Organization"
WHO_TERMS = "https://www.who.int/about/policies/publishing/copyright"
WHO_LICENCE = "WHO publishing and copyright policy (CC BY-NC-SA 3.0 IGO for GHO content)"
LICENCE_FROM_POLICY = (
    "transcribed from WHO's site-wide publishing policy; WHO does not attach a "
    "per-dataset licence file to these resources"
)

GHO_API = "https://ghoapi.azureedge.net/api"


def _retrieved() -> str:
    from backend.epidemic.registry import now

    return now()


def _frame(rows: list[dict]) -> pd.DataFrame:
    return surveillance.conform(pd.DataFrame(rows)) if rows else surveillance.empty()


# --------------------------------------------------------------------------------------
# Global Health Observatory
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GhoIndicator:
    code: str
    metric: str
    observation_type: str
    label: str


@dataclass(frozen=True)
class GhoSource(Source):
    indicators: tuple[GhoIndicator, ...] = ()

    def probe(self) -> Probe:
        """Ask the service for one row of the first indicator.

        A reachable service that returns an empty collection for an indicator is a real
        failure mode — the indicator code was retired — and is reported as unreachable
        with that reason rather than producing an empty dataset downstream.
        """
        first = self.indicators[0]
        url = f"{GHO_API}/{first.code}?$top=1"
        try:
            payload = net.get_json(url, timeout=60)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        rows = payload.get("value") or []
        if not rows:
            return Probe(False, f"indicator {first.code} returned no rows", status=200)
        return Probe(
            True,
            f"{len(self.indicators)} indicator(s) served over OData",
            status=200,
            license=WHO_LICENCE,
            license_url=WHO_TERMS,
        )

    def fetch(self) -> Fetched:
        directory = paths.ensure(self.raw_dir())
        total = 0
        files = []
        records = 0
        for indicator in self.indicators:
            rows = list(net.odata_rows(f"{GHO_API}/{indicator.code}", page=50_000, timeout=180))
            destination = directory / f"{indicator.code}.json"
            payload = json.dumps(
                {"indicator": indicator.code, "label": indicator.label, "value": rows},
                indent=1,
            )
            destination.write_text(payload, encoding="utf-8")
            total += destination.stat().st_size
            records += len(rows)
            files.append(destination)
        combined = "".join(sorted(net.sha256_of(path) for path in files))
        import hashlib

        return Fetched(
            files=tuple(files),
            bytes=total,
            sha256=hashlib.sha256(combined.encode()).hexdigest(),
            file_format="json",
            records=records,
            source_last_updated=self._latest_date(files),
        )

    @staticmethod
    def _latest_date(files: list) -> str | None:
        """GHO stamps every row with the date the value was loaded; the newest of those is
        the closest thing the service offers to a dataset update time."""
        latest = None
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("value", []):
                stamp = row.get("Date")
                if stamp and (latest is None or stamp > latest):
                    latest = stamp
        return latest

    def normalize(self) -> pd.DataFrame | None:
        directory = self.raw_dir()
        if not directory.exists():
            return None
        by_code = {indicator.code: indicator for indicator in self.indicators}
        rows: list[dict] = []
        retrieved = _retrieved()
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            indicator = by_code.get(payload.get("indicator"))
            if indicator is None:
                continue
            for row in payload.get("value", []):
                if row.get("SpatialDimType") != "COUNTRY" or row.get("TimeDimType") != "YEAR":
                    continue
                value = row.get("NumericValue")
                if value is None:
                    value = _numeric(row.get("Value"))
                year = row.get("TimeDim")
                if value is None or year is None:
                    continue
                rows.append(
                    {
                        "disease": self.diseases[0],
                        "dataset_id": self.dataset_id,
                        "source": WHO,
                        "country": row.get("SpatialDim"),
                        "iso3": row.get("SpatialDim"),
                        "who_region": row.get("ParentLocationCode"),
                        "admin_level": surveillance.NATIONAL,
                        "area": None,
                        "period_start": f"{year}-01-01",
                        "period_end": f"{year}-12-31",
                        "period_type": surveillance.YEAR,
                        "metric": indicator.metric,
                        "value": value,
                        "observation_type": indicator.observation_type,
                        "retrieved_at": retrieved,
                    }
                )
        return _frame(rows)


def _numeric(value: object) -> float | None:
    """GHO's `Value` is free text: "1268", "1 268", "<1" or a footnote marker.

    Only an unambiguous number is taken. A censored value such as "<1" is dropped rather
    than being read as 1, because the two are different claims.
    """
    if value is None:
        return None
    text = str(value).replace(" ", "").replace(" ", "").replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    return float(text)


WHO_GHO_CHOLERA = GhoSource(
    dataset_id="who_gho_cholera",
    name="Cholera reported cases, deaths and case fatality rate",
    diseases=("cholera",),
    organisation=WHO,
    source_url="https://www.who.int/data/gho/data/themes/topics/cholera",
    download_url=f"{GHO_API}/CHOLERA_0000000001",
    download_mechanism="GHO OData service, one request per indicator",
    dataset_type=SURVEILLANCE,
    file_format="json",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "who_region", "year"),
    metrics=(
        surveillance.NEW_CASES,
        surveillance.NEW_DEATHS,
        surveillance.CASE_FATALITY_PCT,
    ),
    notes=(
        "Annual figures as reported to WHO by national authorities. Reporting is known to "
        "be incomplete for cholera; an absent country-year is not evidence of no cases."
    ),
    indicators=(
        GhoIndicator(
            "CHOLERA_0000000001", surveillance.NEW_CASES, surveillance.REPORTED, "Reported cases"
        ),
        GhoIndicator(
            "CHOLERA_0000000002", surveillance.NEW_DEATHS, surveillance.REPORTED, "Reported deaths"
        ),
        GhoIndicator(
            "CHOLERA_0000000003",
            surveillance.CASE_FATALITY_PCT,
            surveillance.REPORTED,
            "Case fatality rate",
        ),
    ),
)

WHO_GHO_MEASLES = GhoSource(
    dataset_id="who_gho_measles",
    name="Measles reported cases with first- and second-dose vaccine coverage",
    diseases=("measles",),
    organisation=WHO,
    source_url="https://www.who.int/data/gho/data/themes/immunization",
    download_url=f"{GHO_API}/WHS3_62",
    download_mechanism="GHO OData service, one request per indicator",
    dataset_type=SURVEILLANCE,
    file_format="json",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "who_region", "year"),
    metrics=(surveillance.NEW_CASES, surveillance.VACCINE_COVERAGE_PCT),
    notes=(
        "Case counts and coverage are on the same country-year grid, which is what makes "
        "the two readable together. Coverage is an administrative estimate, not a survey."
    ),
    indicators=(
        GhoIndicator(
            "WHS3_62", surveillance.NEW_CASES, surveillance.REPORTED, "Reported cases"
        ),
        GhoIndicator(
            "WHS8_110",
            surveillance.VACCINE_COVERAGE_PCT,
            surveillance.COVERAGE,
            "MCV1 coverage among one-year-olds",
        ),
        GhoIndicator(
            "MCV2",
            surveillance.VACCINE_COVERAGE_PCT,
            surveillance.COVERAGE,
            "MCV2 coverage at the nationally recommended age",
        ),
    ),
)

WHO_GHO_MENINGITIS = GhoSource(
    dataset_id="who_gho_meningitis",
    name="Suspected meningitis cases, deaths and epidemic districts",
    diseases=("meningococcal_meningitis",),
    organisation=WHO,
    source_url="https://www.who.int/data/gho/data/themes/topics/meningitis",
    download_url=f"{GHO_API}/MENING_2",
    download_mechanism="GHO OData service, one request per indicator",
    dataset_type=SURVEILLANCE,
    file_format="json",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "who_region", "year"),
    metrics=(
        surveillance.NEW_CASES,
        surveillance.NEW_DEATHS,
        surveillance.EPIDEMIC_DISTRICTS,
    ),
    notes=(
        "These are suspected cases under the enhanced surveillance used in the African "
        "meningitis belt, not laboratory-confirmed meningococcal disease. The observation "
        "type records that, and the two must not be added together."
    ),
    indicators=(
        GhoIndicator(
            "MENING_2", surveillance.NEW_CASES, surveillance.SUSPECTED, "Suspected cases"
        ),
        GhoIndicator(
            "MENING_1", surveillance.NEW_DEATHS, surveillance.SUSPECTED, "Suspected deaths"
        ),
        GhoIndicator(
            "MENING_3",
            surveillance.EPIDEMIC_DISTRICTS,
            surveillance.REPORTED,
            "Districts in epidemic",
        ),
    ),
)


# --------------------------------------------------------------------------------------
# COVID-19 daily global file
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhoCovidDaily(Source):
    def fetch(self) -> Fetched:
        destination = paths.ensure(self.raw_dir()) / "WHO-COVID-19-global-daily-data.csv"
        headers = net.head(self.download_url or "")
        size, digest = net.download(self.download_url or "", destination)
        return Fetched(
            files=(destination,),
            bytes=size,
            sha256=digest,
            file_format="csv",
            version=http_date(headers.get("last-modified")),
            source_last_updated=http_date(headers.get("last-modified")),
        )

    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / "WHO-COVID-19-global-daily-data.csv"
        if not path.exists():
            return None
        raw = pd.read_csv(path, dtype={"Country_code": "string"})
        melted = raw.melt(
            id_vars=["Date_reported", "Country_code", "Country", "WHO_region"],
            value_vars=["New_cases", "Cumulative_cases", "New_deaths", "Cumulative_deaths"],
            var_name="column",
            value_name="value",
        ).dropna(subset=["value"])
        metrics = {
            "New_cases": surveillance.NEW_CASES,
            "Cumulative_cases": surveillance.CUMULATIVE_CASES,
            "New_deaths": surveillance.NEW_DEATHS,
            "Cumulative_deaths": surveillance.CUMULATIVE_DEATHS,
        }
        out = pd.DataFrame(
            {
                "disease": "covid19",
                "dataset_id": self.dataset_id,
                "source": WHO,
                "country": melted["Country"],
                "iso3": melted["Country_code"].map(countries.to_iso3),
                "who_region": melted["WHO_region"],
                "admin_level": surveillance.NATIONAL,
                "area": None,
                "period_start": melted["Date_reported"],
                "period_end": melted["Date_reported"],
                "period_type": surveillance.DAY,
                "metric": melted["column"].map(metrics),
                "value": melted["value"],
                # WHO's file is what member states reported, with no separation of
                # laboratory-confirmed from clinically diagnosed, so `reported` is the
                # only claim it supports.
                "observation_type": surveillance.REPORTED,
                "retrieved_at": _retrieved(),
            }
        )
        return surveillance.conform(out)


WHO_COVID_DAILY = WhoCovidDaily(
    dataset_id="who_covid_daily",
    name="COVID-19 cases and deaths reported to WHO, daily by country",
    diseases=("covid19",),
    organisation=WHO,
    source_url="https://data.who.int/dashboards/covid19/data",
    download_url=(
        "https://srhdpeuwpubsa.blob.core.windows.net/whdh/COVID/"
        "WHO-COVID-19-global-daily-data.csv"
    ),
    download_mechanism="the CSV the COVID-19 dashboard links as its own download",
    dataset_type=SURVEILLANCE,
    file_format="csv",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("date_reported", "country", "iso3", "who_region"),
    metrics=(
        surveillance.NEW_CASES,
        surveillance.CUMULATIVE_CASES,
        surveillance.NEW_DEATHS,
        surveillance.CUMULATIVE_DEATHS,
    ),
    notes=(
        "Reporting cadence changed repeatedly over the pandemic and many countries moved "
        "to weekly or monthly reporting, which shows up as runs of zeros followed by a "
        "spike. The daily series is historical and is not a live feed."
    ),
)


# --------------------------------------------------------------------------------------
# Global Tuberculosis Programme
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhoTme(Source):
    """A Global TB Programme CSV export.

    `columns` maps a column in the export onto a metric. Anything not named is left in the
    raw file and ignored; the exports carry well over a hundred columns and most of them
    are the low and high bounds of an interval this schema has nowhere to put.
    """

    filename: str = "export.csv"
    columns: tuple[tuple[str, str, str], ...] = ()

    def probe(self) -> Probe:
        try:
            headers = net.head(self.download_url or "", timeout=120)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        return Probe(
            True,
            f"HTTP {headers.get('status')}, {headers.get('content-disposition', 'no filename')}",
            status=int(headers.get("status", 0)) or None,
            license=WHO_LICENCE,
            license_url=WHO_TERMS,
            source_last_updated=_vintage(headers.get("content-disposition")),
        )

    def fetch(self) -> Fetched:
        destination = paths.ensure(self.raw_dir()) / self.filename
        headers = net.head(self.download_url or "", timeout=120)
        size, digest = net.download(self.download_url or "", destination)
        vintage = _vintage(headers.get("content-disposition"))
        return Fetched(
            files=(destination,),
            bytes=size,
            sha256=digest,
            file_format="csv",
            version=vintage,
            source_last_updated=vintage,
        )

    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / self.filename
        if not path.exists():
            return None
        raw = pd.read_csv(path, low_memory=False)
        present = [(column, m, t) for column, m, t in self.columns if column in raw.columns]
        if not present:
            return surveillance.empty()
        rows = []
        retrieved = _retrieved()
        for column, metric, observation_type in present:
            block = raw[["country", "iso3", "g_whoregion", "year", column]].dropna(
                subset=[column]
            )
            rows.append(
                pd.DataFrame(
                    {
                        "disease": "tuberculosis",
                        "dataset_id": self.dataset_id,
                        "source": WHO,
                        "country": block["country"],
                        "iso3": block["iso3"],
                        "who_region": block["g_whoregion"],
                        "admin_level": surveillance.NATIONAL,
                        "area": None,
                        "period_start": block["year"].astype(int).astype(str) + "-01-01",
                        "period_end": block["year"].astype(int).astype(str) + "-12-31",
                        "period_type": surveillance.YEAR,
                        "metric": metric,
                        "value": block[column],
                        "observation_type": observation_type,
                        "retrieved_at": retrieved,
                    }
                )
            )
        return surveillance.conform(pd.concat(rows, ignore_index=True))


def _vintage(disposition: str | None) -> str | None:
    """The TB exports do not send Last-Modified, but they name the vintage in the
    attachment filename: `TB_burden_countries_2026-10-01.csv`."""
    if not disposition:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})", disposition)
    return match.group(1) if match else None


WHO_TB_BURDEN = WhoTme(
    dataset_id="who_tb_burden",
    name="WHO estimates of tuberculosis incidence and mortality by country",
    diseases=("tuberculosis",),
    organisation=WHO,
    source_url="https://www.who.int/teams/global-programme-on-tuberculosis-and-lung-health/data",
    download_url="https://extranet.who.int/tme/generateCSV.asp?ds=estimates",
    download_mechanism="the CSV export the Global TB Programme data page offers",
    dataset_type=EPIDEMIOLOGICAL,
    file_format="csv",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "g_whoregion", "year", "e_pop_num"),
    metrics=(
        surveillance.INCIDENCE_PER_100K,
        surveillance.MORTALITY_PER_100K,
        surveillance.CASE_FATALITY_PCT,
    ),
    notes=(
        "Every figure in this file is a model output with a published uncertainty interval, "
        "not a count of notified cases. It is stored with observation_type 'estimated' and "
        "the dashboard never presents it as a reported case count."
    ),
    filename="TB_burden_countries.csv",
    columns=(
        ("e_inc_100k", surveillance.INCIDENCE_PER_100K, surveillance.ESTIMATED),
        ("e_mort_100k", surveillance.MORTALITY_PER_100K, surveillance.ESTIMATED),
        ("cfr_pct", surveillance.CASE_FATALITY_PCT, surveillance.ESTIMATED),
    ),
)

WHO_TB_OUTCOMES = WhoTme(
    dataset_id="who_tb_outcomes",
    name="WHO tuberculosis treatment outcomes and notified cases by country",
    diseases=("tuberculosis",),
    organisation=WHO,
    source_url="https://www.who.int/teams/global-programme-on-tuberculosis-and-lung-health/data",
    download_url="https://extranet.who.int/tme/generateCSV.asp?ds=outcomes",
    download_mechanism="the CSV export the Global TB Programme data page offers",
    dataset_type=SURVEILLANCE,
    file_format="csv",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "g_whoregion", "year", "newrel_coh"),
    metrics=(surveillance.TREATMENT_SUCCESS_PCT,),
    notes=(
        "`c_new_tsr` is the share of the new-and-relapse treatment cohort with a successful "
        "outcome, which WHO reports a year behind the notification year because a cohort "
        "has to finish treatment before it can be evaluated."
    ),
    filename="TB_outcomes.csv",
    columns=(("c_new_tsr", surveillance.TREATMENT_SUCCESS_PCT, surveillance.REPORTED),),
)


# --------------------------------------------------------------------------------------
# Global influenza surveillance (FluNet, over the public xMart service)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhoFluNet(Source):
    def probe(self) -> Probe:
        try:
            payload = net.get_json(f"{self.download_url}&$top=1", timeout=90)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        rows = payload.get("value") or []
        if not rows:
            return Probe(False, "the FLUMART view returned no rows", status=200)
        return Probe(
            True,
            "xMart OData view reachable",
            status=200,
            license=WHO_LICENCE,
            license_url=WHO_TERMS,
        )

    def fetch(self) -> Fetched:
        destination = paths.ensure(self.raw_dir()) / "VIW_FNT.csv"
        rows = list(net.odata_rows(self.download_url or "", page=40_000, timeout=300))
        frame = pd.DataFrame(rows)
        frame.to_csv(destination, index=False)
        return Fetched(
            files=(destination,),
            bytes=destination.stat().st_size,
            sha256=net.sha256_of(destination),
            file_format="csv",
            records=len(frame),
            source_last_updated=(
                str(frame["ISO_WEEKSTARTDATE"].max()) if "ISO_WEEKSTARTDATE" in frame else None
            ),
        )

    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / "VIW_FNT.csv"
        if not path.exists():
            return None
        raw = pd.read_csv(path, low_memory=False)
        start = pd.to_datetime(raw["ISO_WEEKSTARTDATE"], errors="coerce")
        base = pd.DataFrame(
            {
                "disease": "influenza_h1n1",
                "dataset_id": self.dataset_id,
                "source": WHO,
                "country": raw["COUNTRY_AREA_TERRITORY"],
                "iso3": raw["COUNTRY_CODE"],
                "who_region": raw["WHOREGION"],
                "admin_level": surveillance.NATIONAL,
                "area": None,
                "period_start": start,
                "period_end": start + pd.Timedelta(days=6),
                "period_type": surveillance.WEEK,
                "retrieved_at": _retrieved(),
            }
        )
        blocks = []
        for column, metric, observation_type in (
            ("AH1N12009", surveillance.LAB_CONFIRMED, surveillance.CONFIRMED),
            ("SPEC_PROCESSED_NB", surveillance.SPECIMENS_PROCESSED, surveillance.REPORTED),
        ):
            if column not in raw.columns:
                continue
            block = base.copy()
            block["metric"] = metric
            block["value"] = pd.to_numeric(raw[column], errors="coerce")
            block["observation_type"] = observation_type
            blocks.append(block.dropna(subset=["value"]))
        if not blocks:
            return surveillance.empty()
        return surveillance.conform(pd.concat(blocks, ignore_index=True))


WHO_FLUNET = WhoFluNet(
    dataset_id="who_flunet_h1n1",
    name="FluNet laboratory-confirmed influenza A(H1N1)pdm09 detections by country and week",
    diseases=("influenza_h1n1",),
    organisation=WHO,
    source_url="https://www.who.int/tools/flunet",
    download_url=(
        "https://xmart-api-public.who.int/FLUMART/VIW_FNT?$select="
        "WHOREGION,COUNTRY_CODE,COUNTRY_AREA_TERRITORY,ISO_WEEKSTARTDATE,ISO_YEAR,ISO_WEEK,"
        "AH1N12009,INF_A,INF_ALL,SPEC_PROCESSED_NB"
    ),
    download_mechanism="public xMart OData service, paged with $top and $skip",
    dataset_type=LABORATORY,
    file_format="csv",
    license=WHO_LICENCE,
    license_url=WHO_TERMS,
    license_source=LICENCE_FROM_POLICY,
    features=("country", "iso3", "who_region", "iso_year", "iso_week", "specimens_processed"),
    metrics=(surveillance.LAB_CONFIRMED, surveillance.SPECIMENS_PROCESSED),
    notes=(
        "A detection count without its denominator is uninterpretable, so the number of "
        "specimens processed is collected alongside it: a rise in positives can be a rise "
        "in testing. Sentinel laboratory coverage differs greatly between countries, so "
        "counts are not comparable across countries without that caveat."
    ),
)
