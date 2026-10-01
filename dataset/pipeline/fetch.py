from __future__ import annotations

import base64
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = "painsense-dataset-pipeline/1.0 (research prototype; contact via repository)"

KAGGLE_API = "https://www.kaggle.com/api/v1"
KAGGLE_CREDENTIALS_PATH = Path.home() / ".kaggle" / "kaggle.json"


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def get(url: str, *, timeout: int = 30, retries: int = 2, accept: str | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    if accept:
        request.add_header("Accept", accept)
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            raise FetchError(f"{url} returned HTTP {exc.code}", status=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{url} could not be reached: {last}")


def get_text(url: str, **kwargs: Any) -> str:
    return get(url, **kwargs).decode("utf-8", errors="replace")


def get_json(url: str, **kwargs: Any) -> Any:
    return json.loads(get(url, accept="application/json", **kwargs))


def peek(url: str, *, size: int = 512, timeout: int = 60) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(size)
    except HTTPError as exc:
        raise FetchError(f"{url} returned HTTP {exc.code}", status=exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise FetchError(f"{url} could not be reached: {exc}") from exc


def download_to(url: str, destination: Path, *, timeout: int = 300) -> int:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                written += len(chunk)
    except HTTPError as exc:
        raise FetchError(f"{url} returned HTTP {exc.code}", status=exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise FetchError(f"{url} could not be reached: {exc}") from exc
    return written


@dataclass(frozen=True)
class Credentials:
    username: str
    key: str

    @property
    def basic_auth(self) -> str:
        raw = f"{self.username}:{self.key}".encode()
        return "Basic " + base64.b64encode(raw).decode()


def load_credentials() -> Credentials | None:
    if not KAGGLE_CREDENTIALS_PATH.exists():
        return None
    try:
        payload = json.loads(KAGGLE_CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    username, key = payload.get("username"), payload.get("key")
    if not username or not key:
        return None
    return Credentials(username=username, key=key)


def search_kaggle(query: str, *, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
    url = f"{KAGGLE_API}/datasets/list?search={quote(query)}&page={page}&pageSize={page_size}"
    payload = get_json(url, timeout=45)
    if not isinstance(payload, list):
        raise FetchError(f"unexpected search payload for {query!r}: {type(payload).__name__}")
    return payload


def kaggle_archive_url(dataset_ref: str) -> str:
    return f"{KAGGLE_API}/datasets/download/{dataset_ref}"


def probe_kaggle_archive(dataset_ref: str) -> tuple[bool, str]:
    try:
        head = peek(kaggle_archive_url(dataset_ref))
    except FetchError as exc:
        return False, f"HTTP error: {exc}"
    if head[:2] == b"PK":
        return True, "zip archive"
    if b"<!DOCTYPE html" in head[:400] or b"<html" in head[:400]:
        return False, "login or error page returned instead of an archive"
    return False, "response was not a zip archive"


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def flatten_markup(markup: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", markup, flags=re.DOTALL | re.IGNORECASE
    )
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", without_scripts))).strip()


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]


def quote_matching(text: str, *keywords: str, limit: int = 6) -> list[str]:
    lowered = [keyword.lower() for keyword in keywords]
    found: list[str] = []
    for sentence in sentences(text):
        if any(keyword in sentence.lower() for keyword in lowered):
            cleaned = re.sub(r"writeEmail\([^)]*\)", "[email address on the page]", sentence)
            if cleaned not in found:
                found.append(cleaned[:400])
        if len(found) >= limit:
            break
    return found


def section(text: str, heading: str, *, length: int = 2000) -> str | None:
    index = text.find(heading)
    return text[index : index + length] if index >= 0 else None
