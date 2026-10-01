from __future__ import annotations

import html
import json
import re
from typing import Any

from . import registry
from .fetch import FetchError, get_text, load_credentials, search_kaggle
from .registry import KAGGLE_CATALOG_PATH, PHYSIONET_ACCESS_REPORT, ensure

KAGGLE_QUERIES = (
    "pain",
    "pain assessment",
    "pain intensity",
    "pain recognition",
    "pain detection",
    "physiological pain",
    "heat pain",
    "chronic pain",
    "acute pain",
    "multimodal pain",
    "pain ECG",
    "pain EDA",
    "pain GSR",
    "pain HRV",
    "pain respiration",
    "pain temperature",
    "pain EMG",
    "pain facial expression",
    "pain speech",
    "pain clinical data",
    "pain NRS",
    "pain VAS",
    "patient pain scores",
)

PERMISSIVE_LICENCES = {
    "cc0: public domain",
    "cc0-1.0",
    "cc by 4.0",
    "cc-by-4.0",
    "cc by-sa 4.0",
    "cc-by-sa-4.0",
    "cc by-nc-sa 4.0",
    "database: open database, contents: database contents",
    "database: open database, contents: original author",
    "odbl-1.0",
    "apache 2.0",
    "mit",
    "gpl 2",
    "u.s. government works",
    "community data license agreement - permissive - version 1.0",
    "community data license agreement - sharing - version 1.0",
}

MODALITY_KEYWORDS = {
    "ecg": ("ecg", "electrocardiogram"),
    "eda": ("eda", "electrodermal"),
    "gsr": ("gsr", "galvanic skin"),
    "emg": ("emg", "electromyograph"),
    "eeg": ("eeg", "electroencephalo"),
    "hrv": ("hrv", "heart rate variability"),
    "heart_rate": ("heart rate", "pulse", "bpm"),
    "respiration": ("respiration", "respiratory", "breathing"),
    "temperature": ("temperature", "thermal"),
    "blood_pressure": ("blood pressure", "systolic", "diastolic"),
    "spo2": ("spo2", "oxygen saturation", "oximetry"),
    "video": ("video", "frames"),
    "image": ("image", "photo", "facial", "face"),
    "audio": ("audio", "speech", "voice", "vocal"),
    "text": ("notes", "text", "report", "questionnaire", "survey"),
    "tabular_clinical": ("clinical", "patient", "diagnosis", "symptom", "ehr", "records"),
}

TARGET_KEYWORDS = {
    "nrs": ("nrs", "numeric rating"),
    "vas": ("vas", "visual analog", "visual analogue"),
    "pain_intensity": ("pain intensity", "pain level", "pain score", "pain severity"),
    "pain_present": ("pain detection", "pain recognition", "pain classification", "no pain"),
    "pain_type": ("pain type", "neuropathic", "nociceptive"),
}

RELEVANCE_KEYWORDS = {
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
    "nrs": 3,
    "vas": 2,
    "pain": 2,
    "migraine": 1,
    "headache": 1,
    "arthritis": 1,
}

PHYSIONET_BASE = "https://physionet.org"
PHYSIONET_TOPIC_URL = f"{PHYSIONET_BASE}/content/?topic={{topic}}"
PHYSIONET_INDEX_URL = f"{PHYSIONET_BASE}/about/database/"

PHYSIONET_TOPICS = ("pain", "nociception", "analgesia")
PHYSIONET_TITLE_KEYWORDS = ("pain", "nocicep", "analgesi", "opioid")

ACCESS_SENTENCES = (
    (
        ("Anyone can access the files, as long as they conform to the terms of the specified "
        "license"), "open",
    ),
    ("Only credentialed users who sign the DUA can access the files", "credentialed"),
    (
        ("Only credentialed users who sign the specified data use agreement can access the "
        "files"), "credentialed",
    ),
    (
        ("Only registered users who sign the specified data use agreement can access the "
        "files"), "restricted",
    ),
    ("Only registered users who sign the DUA can access the files", "restricted"),
)

ACCESS_PROCEDURE = {
    "open": [
        "Read the licence stated on the project page",
        "Download the files directly; no account is required",
    ],
    "restricted": [
        "Create a PhysioNet account and sign in",
        "Open the project page and read the data use agreement",
        "Sign the data use agreement for this specific project",
        "Download the files once the signed agreement is accepted",
    ],
    "credentialed": [
        "Create a PhysioNet account and sign in",
        "Complete PhysioNet credentialing, which requires a CITI human-subjects training report",
        "Wait for the credentialing application to be reviewed and approved",
        "Sign the data use agreement for this specific project",
        "Download the files once credentialing and the agreement are both in place",
    ],
    "unknown": ["Read the project page and follow the access instructions stated there"],
}


def _text_of(row: dict[str, Any]) -> str:
    parts = (row.get("title") or "", row.get("subtitle") or "", row.get("description") or "")
    return " ".join(parts).lower()


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _matches(text: str, keywords: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(
        key for key, needles in keywords.items() if any(_contains(text, n) for n in needles)
    )


def _relevance(text: str) -> tuple[int, list[str]]:
    hits = [
        (phrase, weight)
        for phrase, weight in RELEVANCE_KEYWORDS.items()
        if _contains(text, phrase)
    ]
    if not hits:
        return 0, []
    score = sum(weight for _, weight in hits)
    reasons = [phrase for phrase, _ in sorted(hits, key=lambda item: -item[1])]
    return score, reasons


def _licence_verdict(license_name: str | None) -> str:
    if not license_name:
        return "unknown"
    return (
        "permissive" if license_name.strip().lower() in PERMISSIVE_LICENCES else "review_required"
    )


def describe_kaggle_row(row: dict[str, Any], query: str) -> dict[str, Any]:
    text = _text_of(row)
    score, reasons = _relevance(text)
    license_name = row.get("licenseName")
    return {
        "dataset_id": row.get("ref"),
        "dataset_name": row.get("title"),
        "owner": row.get("ownerName") or row.get("ownerRef"),
        "owner_ref": row.get("ownerRef"),
        "dataset_url": row.get("url"),
        "description": row.get("subtitle") or row.get("description") or "",
        "license": license_name,
        "license_verdict": _licence_verdict(license_name),
        "size_bytes": row.get("totalBytes"),
        "update_date": row.get("lastUpdated"),
        "version": row.get("currentVersionNumber"),
        "usability_rating": row.get("usabilityRating"),
        "download_count": row.get("downloadCount"),
        "vote_count": row.get("voteCount"),
        "is_private": row.get("isPrivate"),
        "file_list": [],
        "file_list_status": "not_retrieved: the Kaggle file-listing endpoint requires credentials",
        "available_modalities": _matches(text, MODALITY_KEYWORDS),
        "target_variables": _matches(text, TARGET_KEYWORDS),
        "inference_basis": (
            "modalities and target variables are inferred from the published title, subtitle "
            "and description, not from file contents"
        ),
        "records": None,
        "authentication_required": False,
        "matched_queries": [query],
        "relevance_score": score,
        "relevance_reasons": reasons,
    }


def build_kaggle_catalog(queries: tuple[str, ...], page_size: int) -> dict[str, Any]:
    credentials = load_credentials()
    by_ref: dict[str, dict[str, Any]] = {}
    executed: list[dict[str, Any]] = []

    for query in queries:
        try:
            rows = search_kaggle(query, page_size=page_size)
        except FetchError as exc:
            executed.append({"query": query, "status": "failed", "detail": str(exc), "results": 0})
            continue
        executed.append({"query": query, "status": "ok", "results": len(rows)})
        for row in rows:
            ref = row.get("ref")
            if not ref:
                continue
            described = describe_kaggle_row(row, query)
            known = by_ref.get(ref)
            if known is None:
                by_ref[ref] = described
            elif query not in known["matched_queries"]:
                known["matched_queries"].append(query)

    results = sorted(
        by_ref.values(),
        key=lambda item: (
            -item["relevance_score"], -(item["download_count"] or 0), item["dataset_id"]
        ),
    )
    failed = [item for item in executed if item["status"] == "failed"]
    return {
        "generated_at": registry.now(),
        "source": "kaggle",
        "api_endpoint": "https://www.kaggle.com/api/v1/datasets/list",
        "credentials_present": credentials is not None,
        "api_status": "reachable" if any(i["status"] == "ok" for i in executed) else "unreachable",
        "queries_executed": executed,
        "queries_failed": len(failed),
        "unique_datasets": len(results),
        "results": results,
        "notes": (
            "Search ran against Kaggle's public dataset API. File listings require credentials "
            "and were not retrieved. No dataset was downloaded by this step."
        ),
    }


def discover_kaggle(
    queries: tuple[str, ...] = KAGGLE_QUERIES, page_size: int = 20
) -> dict[str, Any]:
    catalog = build_kaggle_catalog(queries, page_size)
    ensure(KAGGLE_CATALOG_PATH.parent)
    KAGGLE_CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return {
        "catalog_path": str(KAGGLE_CATALOG_PATH),
        "api_status": catalog["api_status"],
        "unique_datasets": catalog["unique_datasets"],
        "queries_failed": catalog["queries_failed"],
        "top_candidates": [
            {
                "dataset_id": item["dataset_id"],
                "relevance_score": item["relevance_score"],
                "license_verdict": item["license_verdict"],
                "size_bytes": item["size_bytes"],
            }
            for item in catalog["results"][:10]
        ],
    }


def _strip_tags(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


def _slugs_from_topic(topic: str) -> dict[str, str]:
    try:
        page = get_text(PHYSIONET_TOPIC_URL.format(topic=topic), timeout=45)
    except FetchError:
        return {}
    found: dict[str, str] = {}
    for path in re.findall(r'href="(/content/[a-z0-9][a-z0-9./-]*/)"', page):
        parts = [part for part in path.strip("/").split("/") if part != "content"]
        if parts:
            found.setdefault(parts[0], path)
    return found


def _slugs_from_index() -> dict[str, str]:
    try:
        page = get_text(PHYSIONET_INDEX_URL, timeout=60)
    except FetchError:
        return {}
    found: dict[str, str] = {}
    for path, title in re.findall(r'href="(/content/[a-z0-9][a-z0-9.-]*/)">([^<]*)</a>', page):
        if any(keyword in title.lower() for keyword in PHYSIONET_TITLE_KEYWORDS):
            found.setdefault(path.strip("/").split("/")[-1], path)
    return found


def parse_physionet_project(page: str) -> dict[str, Any]:
    text = html.unescape(_strip_tags(page))

    access_status = "unknown"
    access_sentence = None
    for sentence, status in ACCESS_SENTENCES:
        if sentence in text:
            access_status, access_sentence = status, sentence
            break

    licence = version = dua = None
    licence_match = re.search(
        r'href="/content/[^"]*/view-license/([0-9.]+)/"[^>]*>([^<]+)</a>', page
    )
    if licence_match:
        version, licence = licence_match.group(1), html.unescape(licence_match.group(2)).strip()

    dua_match = re.search(r'href="/content/[^"]*/view-dua/[0-9.]+/"[^>]*>([^<]+)</a>', page)
    if dua_match:
        dua = html.unescape(dua_match.group(1)).strip()

    if version is None:
        version_match = re.search(r"DOI \(v([0-9.]+)\)", text)
        if version_match:
            version = version_match.group(1)

    doi = None
    doi_match = re.search(r"DOI \(v[0-9.]+\)\s+(10\.\d{4,}/[^\s]+)", text)
    if doi_match:
        doi = doi_match.group(1)

    topics: list[str] = []
    topics_match = re.search(r"Topics\s+(.+?)\s+Project Views", text)
    if topics_match:
        topics = [t for t in topics_match.group(1).split() if t]

    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.DOTALL)
    title = html.unescape(_strip_tags(title_match.group(1))) if title_match else None

    return {
        "title": title,
        "access_status": access_status,
        "access_sentence": access_sentence,
        "license": licence,
        "data_use_agreement": dua,
        "version": version,
        "doi": doi,
        "topics": topics,
    }


def inspect_physionet_project(slug: str, path: str) -> dict[str, Any]:
    url = f"{PHYSIONET_BASE}{path}"
    try:
        page = get_text(url, timeout=60)
    except FetchError as exc:
        return {
            "slug": slug,
            "source_url": url,
            "access_status": "unknown",
            "fetch_error": str(exc),
        }
    return {"slug": slug, "source_url": url, **parse_physionet_project(page)}


def _physionet_entry(record: dict[str, Any]) -> dict[str, Any]:
    status = record.get("access_status", "unknown")
    mentions_pain = any("pain" in topic.lower() for topic in record.get("topics", []))
    notes = []
    if record.get("access_sentence"):
        notes.append(f'PhysioNet states: "{record["access_sentence"]}."')
    if record.get("data_use_agreement"):
        notes.append(f'Data use agreement: {record["data_use_agreement"]}.')
    if record.get("fetch_error"):
        notes.append(f'Project page could not be read: {record["fetch_error"]}.')
    notes.append(
        "Publisher lists pain among the project topics."
        if mentions_pain
        else "Publisher does not list pain among the project topics; kept as a related resource."
    )
    notes.append("No files were downloaded.")

    return registry.entry(
        f"physionet_{record['slug'].replace('-', '_')}",
        record.get("title") or record["slug"],
        "PhysioNet",
        record["source_url"],
        status,
        license=record.get("license"),
        version=record.get("version"),
        retrieved_at=registry.now(),
        modalities=record.get("topics") or [],
        pain_labels=[],
        target_available=False,
        notes=" ".join(notes),
    )


def discover_physionet(
    topics: tuple[str, ...] = PHYSIONET_TOPICS, skip_index: bool = False
) -> dict[str, Any]:
    candidates: dict[str, str] = {}
    sweeps: list[dict[str, Any]] = []
    for topic in topics:
        found = _slugs_from_topic(topic)
        sweeps.append({"sweep": f"topic={topic}", "found": len(found), "slugs": sorted(found)})
        candidates.update(found)
    if not skip_index:
        found = _slugs_from_index()
        sweeps.append({
            "sweep": "database index title keywords",
            "found": len(found),
            "slugs": sorted(found),
        })
        for slug, path in found.items():
            candidates.setdefault(slug, path)

    inspected = [inspect_physionet_project(slug, path) for slug, path in sorted(candidates.items())]
    entries = [_physionet_entry(record) for record in inspected]
    registry.upsert(entries)
    registry.write_manifest("physionet", entries)
    for record, entry in zip(inspected, entries):
        registry.record_licence(
            entry["dataset_id"],
            name=entry["name"],
            license=record.get("license"),
            license_url=record["source_url"],
            source_url=record["source_url"],
            redistribution="not redistributed; no files were downloaded",
            notes=f"access status {entry['access_status']}",
        )

    by_status: dict[str, list[str]] = {}
    for entry in entries:
        by_status.setdefault(entry["access_status"], []).append(entry["dataset_id"])

    report = {
        "generated_at": registry.now(),
        "source": "physionet",
        "sweeps": sweeps,
        "candidates_inspected": len(inspected),
        "by_access_status": {k: sorted(v) for k, v in sorted(by_status.items())},
        "access_procedures": ACCESS_PROCEDURE,
        "resources": inspected,
        "notes": (
            "Access status is parsed from each project page's Access Policy section. No "
            "restricted or credentialed resource was downloaded."
        ),
    }
    ensure(PHYSIONET_ACCESS_REPORT.parent)
    PHYSIONET_ACCESS_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return {
        "report": str(PHYSIONET_ACCESS_REPORT),
        "candidates_inspected": len(inspected),
        "by_access_status": report["by_access_status"],
    }
