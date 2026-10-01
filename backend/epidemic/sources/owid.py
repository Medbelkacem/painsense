"""Our World in Data's mpox dataset.

OWID compiles this from the WHO mpox situation dashboard and publishes it as a CSV in a
public repository under a stated CC BY 4.0 licence, which makes it the cleanest available
route to a global mpox series: WHO's own dashboard offers no equivalent file download.

The file carries OWID's aggregate rows — continents and a world total, under `OWID_` prefixed
codes — alongside countries. Those are kept and marked, because a continent series is useful
and recomputing it from an incomplete country set would be worse than using OWID's.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.epidemic import net, paths, surveillance
from backend.epidemic.diseases import SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Source, http_date

OWID = "Our World in Data"


@dataclass(frozen=True)
class OwidMpox(Source):
    def fetch(self) -> Fetched:
        destination = paths.ensure(self.raw_dir()) / "owid-monkeypox-data.csv"
        headers = net.head(self.download_url or "", timeout=60)
        size, digest = net.download(self.download_url or "", destination)
        stamp = http_date(headers.get("last-modified"))
        return Fetched(
            files=(destination,),
            bytes=size,
            sha256=digest,
            file_format="csv",
            version=stamp,
            source_last_updated=stamp,
        )

    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / "owid-monkeypox-data.csv"
        if not path.exists():
            return None
        raw = pd.read_csv(path)
        metrics = {
            "new_cases": surveillance.NEW_CASES,
            "total_cases": surveillance.CUMULATIVE_CASES,
            "new_deaths": surveillance.NEW_DEATHS,
            "total_deaths": surveillance.CUMULATIVE_DEATHS,
        }
        available = [column for column in metrics if column in raw.columns]
        melted = raw.melt(
            id_vars=["location", "date", "iso_code"],
            value_vars=available,
            var_name="column",
            value_name="value",
        ).dropna(subset=["value"])

        aggregate = melted["iso_code"].astype("string").str.startswith("OWID_", na=False)
        out = pd.DataFrame(
            {
                "disease": "mpox",
                "dataset_id": self.dataset_id,
                "source": OWID,
                "country": melted["location"],
                # An OWID aggregate code is not an ISO 3166 code, so it is kept out of the
                # column other sources are joined on.
                "iso3": melted["iso_code"].where(~aggregate),
                "who_region": None,
                "admin_level": pd.Series(surveillance.NATIONAL, index=melted.index).where(
                    ~aggregate, surveillance.GLOBAL
                ),
                "area": None,
                "period_start": melted["date"],
                "period_end": melted["date"],
                "period_type": surveillance.DAY,
                "metric": melted["column"].map(metrics),
                "value": melted["value"],
                "observation_type": surveillance.CONFIRMED,
                "retrieved_at": _now(),
            }
        )
        return surveillance.conform(out)


def _now() -> str:
    from backend.epidemic.registry import now

    return now()


OWID_MPOX = OwidMpox(
    dataset_id="owid_mpox_daily",
    name="Mpox confirmed cases and deaths, daily by country",
    diseases=("mpox",),
    organisation=OWID,
    source_url="https://github.com/owid/monkeypox",
    download_url=(
        "https://raw.githubusercontent.com/owid/monkeypox/main/owid-monkeypox-data.csv"
    ),
    download_mechanism="the CSV the publishing repository serves at a stable path",
    dataset_type=SURVEILLANCE,
    file_format="csv",
    license="CC BY 4.0",
    license_url="https://github.com/owid/monkeypox#license",
    license_source="declared by the publisher in the repository",
    redistribution="permitted with attribution; not redistributed by this pipeline",
    features=("location", "iso_code", "date"),
    metrics=(
        surveillance.NEW_CASES,
        surveillance.CUMULATIVE_CASES,
        surveillance.NEW_DEATHS,
        surveillance.CUMULATIVE_DEATHS,
    ),
    notes=(
        "Confirmed cases as compiled from the WHO situation dashboard. Case definitions and "
        "testing capacity varied widely between countries during the 2022 outbreak, and the "
        "series begins in May 2022, so it says nothing about mpox before then."
    ),
)
