"""Ebola case and death counts from the 2014-2016 West African epidemic.

WHO published these in its situation reports, which are documents. The numbers were
transcribed into a machine-readable time series by a third party and that transcription is
what is reachable; WHO itself offers no Ebola indicator in the Global Health Observatory
and no CSV export for the sitrep series.

The transcription repository declares no licence. GitHub's licence endpoint answers
NOASSERTION for it, which means no redistribution right has been granted, so this adapter
refuses to fetch unless a reviewer passes `--accept-undeclared-license` with a reason. The
refusal and the reason both go into the acquisition log. The rule is the same one the pain
dataset pipeline next door applies to a Kaggle licence flagged for review: a dataset whose
terms have not been read by a person is not quietly downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.epidemic import net, paths, surveillance
from backend.epidemic.diseases import SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Probe, Refused, Source

PUBLISHER = "WHO situation reports (via the cmrivers/ebola transcription)"

#: The file holds one column per country per measure, named `Cases_Guinea`,
#: `Deaths_Liberia` and so on, with a handful of city-level columns mixed in.
COUNTRY_ISO3 = {
    "Guinea": "GIN",
    "Liberia": "LBR",
    "SierraLeone": "SLE",
    "Nigeria": "NGA",
    "Senegal": "SEN",
    "UnitedStates": "USA",
    "Spain": "ESP",
    "Mali": "MLI",
    "Guinea2": None,
    "Liberia2": None,
}
DISPLAY_NAMES = {
    "SierraLeone": "Sierra Leone",
    "UnitedStates": "United States of America",
}


@dataclass(frozen=True)
class EbolaSitrepSeries(Source):
    accepted_reason: str | None = None

    def probe(self) -> Probe:
        try:
            headers = net.head(self.download_url or "", timeout=60)
        except net.Unreachable as exc:
            return Probe(False, str(exc), status=exc.status)
        return Probe(
            True,
            f"HTTP {headers.get('status')}; licence review is still required before fetching",
            status=int(headers.get("status", 0)) or None,
        )

    def fetch(self) -> Fetched:
        if not self.accepted_reason:
            raise Refused(
                "the transcription repository declares no licence (GitHub reports "
                "NOASSERTION). Re-run with --accept-undeclared-license and a reason to "
                "record the review, or import the sitrep figures manually."
            )
        destination = paths.ensure(self.raw_dir()) / "country_timeseries.csv"
        size, digest = net.download(self.download_url or "", destination)
        return Fetched(
            files=(destination,),
            bytes=size,
            sha256=digest,
            file_format="csv",
            version="2015-12-15",
        )

    def normalize(self) -> pd.DataFrame | None:
        path = self.raw_dir() / "country_timeseries.csv"
        if not path.exists():
            return None
        raw = pd.read_csv(path)
        date = pd.to_datetime(raw["Date"], format="%m/%d/%Y", errors="coerce")
        rows = []
        for column in raw.columns:
            measure, _, suffix = column.partition("_")
            if measure not in ("Cases", "Deaths") or suffix not in COUNTRY_ISO3:
                continue
            # The `Guinea2`/`Liberia2` columns are the sitreps' patient-database counts for
            # the same country, published next to the sitrep counts. Two counts of the same
            # thing cannot both be loaded without double counting, so only the sitrep
            # column is taken.
            if suffix.endswith("2"):
                continue
            values = pd.to_numeric(raw[column], errors="coerce")
            frame = pd.DataFrame(
                {
                    "disease": "ebola",
                    "dataset_id": self.dataset_id,
                    "source": PUBLISHER,
                    "country": DISPLAY_NAMES.get(suffix, suffix),
                    "iso3": COUNTRY_ISO3[suffix],
                    "who_region": None,
                    "admin_level": surveillance.NATIONAL,
                    "area": None,
                    "period_start": date,
                    "period_end": date,
                    "period_type": surveillance.DAY,
                    "metric": (
                        surveillance.CUMULATIVE_CASES
                        if measure == "Cases"
                        else surveillance.CUMULATIVE_DEATHS
                    ),
                    "value": values,
                    # Sitrep totals combined confirmed, probable and suspected cases under
                    # one figure throughout the epidemic.
                    "observation_type": surveillance.PROBABLE,
                    "retrieved_at": _now(),
                }
            )
            rows.append(frame.dropna(subset=["value", "period_start"]))
        if not rows:
            return surveillance.empty()
        return surveillance.conform(pd.concat(rows, ignore_index=True))


def _now() -> str:
    from backend.epidemic.registry import now

    return now()


WHO_EBOLA_SITREPS = EbolaSitrepSeries(
    dataset_id="who_ebola_sitreps_2014",
    name="Ebola virus disease cumulative cases and deaths, 2014-2016 West African epidemic",
    diseases=("ebola",),
    organisation=PUBLISHER,
    source_url="https://github.com/cmrivers/ebola",
    download_url=(
        "https://raw.githubusercontent.com/cmrivers/ebola/master/country_timeseries.csv"
    ),
    download_mechanism="a CSV in a public repository; fetched only after a licence review",
    dataset_type=SURVEILLANCE,
    file_format="csv",
    license=None,
    license_url="https://api.github.com/repos/cmrivers/ebola/license",
    license_source="GitHub's licence endpoint reports NOASSERTION: no licence is declared",
    redistribution="no licence declared; no redistribution right has been granted",
    access_procedure=(
        "Re-run the pipeline with --accept-undeclared-license and a written reason, which "
        "is recorded in the acquisition log. The underlying figures are WHO's own and can "
        "also be transcribed from the situation reports and imported as a CSV."
    ),
    license_review_required=True,
    features=("date", "country"),
    metrics=(surveillance.CUMULATIVE_CASES, surveillance.CUMULATIVE_DEATHS),
    notes=(
        "Cumulative counts, so a figure for a period is that period's last value and never "
        "a sum. The transcription stopped on 15 December 2015 while the epidemic was still "
        "running, so the final totals in it are not the epidemic's final totals. Later "
        "Ebola outbreaks are not covered at all."
    ),
)
