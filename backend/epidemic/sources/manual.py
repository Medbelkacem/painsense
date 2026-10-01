"""Sources that exist but are not served through any data interface.

Lassa fever is the clear case. Nigeria accounts for most of the reported global burden and
the Nigeria Centre for Disease Control publishes weekly situation reports for it, but as
documents on a web page rather than through an API or a stable CSV. Scraping the pages to
assemble a series would mean building a parser against a layout nobody promised to keep,
and the brief rules out working against a publisher's terms, so this adapter does not
download anything.

What it does instead is register the dataset with the real reason it is unavailable and the
procedure a person would follow, and leave `POST /api/epidemiology/datasets/import` as the
route in. Until somebody walks that route, the interface says "manual import required" for
Lassa fever rather than showing a chart.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.epidemic import net, registry
from backend.epidemic.diseases import SURVEILLANCE
from backend.epidemic.sources.base import Fetched, Probe, Refused, Source


@dataclass(frozen=True)
class DocumentOnlySource(Source):
    def probe(self) -> Probe:
        """Check only that the publisher's page is still where the registry says it is.

        Reachability of a page is not availability of data, so `reachable` stays False
        whatever the page returns; the detail records what was found.
        """
        try:
            headers = net.head(self.source_url, timeout=45)
            found = f"the publisher's page answers HTTP {headers.get('status')}"
        except net.Unreachable as exc:
            found = f"the publisher's page could not be reached: {exc}"
        return Probe(False, f"{found}; the series is published as documents, not as data")

    def fetch(self) -> Fetched:
        raise Refused(
            "this publisher releases the series as situation report documents. Use "
            "POST /api/epidemiology/datasets/import, or the import_csv pipeline command, "
            "to load figures transcribed from them."
        )


NCDC_LASSA_SITREPS = DocumentOnlySource(
    dataset_id="ncdc_lassa_sitreps",
    name="Lassa fever weekly situation reports, Nigeria",
    diseases=("lassa",),
    organisation="Nigeria Centre for Disease Control and Prevention",
    source_url="https://ncdc.gov.ng/diseases/sitreps",
    download_url=None,
    download_mechanism="none published; weekly situation reports as documents",
    dataset_type=SURVEILLANCE,
    file_format=None,
    license=None,
    license_url="https://ncdc.gov.ng/",
    license_source="no data licence is published alongside the situation reports",
    redistribution="unknown; no licence published",
    access_status=registry.ACCESS_DOCUMENT_ONLY,
    access_procedure=(
        "Open the weekly situation report for the epidemiological week of interest, read "
        "the confirmed-case and death table, and import it as a CSV with columns disease, "
        "country, period_start, period_end, metric, value. The import endpoint validates "
        "the columns and records the report it came from as the provenance."
    ),
    features=(),
    notes=(
        "Nigeria reports the large majority of confirmed Lassa fever cases worldwide, so "
        "without these reports the only automatic figures are the US notifiable-disease "
        "counts, which are zero in almost every week."
    ),
)
