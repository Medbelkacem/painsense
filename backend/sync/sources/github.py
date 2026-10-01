"""Dataset and reference-implementation repositories on GitHub.

Several of the burn datasets worth knowing about are distributed as a research repository:
the code is on GitHub and the imagery is behind a form, a mail request or a university
download page described in the README. Cataloguing the repository is still the right move
— it records the dataset exists, what it claims to contain and where to ask — and it is
the only honest alternative to pretending the data is available.

The licence comes from GitHub's own licence detection, which reads the repository's
LICENSE file. A repository with no LICENSE file reports nothing, and that is recorded as
nothing rather than guessed from the README. In this field that is the common case, so it
decides the behaviour of the pipeline for most of these sources: catalogue, record the
access route, download no data.

What is fetched, where the licence permits, is the repository tarball. That is code and
documentation, not the dataset, and the note on the stored version says so.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.sync import http
from backend.sync.sources.base import (
    SOURCE_CODE,
    Acquired,
    Connector,
    RemoteDataset,
    Unavailable,
    dominant_format,
)
from backend.sync.storage import safe_extract
from database.models import Granularity, SourceAccess

API = "https://api.github.com"

#: Phrases in a README that mean the data itself is not in the repository. Their presence
#: is why `access_status` for these sources is a request route rather than open.
REQUEST_MARKERS = (
    "request access",
    "upon request",
    "please contact",
    "sign the agreement",
    "data use agreement",
    "fill in the form",
    "google form",
    "apply for access",
)


def _parsed_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class GitHub(Connector):
    def discover(self, config: dict) -> list[RemoteDataset]:
        repositories = tuple(config.get("repositories") or ())
        if not repositories:
            return []
        client = self.client()
        found: list[RemoteDataset] = []
        failures: list[str] = []
        for repo in repositories:
            try:
                found.append(self._describe(client, repo))
            except http.TransferError as exc:
                failures.append(f"{repo}: {exc}")
        if not found and failures:
            raise Unavailable("no repository could be read: " + "; ".join(failures))
        return found

    def _describe(self, client: http.Client, repo: str) -> RemoteDataset:
        payload = client.get_json(f"{API}/repos/{repo}", max_bytes=8 << 20)
        licence = (payload.get("license") or {}).get("name")
        spdx = (payload.get("license") or {}).get("spdx_id")
        if spdx in ("NOASSERTION", None) and not licence:
            licence = None

        readme = ""
        try:
            readme = client.get(
                f"{API}/repos/{repo}/readme",
                accept="application/vnd.github.raw",
                max_bytes=4 << 20,
            ).text()
        except http.TransferError:
            # A repository with no README is unusual but not an error; the access route
            # is then simply unknown, which is what gets recorded.
            readme = ""

        haystack = f"{payload.get('description') or ''} {readme}".casefold()
        by_request = any(marker in haystack for marker in REQUEST_MARKERS)
        access = SourceAccess.AGREEMENT_REQUIRED if by_request else SourceAccess.OPEN

        default_branch = payload.get("default_branch") or "main"
        return RemoteDataset(
            external_id=repo,
            name=payload.get("full_name") or repo,
            description=" ".join(str(payload.get("description") or "").split())[:4000],
            source_url=payload.get("html_url") or f"https://github.com/{repo}",
            download_url=f"{API}/repos/{repo}/tarball/{default_branch}",
            download_mechanism="GitHub repository tarball",
            dataset_type=SOURCE_CODE,
            granularity=Granularity.UNKNOWN,
            access_status=access,
            licence=licence,
            licence_url=f"https://github.com/{repo}" if licence else None,
            publisher_version=default_branch,
            publisher_updated_at=_parsed_time(payload.get("pushed_at")),
            bytes_claimed=int(payload.get("size") or 0) * 1024 or None,
            relevance=3 if "burn" in haystack else 1,
            notes=(
                "The README indicates the imagery is obtained by request rather than from "
                "the repository. What is here is the reference implementation; the dataset "
                "itself has to be requested from the authors."
                if by_request
                else "This repository holds a reference implementation. Any dataset it "
                "describes may be distributed separately."
            )
            + ("" if licence else " The repository declares no LICENSE file."),
        )

    def fetch(self, dataset: RemoteDataset, destination: Path, *, max_bytes: int) -> Acquired:
        if not dataset.download_url:
            raise Unavailable("no tarball URL for this repository")
        client = self.client()
        archive = destination / "repository.tar.gz"
        try:
            downloaded = client.download(dataset.download_url, archive, max_bytes=max_bytes)
        except http.TransferError as exc:
            raise Unavailable(str(exc)) from exc

        extracted = destination / "files"
        files = tuple(safe_extract(archive, extracted, max_bytes=max_bytes))
        archive.unlink(missing_ok=True)
        if not files:
            raise Unavailable("the tarball held no files")

        from backend.sync.fingerprint import of_directory

        return Acquired(
            files=files,
            bytes=sum(path.stat().st_size for path in files),
            sha256=of_directory(extracted),
            file_format=dominant_format(files),
            version=dataset.publisher_version or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            retrieved_from=downloaded.url,
            notes=(
                f"{len(files)} file(s) from the repository at "
                f"{dataset.publisher_version}. This is code and documentation, not the "
                "dataset the repository describes."
            ),
        )


GITHUB = GitHub(
    code="github",
    label="GitHub research repositories",
    organisation="GitHub",
    homepage="https://github.com",
    hosts=("api.github.com", "github.com", "codeload.github.com", "objects.githubusercontent.com"),
    default_config={
        "repositories": ["VEDAs-Lab/EBIS", "xjtu-mia/BurnAnalysis"],
    },
)
