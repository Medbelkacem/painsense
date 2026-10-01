"""HTTP access to the publishers, with the paging each one actually needs.

Three publishers, three paging conventions: WHO's Global Health Observatory and xMart both
speak OData but only xMart honours `$skip`, and Socrata wants `$offset`. Rather than hide
that behind one leaky abstraction, each convention gets its own function and the source
adapters say which they use.

Everything goes through `_open`, so the user agent, the timeout policy and the retry
budget are set once. There is no authentication anywhere in this module: a resource that
needs credentials is not downloaded, it is registered as requiring them.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = (
    "painsense-epidemic-pipeline/1.0 (research prototype, University of Batna 2; "
    "contact via repository)"
)
CHUNK = 1 << 20
DEFAULT_TIMEOUT = 120
LONG_TIMEOUT = 900


class Unreachable(RuntimeError):
    """The publisher could not be reached, or refused the request.

    `status` is the HTTP status where there was one. A 401 or 403 is not a bug in this
    pipeline, it is the publisher saying the resource is not open, and the caller records
    it that way.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _open(url: str, *, timeout: int, accept: str | None, retries: int):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    if accept:
        request.add_header("Accept", accept)
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as exc:
            # 429 and 5xx are worth another go; a 404 or a 403 will not change.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise Unreachable(f"{url} returned HTTP {exc.code}", status=exc.code) from exc
            last = exc
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt == retries:
                break
        time.sleep(delay)
        delay *= 2
    raise Unreachable(f"{url} could not be reached: {last}")


def get_bytes(url: str, *, timeout: int = DEFAULT_TIMEOUT, accept: str | None = None) -> bytes:
    with _open(url, timeout=timeout, accept=accept, retries=2) as response:
        return response.read()


def get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    return json.loads(get_bytes(url, timeout=timeout, accept="application/json"))


def head(url: str, *, timeout: int = 30) -> dict[str, str]:
    """Probe a resource without downloading it.

    Several of these publishers answer HEAD with 405 while answering GET perfectly well, so
    this issues a GET and closes the connection after the headers.
    """
    with _open(url, timeout=timeout, accept=None, retries=1) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        headers["status"] = str(response.status)
        return headers


def download(url: str, destination: Path, *, timeout: int = LONG_TIMEOUT) -> tuple[int, str]:
    """Stream a resource to disk and return its size and SHA-256.

    The hash is computed from the bytes as they are written rather than by re-reading the
    file, so what is recorded is what was received.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    partial = destination.with_suffix(destination.suffix + ".part")
    with (
        _open(url, timeout=timeout, accept=None, retries=2) as response,
        partial.open("wb") as handle,
    ):
        while chunk := response.read(CHUNK):
            handle.write(chunk)
            digest.update(chunk)
            written += len(chunk)
    partial.replace(destination)
    return written, digest.hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _with_query(url: str, extra: dict[str, Any]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query.update({key: str(value) for key, value in extra.items()})
    return parsed._replace(query=urllib.parse.urlencode(query)).geturl()


def odata_rows(
    url: str, *, page: int = 20_000, limit: int | None = None, timeout: int = DEFAULT_TIMEOUT
) -> Iterator[dict]:
    """Page through an OData v4 collection.

    WHO's GHO endpoint ignores `$skip` and returns the whole indicator in one response, so
    a short first page that comes back complete ends the loop. xMart honours it and is
    paged properly.
    """
    skip = 0
    seen = 0
    while True:
        payload = get_json(_with_query(url, {"$top": page, "$skip": skip}), timeout=timeout)
        rows = payload.get("value", []) if isinstance(payload, dict) else []
        if not rows:
            return
        for row in rows:
            yield row
            seen += 1
            if limit and seen >= limit:
                return
        if len(rows) < page:
            return
        skip += len(rows)


def socrata_rows(
    url: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    page: int = 50_000,
    limit: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Iterator[dict]:
    """Page through a Socrata resource.

    An unordered Socrata query gives no stability guarantee across pages, so `order` is
    always sent; the caller passes a column that is unique enough to make the paging
    deterministic.
    """
    query: dict[str, Any] = {"$order": order or ":id"}
    if select:
        query["$select"] = select
    if where:
        query["$where"] = where
    offset = 0
    seen = 0
    while True:
        want = page if limit is None else min(page, limit - seen)
        if want <= 0:
            return
        rows = get_json(
            _with_query(url, {**query, "$limit": want, "$offset": offset}), timeout=timeout
        )
        if not isinstance(rows, list) or not rows:
            return
        yield from rows
        seen += len(rows)
        if len(rows) < want or (limit is not None and seen >= limit):
            return
        offset += len(rows)
