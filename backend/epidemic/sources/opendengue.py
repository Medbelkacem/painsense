"""OpenDengue's national extract.

OpenDengue, at the London School of Hygiene and Tropical Medicine, assembles national
dengue case counts out of ministry-of-health bulletins and publishes them as a numbered
release with per-record provenance. It is the only global dengue series found with a stated
licence and a stable download: WHO's Global Health Observatory carries no dengue indicator.

Releases are versioned in the path, so the version this pipeline holds is the version in
the URL it fetched and nothing has to be inferred.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass

import pandas as pd

from backend.epidemic import net, paths, surveillance
from backend.epidemic.diseases import SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Source

LSHTM = "OpenDengue (London School of Hygiene and Tropical Medicine)"
RELEASE = "V1_3"


@dataclass(frozen=True)
class OpenDengueNational(Source):
    release: str = RELEASE

    def fetch(self) -> Fetched:
        directory = paths.ensure(self.raw_dir())
        archive = directory / f"National_extract_{self.release}.zip"
        size, digest = net.download(self.download_url or "", archive)
        extracted = directory / "extracted"
        extracted.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                # A release archive is a flat list of CSVs, but an archive is still
                # attacker-controlled input: a member that escapes the target directory is
                # refused rather than written.
                target = (extracted / member.filename).resolve()
                if not str(target).startswith(str(extracted.resolve())):
                    raise ValueError(f"archive member escapes the target directory: {member.filename}")
                bundle.extract(member, extracted)
        return Fetched(
            files=(archive,),
            bytes=size,
            sha256=digest,
            file_format="zip of csv",
            version=self.release,
        )

    def _table(self) -> pd.DataFrame | None:
        extracted = self.raw_dir() / "extracted"
        if not extracted.exists():
            return None
        candidates = sorted(extracted.rglob("*.csv"), key=lambda path: -path.stat().st_size)
        return pd.read_csv(candidates[0], low_memory=False) if candidates else None

    def normalize(self) -> pd.DataFrame | None:
        raw = self._table()
        if raw is None or raw.empty:
            return None
        columns = {name.lower(): name for name in raw.columns}

        def column(*names: str) -> str | None:
            for name in names:
                if name in columns:
                    return columns[name]
            return None

        country = column("adm_0_name", "country", "countryname")
        start = column("calendar_start_date", "start_date", "date")
        end = column("calendar_end_date", "end_date")
        cases = column("dengue_total", "cases", "total_cases")
        iso = column("iso_a0", "iso3", "iso_code")
        if not (country and start and cases):
            raise ValueError(
                "the OpenDengue extract does not carry the expected country, date and case "
                f"columns; it has {', '.join(sorted(raw.columns))}"
            )

        period_start = pd.to_datetime(raw[start], errors="coerce")
        period_end = (
            pd.to_datetime(raw[end], errors="coerce") if end else period_start
        ).fillna(period_start)
        # Records are published per reporting window rather than on a fixed cadence: some
        # countries report weekly, some monthly, some annually. The window is recorded as
        # it stands and the cadence is called a range rather than being forced into one.
        out = pd.DataFrame(
            {
                "disease": "dengue",
                "dataset_id": self.dataset_id,
                "source": LSHTM,
                "country": raw[country],
                "iso3": raw[iso] if iso else None,
                "who_region": None,
                "admin_level": surveillance.NATIONAL,
                "area": None,
                "period_start": period_start,
                "period_end": period_end,
                "period_type": surveillance.RANGE,
                "metric": surveillance.NEW_CASES,
                "value": pd.to_numeric(raw[cases], errors="coerce"),
                "observation_type": surveillance.REPORTED,
                "retrieved_at": _now(),
            }
        ).dropna(subset=["value", "period_start"])
        return surveillance.conform(out)


def _now() -> str:
    from backend.epidemic.registry import now

    return now()


OPENDENGUE_NATIONAL = OpenDengueNational(
    dataset_id="opendengue_national",
    name=f"OpenDengue national extract {RELEASE.replace('_', '.')}",
    diseases=("dengue",),
    organisation=LSHTM,
    source_url="https://opendengue.org/data.html",
    download_url=(
        "https://github.com/OpenDengue/master-repo/raw/main/data/releases/V1.3/"
        "National_extract_V1_3.zip"
    ),
    download_mechanism="the versioned release archive the project's data page links",
    dataset_type=SURVEILLANCE,
    file_format="zip of csv",
    license="CC BY 4.0",
    license_url="https://opendengue.org/",
    license_source="stated in the site footer: content licensed under CC BY 4.0",
    redistribution="permitted with attribution; not redistributed by this pipeline",
    features=("country", "iso3", "reporting window"),
    metrics=(surveillance.NEW_CASES,),
    notes=(
        "Assembled from national bulletins, so the reporting window differs by country and "
        "by year and each record carries its own window rather than sitting on a common "
        "cadence. Case definitions are whatever the reporting country used."
    ),
)
