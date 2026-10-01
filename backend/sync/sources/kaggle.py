"""Kaggle, over its documented public API.

Dataset search answers anonymously, so discovery works with no account at all. A download
does not always: a dataset whose owner requires a signed-in account answers an anonymous
request with an HTML sign-in page rather than an archive. Credentials, when configured,
are the platform operator's own Kaggle account used through the API Kaggle publishes for
exactly this. They are not used to reach anything the account is not entitled to, and a
dataset that still refuses is recorded as refusing.

The response is checked before it is believed. Kaggle answers a refused download with
`200 OK` and an HTML page, so an archive that does not begin with the zip magic number is
treated as a failed acquisition and deleted, never stored as if it were data.

Licence names come back as free text and are recorded verbatim; `app.sync.licensing`
decides what they permit. Most of Kaggle is not pain-related, so the relevance score below
decides what is worth cataloguing at all.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings
from database.models import Granularity, SourceAccess
from backend.sync import http
from backend.sync.sources.base import (
    CLINICAL_RECORDS,
    PHYSIOLOGICAL_SIGNALS,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
    dominant_format,
)
from backend.sync.storage import safe_extract

API = "https://www.kaggle.com/api/v1"

DEFAULT_QUERIES = (
    "pain assessment",
    "pain intensity",
    "pain detection",
    "chronic pain",
    "migraine",
    "physiological pain",
)

#: Phrases that make a dataset worth cataloguing, and how strongly. A dataset scoring zero
#: is dropped at discovery: Kaggle's search is generous and "pain" matches a great deal
#: that has nothing to do with clinical pain.
RELEVANCE = {
    "pain intensity": 5,
    "pain level": 5,
    "pain score": 5,
    "pain severity": 5,
    "pain assessment": 4,
    "pain recognition": 4,
    "pain detection": 4,
    "chronic pain": 3,
    "acute pain": 3,
    "back pain": 3,
    "neck pain": 3,
    "migraine": 3,
    "nrs": 3,
    "vas": 2,
    "pain": 2,
    "headache": 1,
    "arthritis": 1,
}

MODALITIES = {
    "ecg": ("ecg", "electrocardiogram"),
    "eda": ("eda", "electrodermal", "gsr", "galvanic skin"),
    "emg": ("emg", "electromyograph"),
    "eeg": ("eeg", "electroencephalo"),
    "ppg": ("ppg", "photoplethysmo"),
    "hrv": ("hrv", "heart rate variability"),
    "heart_rate": ("heart rate", "pulse", "bpm"),
    "respiration": ("respiration", "respiratory", "breathing"),
    "temperature": ("temperature", "thermal"),
    "video": ("video", "frames"),
    "image": ("image", "facial", "face"),
    "audio": ("audio", "speech", "voice"),
    "text": ("notes", "questionnaire", "survey"),
    "tabular_clinical": ("clinical", "patient", "diagnosis", "symptom", "ehr"),
}

TARGETS = {
    "nrs": ("nrs", "numeric rating"),
    "vas": ("vas", "visual analog", "visual analogue"),
    "pain_intensity": ("pain intensity", "pain level", "pain score", "pain severity"),
    "pain_present": ("pain detection", "pain recognition", "no pain"),
}

SIGNAL_MODALITIES = frozenset({"ecg", "eda", "emg", "eeg", "ppg", "hrv", "respiration"})


def _phrase(text: str, needle: str) -> bool:
    return re.search(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])", text) is not None


def _matches(text: str, table: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(
        sorted(key for key, needles in table.items() if any(_phrase(text, n) for n in needles))
    )


def _parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def credentials() -> tuple[str, str] | None:
    settings = get_settings()
    if settings.kaggle_username and settings.kaggle_key:
        return settings.kaggle_username, settings.kaggle_key
    return None


class Kaggle(Connector):
    def _client(self) -> http.Client:
        pair = credentials()
        header = None
        if pair:
            header = "Basic " + base64.b64encode(f"{pair[0]}:{pair[1]}".encode()).decode()
        return self.client(auth_header=header)

    def discover(self, config: dict) -> list[RemoteDataset]:
        queries = tuple(config.get("queries") or DEFAULT_QUERIES)
        page_size = int(config.get("page_size", 20))
        minimum = int(config.get("minimum_relevance", 2))
        client = self._client()

        found: dict[str, RemoteDataset] = {}
        failures: list[str] = []
        for query in queries:
            url = f"{API}/datasets/list?search={urllib.parse.quote(query)}&page=1&pageSize={page_size}"
            try:
                rows = client.get_json(url, max_bytes=16 << 20)
            except http.TransferError as exc:
                failures.append(f"{query}: {exc}")
                continue
            if not isinstance(rows, list):
                failures.append(f"{query}: the search endpoint returned no list")
                continue
            for row in rows:
                entry = self._describe(row)
                if entry is not None and entry.relevance >= minimum:
                    found.setdefault(entry.external_id, entry)
        if not found and failures:
            raise Unavailable("the Kaggle search API could not be read: " + "; ".join(failures))
        return list(found.values())

    @staticmethod
    def _describe(row: dict) -> RemoteDataset | None:
        reference = (row.get("ref") or "").strip()
        title = (row.get("title") or "").strip()
        if not reference or not title or row.get("isPrivate"):
            return None
        subtitle = (row.get("subtitle") or "").strip()
        description = " ".join(f"{subtitle} {row.get('description') or ''}".split())[:4000]
        haystack = f"{title} {description}".casefold()
        score = sum(weight for phrase, weight in RELEVANCE.items() if _phrase(haystack, phrase))
        modalities = _matches(haystack, MODALITIES)
        version = row.get("currentVersionNumber")
        return RemoteDataset(
            external_id=reference,
            name=title,
            description=description,
            source_url=row.get("url") or f"https://www.kaggle.com/datasets/{reference}",
            download_url=f"{API}/datasets/download/{urllib.parse.quote(reference)}",
            download_mechanism="Kaggle dataset archive endpoint",
            dataset_type=(
                PHYSIOLOGICAL_SIGNALS
                if SIGNAL_MODALITIES.intersection(modalities)
                else CLINICAL_RECORDS
            ),
            # Kaggle publishes no machine-readable statement of whether rows describe
            # people or populations. Measured from the file by `app.sync.profile` once it
            # is on disk; claimed as unknown until then.
            granularity=Granularity.UNKNOWN,
            modalities=modalities,
            target_labels=_matches(haystack, TARGETS),
            access_status=SourceAccess.OPEN,
            licence=row.get("licenseName"),
            licence_url=row.get("url"),
            publisher_version=str(version) if version is not None else None,
            publisher_updated_at=_parsed_time(row.get("lastUpdated")),
            bytes_claimed=row.get("totalBytes"),
            relevance=score,
            notes=(
                "Modalities and target labels are inferred from the publisher's title and "
                "description, not from file contents."
            ),
        )

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        if not dataset.download_url:
            raise Unavailable("this dataset publishes no archive URL")
        client = self._client()
        archive = destination / "archive.zip"
        try:
            downloaded = client.download(dataset.download_url, archive, max_bytes=max_bytes)
        except http.TransferError as exc:
            raise Unavailable(str(exc)) from exc

        if not zipfile.is_zipfile(archive):
            opening = archive.read_bytes()[:200]
            archive.unlink(missing_ok=True)
            signed_in = "with" if credentials() else "without"
            raise Unavailable(
                f"Kaggle did not return an archive ({signed_in} credentials); the response "
                f"began {opening[:60]!r}. A dataset whose owner requires a signed-in "
                "account answers an anonymous request with a sign-in page."
            )

        extracted = destination / "files"
        files = tuple(safe_extract(archive, extracted, max_bytes=max_bytes))
        if not files:
            raise Unavailable("the archive held no files")
        archive.unlink(missing_ok=True)

        from backend.sync.fingerprint import of_directory

        return Acquired(
            files=files,
            bytes=sum(path.stat().st_size for path in files),
            sha256=of_directory(extracted),
            file_format=dominant_format(files),
            version=dataset.publisher_version or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            retrieved_from=downloaded.url,
            notes=(
                f"{len(files)} file(s) extracted from the Kaggle archive; the archive "
                "itself was discarded once unpacked."
            ),
        )


KAGGLE = Kaggle(
    code="kaggle",
    label="Kaggle datasets",
    organisation="Kaggle",
    homepage="https://www.kaggle.com/datasets",
    hosts=("kaggle.com", "googleapis.com", "storage.googleapis.com"),
    default_config={
        "queries": list(DEFAULT_QUERIES),
        "page_size": 20,
        "minimum_relevance": 2,
    },
    uses_credentials=True,
)
