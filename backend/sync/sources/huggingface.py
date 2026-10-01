"""Hugging Face dataset repositories.

The Hub's API gives a dataset's files with their sizes before anything is downloaded,
which matters here more than for the other publishers: a burn imaging dataset is
routinely tens of gigabytes, and the size cap should refuse it from the listing rather
than partway through a transfer.

Licensing on the Hub is uneven. Many repositories declare one in the YAML of their card
and many declare nothing at all. What is declared is recorded verbatim and what is not is
recorded as not declared — the dataset is catalogued either way, and the licence gate
then decides. In practice several widely-cited burn datasets fall on the "nothing
declared" side, which is exactly the case this pipeline must handle by cataloguing and
not downloading.

A gated repository is one the owner has put behind an access request. It is reported as
such and never fetched, with or without a token.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from database.models import Granularity, SourceAccess
from backend.sync import http
from backend.sync.sources.base import (
    IMAGING,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
    dominant_format,
)

API = "https://huggingface.co/api"
HUB = "https://huggingface.co/datasets"

DEFAULT_QUERIES = ("burn", "burn segmentation", "wound", "skin lesion")

#: Repository files worth retrieving. A repository's archives hold the imagery and are
#: often enormous; the small structured files are the labels and the card. Both are
#: offered, and the size cap decides which actually arrive.
WANTED_SUFFIXES = (
    ".json",
    ".npy",
    ".csv",
    ".parquet",
    ".jsonl",
    ".txt",
    ".md",
    ".zip",
    ".7z",
    ".tar",
    ".tar.gz",
)

IMAGE_MARKERS = ("image", "segmentation", "mask", "photo", "vision", "burn")


def _parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _size_of(entry: dict) -> int:
    lfs = entry.get("lfs") or {}
    return int(entry.get("size") or lfs.get("size") or 0)


class HuggingFace(Connector):
    def discover(self, config: dict) -> list[RemoteDataset]:
        # An explicit empty list means "do not search", which is different from the key
        # being absent. A deployment that wants only its named repositories polled
        # should not silently get the default sweep as well.
        queries = tuple(config.get("queries", DEFAULT_QUERIES) or ())
        per_query = int(config.get("per_query", 10))
        explicit = tuple(config.get("datasets") or ())
        client = self.client()

        found: dict[str, RemoteDataset] = {}
        failures: list[str] = []

        for repo in explicit:
            try:
                found.setdefault(repo, self._describe(client, repo))
            except http.TransferError as exc:
                failures.append(f"{repo}: {exc}")

        for query in queries:
            url = (
                f"{API}/datasets?search={urllib.parse.quote(query)}"
                f"&limit={per_query}&full=false"
            )
            try:
                rows = client.get_json(url, max_bytes=8 << 20)
            except http.TransferError as exc:
                failures.append(f"{query}: {exc}")
                continue
            for row in rows if isinstance(rows, list) else []:
                repo = row.get("id")
                if not repo or repo in found:
                    continue
                try:
                    found[repo] = self._describe(client, repo)
                except http.TransferError as exc:
                    failures.append(f"{repo}: {exc}")

        if not found and failures:
            raise Unavailable("the Hugging Face Hub could not be read: " + "; ".join(failures[:5]))
        return list(found.values())

    def _describe(self, client: http.Client, repo: str) -> RemoteDataset:
        payload = client.get_json(f"{API}/datasets/{repo}", max_bytes=16 << 20)
        card = payload.get("cardData") or {}
        licence = card.get("license")
        if isinstance(licence, list):
            licence = ", ".join(str(item) for item in licence) or None

        files = [
            {"path": entry.get("rfilename"), "size": _size_of(entry)}
            for entry in (payload.get("siblings") or [])
            if entry.get("rfilename")
        ]
        total = sum(entry["size"] for entry in files)
        description = " ".join(str(payload.get("description") or "").split())[:4000]
        haystack = f"{repo} {description}".casefold()

        gated = bool(payload.get("gated"))
        access = SourceAccess.REGISTRATION_REQUIRED if gated else SourceAccess.OPEN
        if payload.get("private"):
            access = SourceAccess.CREDENTIALED

        return RemoteDataset(
            external_id=repo,
            name=repo.split("/")[-1].replace("-", " ").replace("_", " ").title(),
            description=description,
            source_url=f"{HUB}/{repo}",
            download_url=f"{HUB}/{repo}/resolve/main",
            download_mechanism="Hugging Face Hub file resolve",
            dataset_type=IMAGING
            if any(marker in haystack for marker in IMAGE_MARKERS)
            else "tabular",
            granularity=Granularity.UNKNOWN,
            modalities=tuple(sorted({Path(f["path"]).suffix.lstrip(".") for f in files if f["path"]})[:12]),
            access_status=access,
            licence=licence,
            licence_url=f"{HUB}/{repo}",
            publisher_version=payload.get("sha"),
            publisher_updated_at=_parsed_time(payload.get("lastModified")),
            bytes_claimed=total or None,
            relevance=3 if "burn" in haystack else 1,
            notes=(
                "The owner has put this repository behind an access request; its files "
                "were not retrieved."
                if gated
                else (
                    ""
                    if licence
                    else "The repository card declares no licence. Catalogued without "
                    "retrieving any file."
                )
            ),
        )

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        if dataset.access_status is not SourceAccess.OPEN:
            raise Unavailable(
                "this repository is gated by its owner; its metadata is recorded and no "
                "file was requested"
            )
        client = self.client()
        listing = client.get_json(
            f"{API}/datasets/{dataset.external_id}/tree/main", max_bytes=32 << 20
        )
        if not isinstance(listing, list):
            raise Unavailable("the Hub returned no file listing for this repository")

        # Smallest first, so a repository whose labels are kilobytes and whose imagery is
        # gigabytes yields the labels rather than nothing at all. What was left behind is
        # reported, so the stored copy is never mistaken for the whole dataset.
        candidates = sorted(
            (
                entry
                for entry in listing
                if entry.get("type") == "file"
                and str(entry.get("path", "")).endswith(WANTED_SUFFIXES)
            ),
            key=_size_of,
        )
        if not candidates:
            raise Unavailable("the repository holds no file this pipeline retrieves")

        written: list[Path] = []
        budget = max_bytes
        skipped: list[str] = []
        for entry in candidates:
            path = str(entry["path"])
            size = _size_of(entry)
            if size > budget:
                skipped.append(f"{path} ({size:,} bytes)")
                continue
            target = destination / "files" / path
            url = f"{HUB}/{dataset.external_id}/resolve/main/{urllib.parse.quote(path)}"
            try:
                result = client.download(url, target, max_bytes=budget)
            except http.TransferError as exc:
                skipped.append(f"{path} ({exc})")
                continue
            budget -= result.bytes
            written.append(target)

        if not written:
            raise Unavailable(
                "every file in this repository is larger than the configured size limit; "
                "nothing was stored. Raise SYNC_MAX_DATASET_BYTES or obtain it directly: "
                + ", ".join(skipped[:3])
            )

        from backend.sync.fingerprint import of_directory

        note = f"{len(written)} file(s) retrieved."
        if skipped:
            note += (
                f" {len(skipped)} file(s) exceeded the size limit and were not retrieved: "
                + ", ".join(skipped[:5])
                + ". The stored copy is therefore partial."
            )
        return Acquired(
            files=tuple(written),
            bytes=sum(path.stat().st_size for path in written),
            sha256=of_directory(destination / "files"),
            file_format=dominant_format(tuple(written)),
            version=(dataset.publisher_version or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:40],
            retrieved_from=f"{HUB}/{dataset.external_id}",
            notes=note,
        )


HUGGING_FACE = HuggingFace(
    code="huggingface",
    label="Hugging Face datasets",
    organisation="Hugging Face",
    homepage="https://huggingface.co/datasets",
    hosts=("huggingface.co", "hf.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co"),
    default_config={
        "queries": list(DEFAULT_QUERIES),
        "per_query": 10,
        "datasets": ["HLSS/MassHumanBurns", "shubhambaid/skin-burn-dataset"],
    },
)
