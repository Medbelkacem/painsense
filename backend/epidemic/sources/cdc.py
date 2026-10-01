"""US Centers for Disease Control and Prevention, over the Socrata open data service.

Two datasets with very different shapes:

`NNDSS Weekly Data` is the national notifiable diseases table — one row per reporting area,
MMWR week and condition. It is the only automatic source this pipeline found for Ebola and
Lassa, where it records that the US saw no cases, which is a real surveillance observation
even though it is a run of zeros.

`COVID-19 Case Surveillance Public Use Data` is one row per reported case with the
demographic fields CDC releases publicly, plus hospitalisation, ICU and death indicators.
It is the only patient-level labelled dataset obtained for any of the ten diseases, and it
is what `app.epidemic.clinical` builds a model on.

Licence and last-update time are read from the Socrata view metadata rather than asserted
here, so the registry records what the publisher currently says.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.epidemic import net, paths, surveillance
from backend.epidemic.diseases import CLINICAL, SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Probe, Source, epoch_to_iso

CDC = "Centers for Disease Control and Prevention"
DOMAIN = "https://data.cdc.gov"

#: Per-dataset licence fields on this domain are often null. Where that happens the
#: registry records the domain-wide position with this note attached, so it is clear the
#: statement came from the site policy and not from the dataset's own metadata.
DOMAIN_LICENCE = "Public Domain U.S. Government"
DOMAIN_TERMS = "https://www.usa.gov/government-works"
LICENCE_FROM_DOMAIN = (
    "the dataset's own Socrata metadata declares no licence; recorded from the "
    "data.cdc.gov domain position for US Government works"
)


def _view(identifier: str) -> dict:
    return net.get_json(f"{DOMAIN}/api/views/{identifier}.json", timeout=60)


@dataclass(frozen=True)
class SocrataSource(Source):
    identifier: str = ""
    order_by: str = ":id"
    select: str | None = None
    where: str | None = None
    row_cap: int | None = None

    @property
    def resource_url(self) -> str:
        return f"{DOMAIN}/resource/{self.identifier}.json"

    def probe(self) -> Probe:
        try:
            view = _view(self.identifier)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        licence = (view.get("license") or {}).get("name") or DOMAIN_LICENCE
        terms = (view.get("license") or {}).get("termsLink") or DOMAIN_TERMS
        rows = None
        for key in ("rowsCount", "cachedContents"):
            value = view.get(key)
            if isinstance(value, dict):
                rows = value.get("non_null") or value.get("count")
            elif isinstance(value, int):
                rows = value
            if rows:
                break
        return Probe(
            True,
            f"Socrata view '{view.get('name', self.identifier)}' reachable",
            status=200,
            source_last_updated=epoch_to_iso(view.get("rowsUpdatedAt")),
            license=licence,
            license_url=terms,
            records_claimed=int(rows) if rows else None,
        )

    def fetch(self) -> Fetched:
        destination = paths.ensure(self.raw_dir()) / f"{self.identifier}.csv"
        try:
            view = _view(self.identifier)
        except net.Unreachable:
            view = {}
        rows = list(
            net.socrata_rows(
                self.resource_url,
                select=self.select,
                where=self.where,
                order=self.order_by,
                limit=self.row_cap,
                timeout=300,
            )
        )
        frame = pd.DataFrame(rows)
        frame.to_csv(destination, index=False)
        return Fetched(
            files=(destination,),
            bytes=destination.stat().st_size,
            sha256=net.sha256_of(destination),
            file_format="csv",
            records=len(frame),
            version=epoch_to_iso(view.get("rowsUpdatedAt")),
            source_last_updated=epoch_to_iso(view.get("rowsUpdatedAt")),
        )


# --------------------------------------------------------------------------------------
# Notifiable diseases
# --------------------------------------------------------------------------------------

#: NNDSS condition label to disease code.
#:
#: Two labels that look like matches are deliberately absent. "Novel Influenza A virus
#: infections" counts non-seasonal subtypes — H5, H7 and swine-variant viruses — and not
#: A(H1N1)pdm09, which has been a seasonal subtype since 2010; FluNet is the source for
#: that. "COVID-19-associated pediatric mortality" is a paediatric-only death count and
#: would be read as a national death count if it were mapped onto one.
NNDSS_CONDITIONS: dict[str, tuple[str, str]] = {
    "Tuberculosis": ("tuberculosis", surveillance.CONFIRMED),
    "Measles, Indigenous": ("measles", surveillance.CONFIRMED),
    "Measles, Imported": ("measles", surveillance.CONFIRMED),
    "Cholera": ("cholera", surveillance.CONFIRMED),
    "Dengue virus infections, Dengue": ("dengue", surveillance.CONFIRMED),
    "Dengue virus infections, Severe dengue": ("dengue", surveillance.CONFIRMED),
    "Dengue virus infections, Dengue-like illness": ("dengue", surveillance.SUSPECTED),
    "Meningococcal disease, All serogroups": (
        "meningococcal_meningitis",
        surveillance.CONFIRMED,
    ),
    "Mpox": ("mpox", surveillance.CONFIRMED),
    "Viral hemorrhagic fevers, Ebola virus": ("ebola", surveillance.CONFIRMED),
    "Viral hemorrhagic fevers, Lassa virus": ("lassa", surveillance.CONFIRMED),
}

#: Reporting areas in the NNDSS table that are census groupings rather than states. They
#: are kept, because dropping them loses the only regional view the table offers, but they
#: are marked `regional` so that nothing sums across admin levels and double counts.
NNDSS_GROUPINGS = frozenset(
    {
        "NEW ENGLAND",
        "MIDDLE ATLANTIC",
        "EAST NORTH CENTRAL",
        "WEST NORTH CENTRAL",
        "SOUTH ATLANTIC",
        "EAST SOUTH CENTRAL",
        "WEST SOUTH CENTRAL",
        "MOUNTAIN",
        "PACIFIC",
        "US TERRITORIES",
        "NON-US RESIDENTS",
    }
)
NNDSS_NATIONAL = frozenset({"UNITED STATES", "US RESIDENTS", "TOTAL"})


@dataclass(frozen=True)
class NndssSource(SocrataSource):
    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / f"{self.identifier}.csv"
        if not path.exists():
            return None
        raw = pd.read_csv(path, low_memory=False)
        wanted = raw[raw["label"].isin(NNDSS_CONDITIONS)].copy()
        if wanted.empty:
            return surveillance.empty()

        wanted["disease"] = wanted["label"].map(lambda key: NNDSS_CONDITIONS[key][0])
        wanted["observation_type"] = wanted["label"].map(lambda key: NNDSS_CONDITIONS[key][1])
        wanted["value"] = pd.to_numeric(wanted.get("m1"), errors="coerce")
        wanted = wanted.dropna(subset=["value", "year", "week"])

        # An MMWR week starts on the Sunday of that week. Pandas understands the ISO week
        # directive, and MMWR week 1 and ISO week 1 differ by at most a day for the
        # purpose of a weekly series, so the ISO calendar is used and the cadence recorded.
        start = pd.to_datetime(
            wanted["year"].astype(int).astype(str)
            + "-W"
            + wanted["week"].astype(int).astype(str).str.zfill(2)
            + "-1",
            format="%G-W%V-%u",
            errors="coerce",
        ) - pd.Timedelta(days=1)

        area = wanted["states"].astype(str).str.strip().str.upper()
        level = pd.Series(surveillance.SUBNATIONAL, index=wanted.index, dtype="object")
        level[area.isin(NNDSS_GROUPINGS)] = surveillance.REGIONAL
        level[area.isin(NNDSS_NATIONAL)] = surveillance.NATIONAL

        out = pd.DataFrame(
            {
                "disease": wanted["disease"],
                "dataset_id": self.dataset_id,
                "source": CDC,
                "country": "United States of America",
                "iso3": "USA",
                "who_region": "AMR",
                "admin_level": level,
                "area": wanted["states"].where(level != surveillance.NATIONAL),
                "period_start": start,
                "period_end": start + pd.Timedelta(days=6),
                "period_type": surveillance.WEEK,
                "metric": surveillance.NEW_CASES,
                "value": wanted["value"],
                "observation_type": wanted["observation_type"],
                "retrieved_at": _now(),
            }
        ).dropna(subset=["period_start"])
        return surveillance.conform(out)


def _now() -> str:
    from backend.epidemic.registry import now

    return now()


CDC_NNDSS_WEEKLY = NndssSource(
    dataset_id="cdc_nndss_weekly",
    name="NNDSS weekly provisional counts of nationally notifiable conditions",
    diseases=(
        "tuberculosis",
        "measles",
        "cholera",
        "dengue",
        "meningococcal_meningitis",
        "mpox",
        "ebola",
        "lassa",
    ),
    organisation=CDC,
    source_url="https://data.cdc.gov/d/x9gk-5huc",
    download_url=f"{DOMAIN}/resource/x9gk-5huc.json",
    download_mechanism="Socrata SODA 2.1 resource endpoint, paged with $limit and $offset",
    dataset_type=SURVEILLANCE,
    file_format="csv",
    license=DOMAIN_LICENCE,
    license_url=DOMAIN_TERMS,
    license_source=LICENCE_FROM_DOMAIN,
    features=("reporting_area", "mmwr_year", "mmwr_week", "condition"),
    metrics=(surveillance.NEW_CASES,),
    notes=(
        "Provisional counts, revised in later weeks. A zero means no case was reported to "
        "CDC that week, which for Ebola and Lassa is the normal state and is still an "
        "observation. Counts for census divisions and for the national total are both in "
        "the table, so admin_level has to be respected or the same case is counted twice."
    ),
    identifier="x9gk-5huc",
    order_by="sort_order",
    select="states,year,week,label,m1,m2,m3,m4",
)


# --------------------------------------------------------------------------------------
# COVID-19 case surveillance (patient level)
# --------------------------------------------------------------------------------------

CDC_COVID_CASE_SURVEILLANCE = SocrataSource(
    dataset_id="cdc_covid_case_surveillance",
    name="COVID-19 Case Surveillance Public Use Data",
    diseases=("covid19",),
    organisation=CDC,
    source_url="https://data.cdc.gov/d/vbim-akqf",
    download_url=f"{DOMAIN}/resource/vbim-akqf.json",
    download_mechanism=(
        "Socrata SODA 2.1 resource endpoint, paged with $limit and $offset and ordered by "
        "the case date so a run is reproducible"
    ),
    dataset_type=CLINICAL,
    file_format="csv",
    license=DOMAIN_LICENCE,
    license_url=DOMAIN_TERMS,
    license_source="read from the dataset's own Socrata metadata",
    features=(
        "age_group",
        "sex",
        "race_ethnicity_combined",
        "medcond_yn",
        "current_status",
        "onset_to_report_days",
        "case_month",
    ),
    target_labels=("hosp_yn", "icu_yn", "death_yn"),
    notes=(
        "Deidentified, one row per reported case. There are no symptoms in this file: the "
        "public release carries demographics, a single flag for the presence of any "
        "underlying condition, and the three outcome indicators. Most rows have 'Missing' "
        "or 'Unknown' for the outcomes, so a model can only be trained on the subset where "
        "the outcome is actually recorded, and that subset is not a random sample of cases."
    ),
    identifier="vbim-akqf",
    order_by="cdc_case_earliest_dt",
    select=(
        "cdc_case_earliest_dt,cdc_report_dt,onset_dt,current_status,sex,age_group,"
        "race_ethnicity_combined,hosp_yn,icu_yn,death_yn,medcond_yn"
    ),
    # The full release is tens of millions of rows. The cap is a deliberate, recorded
    # sampling decision rather than a limit of the interface, and `ingest` writes the cap
    # into the registry note so the row count is never read as the whole file.
    row_cap=600_000,
)
