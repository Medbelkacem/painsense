"""World Health Organization, over the Global Health Observatory OData API.

What the GHO actually serves matters for how it is recorded here. `/api/Indicator` is a
catalogue of several thousand indicators — that is metadata, and it is what discovery
reads. `/api/{IndicatorCode}` returns the indicator's observations: one row per country,
year and disaggregation, with a numeric value. Those rows are a real dataset and they are
downloaded, but they are *population statistics*, not records about people, so every
dataset from this connector is marked `AGGREGATE_STATISTICS` and `Granularity.AGGREGATE`.
Nothing downstream can then mistake a cholera case count per country-year for a labelled
clinical dataset, which is the mistake this whole arrangement exists to prevent.

WHO states its terms as a publishing policy rather than attaching a licence file per
indicator, so that is what gets recorded, with the policy URL alongside it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.sync import http
from backend.sync.sources.base import (
    AGGREGATE_STATISTICS,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
)
from database.models import Granularity, SourceAccess

API = "https://ghoapi.azureedge.net/api"
TERMS = "https://www.who.int/about/policies/publishing/copyright"
LICENCE = "WHO publishing and copyright policy (CC BY-NC-SA 3.0 IGO for GHO content)"

#: Indicator-name fragments worth cataloguing. The GHO carries thousands of indicators
#: covering everything WHO measures; without a filter every discovery pass would create
#: thousands of rows that have nothing to do with this platform.
DEFAULT_TERMS = (
    "cholera",
    "measles",
    "meningitis",
    "tuberculosis",
    "malaria",
    "dengue",
    "hepatitis",
    "HIV",
    "influenza",
    "COVID-19",
    "road traffic",
    "arthritis",
    "diabetes",
)


class WhoGho(Connector):
    def discover(self, config: dict) -> list[RemoteDataset]:
        terms = tuple(config.get("terms") or DEFAULT_TERMS)
        limit = int(config.get("limit", 60))
        client = self.client()
        try:
            payload = client.get_json(f"{API}/Indicator", max_bytes=32 << 20)
        except http.TransferError as exc:
            raise Unavailable(f"the GHO indicator catalogue could not be read: {exc}") from exc

        wanted = tuple(term.casefold() for term in terms)
        found: list[RemoteDataset] = []
        for row in payload.get("value", []) if isinstance(payload, dict) else []:
            code = (row.get("IndicatorCode") or "").strip()
            name = (row.get("IndicatorName") or "").strip()
            if not code or not name or (row.get("Language") or "EN") != "EN":
                continue
            haystack = name.casefold()
            if not any(term in haystack for term in wanted):
                continue
            found.append(
                RemoteDataset(
                    external_id=code,
                    name=name,
                    description=(
                        f"WHO Global Health Observatory indicator {code}. Observations are "
                        "reported per country and period as population statistics, not as "
                        "records about individual people."
                    ),
                    source_url=f"https://www.who.int/data/gho/data/indicators/indicator-details/GHO/{code}",
                    download_url=f"{API}/{code}",
                    download_mechanism="GHO OData indicator endpoint",
                    dataset_type=AGGREGATE_STATISTICS,
                    granularity=Granularity.AGGREGATE,
                    modalities=("tabular_aggregate",),
                    access_status=SourceAccess.OPEN,
                    licence=LICENCE,
                    licence_url=TERMS,
                    relevance=2,
                    notes=(
                        "Licence recorded from WHO's site-wide publishing policy; WHO "
                        "attaches no per-indicator licence file."
                    ),
                )
            )
            if len(found) >= limit:
                break
        return found

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        if not dataset.download_url:
            raise Unavailable("this indicator has no observation endpoint")
        client = self.client()
        try:
            response = client.get(dataset.download_url, accept="application/json", max_bytes=max_bytes)
        except http.TransferError as exc:
            raise Unavailable(str(exc)) from exc

        try:
            rows = response.json().get("value", [])
        except (ValueError, AttributeError) as exc:
            raise Unavailable("the indicator endpoint did not return OData JSON") from exc
        if not rows:
            raise Unavailable("the indicator endpoint returned no observations")

        # Written as JSON Lines rather than as the raw OData envelope: the envelope's
        # paging metadata is not data, and one object per line is what the profiler and
        # every downstream reader expect.
        target = destination / f"{dataset.external_id}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")

        from backend.sync.fingerprint import sha256_of

        version = (
            dataset.publisher_updated_at or datetime.now(timezone.utc)
        ).strftime("%Y-%m-%d")
        return Acquired(
            files=(target,),
            bytes=target.stat().st_size,
            sha256=sha256_of(target),
            file_format="jsonl",
            version=version,
            retrieved_from=dataset.download_url,
            notes=(
                f"{len(rows)} observation(s) retrieved from the GHO OData endpoint. The "
                "endpoint publishes no version identifier, so the version records the "
                "acquisition date."
            ),
        )


WHO_GHO = WhoGho(
    code="who_gho",
    label="WHO Global Health Observatory",
    organisation="World Health Organization",
    homepage="https://www.who.int/data/gho",
    hosts=("ghoapi.azureedge.net", "who.int"),
    default_config={"terms": list(DEFAULT_TERMS), "limit": 60},
)
