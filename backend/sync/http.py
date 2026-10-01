"""HTTP access to dataset publishers.

This is deliberately not `app.epidemic.net`. That module talks to a fixed list of URLs
written into the source code, so it can afford to trust them. Here the URLs arrive *in the
response body of a remote API* — Socrata hands back a download link, Kaggle hands back an
archive path — and a publisher that is compromised, misconfigured or simply wrong can
therefore point this worker at anything the container can reach. So every URL is checked
against the publisher's own host before it is opened, redirects are followed by hand with
the same check applied at each hop, and addresses that resolve inside the network are
refused.

The other difference is conditional requests. Discovery runs every few hours against the
same endpoints; sending the stored ETag turns most of those runs into a 304 and keeps the
pipeline a polite client of services that are paying for the bandwidth.
"""

from __future__ import annotations

import gzip
import hashlib
import ipaddress
import json
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import get_settings

USER_AGENT = (
    "painsense-dataset-sync/1.0 (research platform, University of Batna 2; "
    "contact via repository)"
)
CHUNK = 1 << 20
MAX_REDIRECTS = 5
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class TransferError(RuntimeError):
    """The publisher could not be reached, or refused.

    `status` is the HTTP status where there was one. A 401 or 403 is not a defect in this
    pipeline — it is the publisher saying the resource is not open — and the caller records
    it as an access fact rather than retrying it.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in RETRY_STATUSES


class BlockedHost(TransferError):
    """The URL pointed somewhere this worker will not go."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8", errors="replace"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Downloaded:
    path: Path
    bytes: int
    sha256: str
    content_type: str
    url: str


def _host_of(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise BlockedHost(f"{url!r} has no host")
    return host.lower()


def _registrable_suffix_match(host: str, allowed: str) -> bool:
    """True when `host` is `allowed` or a subdomain of it.

    Compared label-wise rather than with `endswith`, so `evil-who.int` does not pass as
    `who.int`.
    """
    host_parts = host.split(".")
    allowed_parts = allowed.lower().strip(".").split(".")
    return host_parts[-len(allowed_parts) :] == allowed_parts


def _public_address(host: str) -> None:
    """Refuse a host that resolves anywhere inside the network.

    Resolution happens here and the request is made by name immediately afterwards, so a
    hostile DNS server could in principle answer differently the second time. Closing that
    window entirely means pinning the socket to the checked address, which breaks TLS SNI
    and virtual hosting; refusing the obvious cases is the proportionate control for a
    worker that only ever talks to a short list of public publishers.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise TransferError(f"{host} could not be resolved: {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global or address.is_multicast:
            raise BlockedHost(f"{host} resolves to the non-public address {address}")


def _check(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise BlockedHost(f"{url!r} is not https")
    host = _host_of(url)
    if allowed_hosts and not any(_registrable_suffix_match(host, a) for a in allowed_hosts):
        raise BlockedHost(f"{host} is not among the hosts declared for this source")
    _public_address(host)


def _retry_after(headers: dict[str, str], fallback: float) -> float:
    raw = headers.get("retry-after", "")
    if raw.isdigit():
        return min(float(raw), 120.0)
    return fallback


@dataclass
class Client:
    """A client bound to one publisher's hosts.

    `allowed_hosts` is the publisher's own declaration of where its data lives. An empty
    tuple means no host restriction, which no adapter in this package uses.
    """

    allowed_hosts: tuple[str, ...] = ()
    auth_header: str | None = None
    timeout: int = 0
    retries: int = 2
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.timeout = self.timeout or get_settings().sync_request_timeout_seconds

    def _headers(self, accept: str | None, conditional: dict[str, str] | None) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", **self.extra_headers}
        if accept:
            headers["Accept"] = accept
        if self.auth_header:
            headers["Authorization"] = self.auth_header
        for name, value in (conditional or {}).items():
            headers[name] = value
        return headers

    def _open(self, url: str, headers: dict[str, str], timeout: int):
        """One request, following redirects by hand so each hop is checked."""
        seen = url
        for _ in range(MAX_REDIRECTS + 1):
            _check(seen, self.allowed_hosts)
            request = Request(seen, headers=headers)
            request.get_method = lambda: "GET"
            try:
                response = urlopen(request, timeout=timeout)
            except HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    target = exc.headers.get("location")
                    if not target:
                        raise TransferError(
                            f"{seen} redirected without a location", status=exc.code
                        ) from exc
                    seen = urllib.parse.urljoin(seen, target)
                    continue
                raise
            if response.status in (301, 302, 303, 307, 308):
                target = response.headers.get("location")
                response.close()
                if not target:
                    raise TransferError(f"{seen} redirected without a location")
                seen = urllib.parse.urljoin(seen, target)
                continue
            return response
        raise TransferError(f"{url} redirected more than {MAX_REDIRECTS} times")

    def _attempt(self, url: str, headers: dict[str, str], timeout: int, handler):
        delay = 2.0
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._open(url, headers, timeout)
            except BlockedHost:
                raise
            except HTTPError as exc:
                if exc.code == 304:
                    return Response(304, _lower(exc.headers), b"", url)
                if exc.code not in RETRY_STATUSES or attempt == self.retries:
                    raise TransferError(
                        f"{url} returned HTTP {exc.code}", status=exc.code
                    ) from exc
                delay = _retry_after(_lower(exc.headers), delay)
                last = exc
            except (URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt == self.retries:
                    break
            else:
                with response:
                    return handler(response)
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        raise TransferError(f"{url} could not be reached: {last}")

    def get(
        self,
        url: str,
        *,
        accept: str | None = None,
        etag: str | None = None,
        modified_since: str | None = None,
        max_bytes: int = 64 << 20,
        timeout: int | None = None,
    ) -> Response:
        """Fetch a document into memory, with an optional conditional request.

        A 304 comes back as a `Response` with that status and an empty body, which is the
        signal the caller wants: nothing has changed, do no further work.
        """
        conditional = {}
        if etag:
            conditional["If-None-Match"] = etag
        if modified_since:
            conditional["If-Modified-Since"] = modified_since

        def read(response) -> Response:
            body = _decode(response, response.read(max_bytes + 1))
            if len(body) > max_bytes:
                raise TransferError(f"{url} returned more than {max_bytes} bytes")
            return Response(response.status, _lower(response.headers), body, response.url)

        return self._attempt(url, self._headers(accept, conditional), timeout or self.timeout, read)

    def get_json(self, url: str, **kwargs) -> Any:
        return self.get(url, accept="application/json", **kwargs).json()

    def download(self, url: str, destination: Path, *, max_bytes: int) -> Downloaded:
        """Stream a resource to disk, refusing anything over `max_bytes`.

        The digest is taken from the bytes as they are written rather than by re-reading
        the file afterwards, so what is recorded is what actually arrived. The file lands
        at its final name only once it is complete, so an interrupted download cannot be
        mistaken for a dataset.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")

        def stream(response) -> Downloaded:
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise TransferError(
                    f"{url} declares {int(declared)} bytes, over the {max_bytes} byte limit"
                )
            digest = hashlib.sha256()
            written = 0
            try:
                with partial.open("wb") as handle:
                    while chunk := response.read(CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            raise TransferError(
                                f"{url} exceeded the {max_bytes} byte limit while downloading"
                            )
                        handle.write(chunk)
                        digest.update(chunk)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            partial.replace(destination)
            return Downloaded(
                path=destination,
                bytes=written,
                sha256=digest.hexdigest(),
                content_type=(response.headers.get("content-type") or "").split(";")[0].strip(),
                url=response.url,
            )

        return self._attempt(
            url, self._headers(None, None), get_settings().sync_request_timeout_seconds * 10, stream
        )


def _lower(headers) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _decode(response, body: bytes) -> bytes:
    if (response.headers.get("content-encoding") or "").lower() == "gzip":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError):
            return body
    return body
