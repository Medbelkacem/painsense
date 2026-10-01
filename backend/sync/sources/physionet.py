"""PhysioNet, read from its published project pages.

PhysioNet has no catalogue API, so discovery parses the topic listings and then each
project page. What is parsed is the Access Policy section, because that sentence is the
whole point of this connector: PhysioNet states, in fixed wording, whether a project is
open to anyone, open to registered users who sign a data use agreement, or restricted to
credentialed users who have completed human-subjects training.

Only an open project is ever downloaded. For everything else the project's metadata, its
licence, its data use agreement and the steps a person would take are recorded, and no
request is made for the files. The platform holds no PhysioNet credentials and there is
no configuration that would let it attempt a credentialed download — the restriction is
structural rather than a flag someone could flip.

Open projects are served as a zip under a stable published-projects path. The slug and
version come from the project page, so the URL is constructed from what PhysioNet stated
rather than guessed.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.sync import http
from backend.sync.sources.base import (
    PHYSIOLOGICAL_SIGNALS,
    TEXT_CORPUS,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
    dominant_format,
)
from backend.sync.storage import safe_extract
from database.models import Granularity, SourceAccess

BASE = "https://physionet.org"
DEFAULT_TOPICS = ("pain", "nociception", "analgesia")

#: PhysioNet's Access Policy sentences, verbatim. Matching the publisher's own wording is
#: what makes this reliable; a keyword search for "credentialed" would also fire on a
#: project that merely mentions the word in its description.
ACCESS_SENTENCES: tuple[tuple[str, SourceAccess], ...] = (
    (
        (
            "Anyone can access the files, as long as they conform to the terms of the "
            "specified license"
        ),
        SourceAccess.OPEN,
    ),
    (
        "Only credentialed users who sign the DUA can access the files",
        SourceAccess.CREDENTIALED,
    ),
    (
        (
            "Only credentialed users who sign the specified data use agreement can access "
            "the files"
        ),
        SourceAccess.CREDENTIALED,
    ),
    (
        (
            "Only registered users who sign the specified data use agreement can access "
            "the files"
        ),
        SourceAccess.AGREEMENT_REQUIRED,
    ),
    (
        "Only registered users who sign the DUA can access the files",
        SourceAccess.AGREEMENT_REQUIRED,
    ),
)

SIGNAL_TOPICS = ("ecg", "eeg", "emg", "ppg", "signal", "physiolog", "waveform")


def _text_of(markup: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup))).strip()


class PhysioNet(Connector):
    def discover(self, config: dict) -> list[RemoteDataset]:
        topics = tuple(config.get("topics") or DEFAULT_TOPICS)
        limit = int(config.get("limit", 25))
        client = self.client()

        slugs: dict[str, str] = {}
        failures: list[str] = []
        for topic in topics:
            try:
                page = client.get(f"{BASE}/content/?topic={topic}", max_bytes=8 << 20).text()
            except http.TransferError as exc:
                failures.append(f"topic {topic}: {exc}")
                continue
            for path in re.findall(r'href="(/content/[a-z0-9][a-z0-9./-]*/)"', page):
                parts = [part for part in path.strip("/").split("/") if part != "content"]
                if parts:
                    slugs.setdefault(parts[0], path)
        if not slugs and failures:
            raise Unavailable("the PhysioNet topic index could not be read: " + "; ".join(failures))

        found = []
        for slug in sorted(slugs)[:limit]:
            entry = self._inspect(client, slug, slugs[slug])
            if entry is not None:
                found.append(entry)
        return found

    def _inspect(self, client: http.Client, slug: str, path: str) -> RemoteDataset | None:
        url = f"{BASE}{path}"
        try:
            page = client.get(url, max_bytes=8 << 20).text()
        except http.TransferError:
            # A project page that cannot be read right now is not evidence about the
            # project. Skipping leaves any existing row untouched rather than overwriting
            # a known access status with a guess.
            return None

        text = _text_of(page)
        access, sentence = SourceAccess.UNKNOWN, None
        for candidate, status in ACCESS_SENTENCES:
            if candidate in text:
                access, sentence = status, candidate
                break

        licence = version = None
        licence_match = re.search(
            r'href="/content/[^"]*/view-license/([0-9.]+)/"[^>]*>([^<]+)</a>', page
        )
        if licence_match:
            version, licence = licence_match.group(1), html.unescape(licence_match.group(2)).strip()
        if version is None:
            version_match = re.search(r"DOI \(v([0-9.]+)\)", text)
            version = version_match.group(1) if version_match else None

        agreement = None
        dua_match = re.search(r'href="/content/[^"]*/view-dua/[0-9.]+/"[^>]*>([^<]+)</a>', page)
        if dua_match:
            agreement = html.unescape(dua_match.group(1)).strip()

        title_match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.DOTALL)
        title = _text_of(title_match.group(1)) if title_match else slug

        topics_match = re.search(r"Topics\s+(.+?)\s+Project Views", text)
        topics = tuple(topics_match.group(1).split()) if topics_match else ()

        notes = []
        if sentence:
            notes.append(f'PhysioNet states: "{sentence}."')
        if agreement:
            notes.append(f"Data use agreement: {agreement}.")
        if access is not SourceAccess.OPEN:
            notes.append("No files were requested for this project.")

        description = " ".join(
            re.findall(r'<meta name="description" content="([^"]*)"', page)
        ) or " ".join(text.split()[:120])

        downloadable = access is SourceAccess.OPEN and version is not None
        return RemoteDataset(
            external_id=slug,
            name=title,
            description=html.unescape(description)[:4000],
            source_url=url,
            download_url=(
                f"{BASE}/static/published-projects/{slug}/{slug}-{version}.zip"
                if downloadable
                else None
            ),
            download_mechanism=(
                "PhysioNet published-project archive" if downloadable else "not served openly"
            ),
            dataset_type=(
                PHYSIOLOGICAL_SIGNALS
                if any(marker in " ".join(topics).casefold() for marker in SIGNAL_TOPICS)
                else TEXT_CORPUS
            ),
            granularity=Granularity.SUBJECT_LEVEL,
            modalities=topics,
            access_status=access,
            licence=licence,
            licence_url=f"{url}#files" if licence else None,
            publisher_version=version,
            relevance=3 if any("pain" in topic.casefold() for topic in topics) else 1,
            notes=" ".join(notes),
        )

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        # Belt and braces. `app.sync.service` has already applied the access gate; this
        # second check means no future caller can reach a restricted project through this
        # method by passing a hand-made dataset.
        if dataset.access_status is not SourceAccess.OPEN:
            raise Unavailable(
                "PhysioNet restricts this project; its access procedure is recorded and no "
                "request for the files was made"
            )
        if not dataset.download_url:
            raise Unavailable("this project publishes no open archive")

        client = self.client()
        archive = destination / "archive.zip"
        try:
            downloaded = client.download(dataset.download_url, archive, max_bytes=max_bytes)
        except http.TransferError as exc:
            raise Unavailable(str(exc)) from exc

        extracted = destination / "files"
        files = tuple(safe_extract(archive, extracted, max_bytes=max_bytes))
        if not files:
            archive.unlink(missing_ok=True)
            raise Unavailable("the published archive held no files")
        archive.unlink(missing_ok=True)

        from backend.sync.fingerprint import of_directory

        return Acquired(
            files=files,
            bytes=sum(path.stat().st_size for path in files),
            sha256=of_directory(extracted),
            file_format=dominant_format(files),
            version=dataset.publisher_version or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            retrieved_from=downloaded.url,
            notes=f"{len(files)} file(s) extracted from the published project archive.",
        )


PHYSIONET = PhysioNet(
    code="physionet",
    label="PhysioNet",
    organisation="PhysioNet / MIT Laboratory for Computational Physiology",
    homepage="https://physionet.org",
    hosts=("physionet.org",),
    default_config={"topics": list(DEFAULT_TOPICS), "limit": 25},
)
