from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from . import registry
from .discover import parse_physionet_project
from .fetch import (
    FetchError,
    download_to,
    flatten_markup,
    get_text,
    kaggle_archive_url,
    load_credentials,
    quote_matching,
    section,
)
from .profile import profile_dataset
from .registry import (
    BIOVID_ACCESS_REPORT,
    KAGGLE_CATALOG_PATH,
    PHYSIONET_ACCESS_REPORT,
    RAW_DIR,
    TAME_PAIN_ACCESS_REPORT,
    ensure,
)
from .sources import dataset_id_for_reference

PHYSIONET_ARCHIVE_URL = (
    "https://physionet.org/static/published-projects/{slug}/{slug}-{version}.zip"
)

SKIP_KINDS = {
    PermissionError: "access_or_licence_refused",
    FileExistsError: "already_present",
    LookupError: "not_discovered",
    ValueError: "unsafe_archive",
}


def skip_kind(error: Exception) -> str:
    for kind_type, name in SKIP_KINDS.items():
        if isinstance(error, kind_type):
            return name
    return "fetch_failed"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> list[Path]:
    ensure(destination)
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe path in archive: {member.filename!r}")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as handle:
                while chunk := source.read(1 << 20):
                    handle.write(chunk)
            extracted.append(target)
    return sorted(extracted)


def _file_digests(files: list[Path], root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
        }
        for path in files
    ]


def kaggle_catalog_record(dataset_ref: str) -> dict[str, Any] | None:
    if not KAGGLE_CATALOG_PATH.exists():
        return None
    catalog = json.loads(KAGGLE_CATALOG_PATH.read_text(encoding="utf-8"))
    for row in catalog.get("results", []):
        if row.get("dataset_id") == dataset_ref:
            return row
    return None


def download_kaggle(
    dataset_ref: str, *, force: bool, licence_override: str | None
) -> dict[str, Any]:
    record = kaggle_catalog_record(dataset_ref)
    verdict = (record or {}).get("license_verdict", "unknown")
    license_name = (record or {}).get("license")

    if verdict != "permissive" and licence_override is None:
        raise PermissionError(
            f"licence verdict for {dataset_ref} is {verdict!r} ({license_name!r}); "
            "pass --accept-reviewed-license '<reason>' to record a human review before downloading"
        )

    slug = dataset_ref.replace("/", "__")
    dataset_dir = RAW_DIR / "kaggle" / slug
    archive = dataset_dir / f"{slug}.zip"
    extracted_dir = dataset_dir / "extracted"

    if archive.exists() and not force:
        raise FileExistsError(
            f"{archive} already exists; pass --force to replace the previously downloaded archive"
        )

    ensure(dataset_dir)
    size = download_to(kaggle_archive_url(dataset_ref), archive)
    if not zipfile.is_zipfile(archive):
        head = archive.read_bytes()[:200]
        archive.unlink()
        raise FetchError(
            f"Kaggle did not return an archive for {dataset_ref}; the response began {head[:80]!r}. "
            "A public dataset answers anonymously; a private one needs credentials in "
            "~/.kaggle/kaggle.json."
        )

    files = safe_extract(archive, extracted_dir)
    return {
        "dataset_id": dataset_ref,
        "status": "downloaded",
        "source": "kaggle",
        "source_url": f"https://www.kaggle.com/datasets/{dataset_ref}",
        "download_url": kaggle_archive_url(dataset_ref),
        "downloaded_at": registry.now(),
        "dataset_version": (record or {}).get("version"),
        "license": license_name,
        "license_verdict": verdict,
        "license_review_reason": licence_override,
        "authenticated": load_credentials() is not None,
        "archive_path": str(archive),
        "archive_bytes": size,
        "archive_sha256": sha256_of(archive),
        "local_path": str(extracted_dir),
        "file_count": len(files),
        "files": _file_digests(files, extracted_dir),
    }


def record_kaggle_download(dataset_ref: str, result: dict[str, Any]) -> None:
    catalog = kaggle_catalog_record(dataset_ref) or {}
    registry.record_licence(
        result["dataset_id"],
        name=catalog.get("dataset_name") or dataset_ref,
        license=result["license"],
        license_url=result["source_url"],
        source_url=result["source_url"],
        redistribution="not redistributed; the archive stays in the local raw directory",
        notes=result.get("license_review_reason") or "licence verdict: permissive",
    )
    registry.upsert([
        registry.entry(
            dataset_id_for_reference(dataset_ref)
            or f"kaggle_{dataset_ref.replace('/', '_').replace('-', '_')}",
            catalog.get("dataset_name") or dataset_ref,
            "Kaggle",
            result["source_url"],
            "open",
            download_url=result["download_url"],
            license=result["license"],
            version=str(result["dataset_version"]) if result["dataset_version"] else None,
            retrieved_at=result["downloaded_at"],
            local_path=result["local_path"],
            notes=(
                f"Archive sha256 {result['archive_sha256'][:16]}, "
                f"{result['file_count']} file(s) extracted."
            ),
        )
    ])


def physionet_record(slug: str) -> dict[str, Any] | None:
    if not PHYSIONET_ACCESS_REPORT.exists():
        return None
    report = json.loads(PHYSIONET_ACCESS_REPORT.read_text(encoding="utf-8"))
    for record in report.get("resources", []):
        if record.get("slug") == slug:
            return record
    return None


def download_physionet(slug: str, *, force: bool) -> dict[str, Any]:
    record = physionet_record(slug)
    if record is None:
        raise LookupError(
            f"{slug} is not in {PHYSIONET_ACCESS_REPORT.name}; run the physionet discovery step "
            "first so the access status is read from PhysioNet before anything is fetched"
        )

    status = record.get("access_status")
    if status != "open":
        raise PermissionError(
            f"{slug} has access status {status!r}: "
            f'PhysioNet states "{record.get("access_sentence")}". '
            "Obtaining it requires a signed agreement under a named person's account, so this "
            "pipeline does not download it."
        )

    version = record.get("version")
    if not version:
        raise LookupError(f"{slug} has no parsed version; cannot form the archive URL")

    dataset_dir = RAW_DIR / "physionet" / slug
    archive = dataset_dir / f"{slug}-{version}.zip"
    extracted_dir = dataset_dir / "extracted"

    if archive.exists() and not force:
        raise FileExistsError(f"{archive} already exists; pass --force to replace it")

    ensure(dataset_dir)
    url = PHYSIONET_ARCHIVE_URL.format(slug=slug, version=version)
    size = download_to(url, archive, timeout=600)
    if not zipfile.is_zipfile(archive):
        archive.unlink()
        raise FetchError(f"{url} did not return a zip archive")

    files = safe_extract(archive, extracted_dir)
    return {
        "dataset_id": slug,
        "status": "downloaded",
        "source": "physionet",
        "source_url": record["source_url"],
        "download_url": url,
        "downloaded_at": registry.now(),
        "dataset_version": version,
        "license": record.get("license"),
        "license_verdict": "open access, licence stated on the project page",
        "doi": record.get("doi"),
        "archive_path": str(archive),
        "archive_bytes": size,
        "archive_sha256": sha256_of(archive),
        "local_path": str(extracted_dir),
        "file_count": len(files),
        "files": _file_digests(files, extracted_dir),
    }


def record_physionet_download(slug: str, result: dict[str, Any]) -> None:
    registry.upsert([
        registry.entry(
            f"physionet_{slug.replace('-', '_')}",
            slug,
            "PhysioNet",
            result["source_url"],
            "open",
            download_url=result["download_url"],
            license=result["license"],
            version=result["dataset_version"],
            retrieved_at=result["downloaded_at"],
            local_path=result["local_path"],
            notes=(
                f"Downloaded under open access. Archive sha256 "
                f"{result['archive_sha256'][:16]}, {result['file_count']} file(s) extracted."
            ),
        )
    ])


BIOVID_URL = "https://www.nit.ovgu.de/BioVid.html"
BIOVID_ROOT = RAW_DIR / "biovid"

BIOVID_ACCESS_PROCEDURE = [
    "Confirm the intended use is non-commercial research, which is the only use the terms allow",
    "Have a researcher holding a permanent academic position act as the applicant or advisor",
    "Complete and sign the agreement form linked from the BioVid page",
    "Send the signed form to the Medical Psychology group at Ulm University, who authorise access",
    "Wait for authorisation; parts A-D and part E are requested separately",
    "Download the authorised parts through the channel given in the authorisation",
]

BIOVID_PART_PATTERN = re.compile(r"Part ([A-E]): (.+?)(?= Part [A-E]:|$)", re.DOTALL)
BIOVID_COUNT_PATTERN = re.compile(r"([\d,]+) samples; (\d+) subjects?")

TAME_PAIN_URL = "https://physionet.org/content/tame-pain/1.0.0/"
TAME_PAIN_ROOT = RAW_DIR / "tame_pain"

TAME_PAIN_ACCESS_PROCEDURE = [
    "Create a PhysioNet account and sign in",
    "Open the TAME Pain project page and read the PhysioNet Restricted Health Data Use Agreement",
    "Sign the data use agreement for this project under a named account",
    "Download the files once the signed agreement is accepted",
]

TAME_PAIN_COUNT_PATTERNS = {
    "participants": r"(\d{1,4})\s+participants",
    "audio_files": r"([\d,]{1,7})\s+audio files",
    "annotated_utterances": r"([\d,]{1,7})\s+annotated utterances",
}


def parse_biovid_parts(text: str) -> list[dict[str, Any]]:
    organisation = section(text, "Data Organization", length=6000)
    if not organisation:
        return []
    parts: list[dict[str, Any]] = []
    for label, body in BIOVID_PART_PATTERN.findall(organisation):
        condensed = re.sub(r"\s+", " ", body).strip()[:420]
        counts = BIOVID_COUNT_PATTERN.search(condensed)
        parts.append({
            "part": label,
            "description": condensed,
            "samples_stated": int(counts.group(1).replace(",", "")) if counts else None,
            "subjects_stated": int(counts.group(2)) if counts else None,
        })
    return parts


def build_biovid_report() -> dict[str, Any]:
    local = profile_dataset(BIOVID_ROOT, dataset_id="biovid_heat_pain")
    try:
        text = flatten_markup(get_text(BIOVID_URL, timeout=45))
        fetch_error = None
    except FetchError as exc:
        text, fetch_error = "", str(exc)

    non_commercial = "available for non-commercial research only" in text
    needs_agreement = "sign the agreement form" in text
    parts = parse_biovid_parts(text)
    subject_overlap = [part for part in parts if "also occur in Part" in part["description"]]

    if fetch_error:
        access_status = "unknown"
    elif needs_agreement:
        access_status = "request_required"
    else:
        access_status = "unknown"

    return {
        "dataset_id": "biovid_heat_pain",
        "name": "BioVid Heat Pain Database",
        "source_url": BIOVID_URL,
        "checked_at": registry.now(),
        "fetch_error": fetch_error,
        "access_status": access_status,
        "download_status": "downloaded" if local.get("has_tabular_data") else "not_downloaded",
        "local_path": str(BIOVID_ROOT) if local.get("exists") else None,
        "local_profile": local,
        "license": "non-commercial research only" if non_commercial else None,
        "authorising_body": (
            "Medical Psychology group, Ulm University"
            if "Medical Psychology group" in text else None
        ),
        "required_access_procedure": BIOVID_ACCESS_PROCEDURE,
        "evidence": quote_matching(
            text, "non-commercial", "agreement form", "authorizing the access", limit=5
        ),
        "documented_parts": parts,
        "documented_subject_overlap": [
            {"part": part["part"], "note": part["description"][:200]} for part in subject_overlap
        ],
        "leakage_warning": (
            "The page states that subjects recur across parts, so combining parts without "
            "grouping on subject identity would place one subject's samples on both sides of "
            "a train/test split."
            if subject_overlap else None
        ),
        "notes": (
            "Nothing was downloaded. The access terms require a signed agreement authorised by "
            "a named group, which a person holds, not this pipeline. Sample and subject counts "
            "above are the publisher's stated figures, not measurements of local files."
        ),
    }


def check_biovid_access() -> dict[str, Any]:
    report = build_biovid_report()
    ensure(BIOVID_ACCESS_REPORT.parent)
    BIOVID_ACCESS_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    stated_subjects = [
        part["subjects_stated"] for part in report["documented_parts"] if part["subjects_stated"]
    ]
    registry.upsert([
        registry.entry(
            "biovid_heat_pain",
            report["name"],
            "BioVid",
            BIOVID_URL,
            report["access_status"],
            license=report["license"],
            retrieved_at=report["checked_at"],
            local_path=report["local_path"],
            modalities=(
                ["frontal video", "GSR", "ECG", "EMG"] if report["documented_parts"] else []
            ),
            subjects=max(stated_subjects) if stated_subjects else None,
            records=None,
            pain_labels=(
                ["heat pain stimulus intensity class (5 levels)"]
                if report["documented_parts"] else []
            ),
            target_available=bool(report["documented_parts"]),
            notes=(
                f"Access requires a signed agreement authorised by {report['authorising_body']}. "
                f"Publisher documents {len(report['documented_parts'])} parts. "
                "Subject and label figures are the publisher's, not measured locally. "
                "No files downloaded."
            ),
        )
    ])
    registry.record_licence(
        "biovid_heat_pain",
        name=report["name"],
        license=report["license"],
        license_url=BIOVID_URL,
        source_url=BIOVID_URL,
        redistribution="not obtained and not redistributed",
        notes="non-commercial research only, by signed agreement",
    )

    return {
        "report": str(BIOVID_ACCESS_REPORT),
        "access_status": report["access_status"],
        "download_status": report["download_status"],
        "documented_parts": [
            {k: part[k] for k in ("part", "samples_stated", "subjects_stated")}
            for part in report["documented_parts"]
        ],
        "leakage_warning": report["leakage_warning"],
    }


def parse_tame_pain_counts(text: str) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for name, pattern in TAME_PAIN_COUNT_PATTERNS.items():
        match = re.search(pattern, text)
        counts[name] = int(match.group(1).replace(",", "")) if match else None
    return counts


def build_tame_pain_report() -> dict[str, Any]:
    local = profile_dataset(TAME_PAIN_ROOT, dataset_id="tame_pain")
    try:
        page = get_text(TAME_PAIN_URL, timeout=45)
        fetch_error = None
    except FetchError as exc:
        page, fetch_error = "", str(exc)

    parsed = parse_physionet_project(page) if page else {"access_status": "unknown"}
    text = flatten_markup(page) if page else ""
    counts = parse_tame_pain_counts(text)

    return {
        "dataset_id": "tame_pain",
        "name": parsed.get("title") or "TAME Pain",
        "source_url": TAME_PAIN_URL,
        "checked_at": registry.now(),
        "fetch_error": fetch_error,
        "access_status": parsed.get("access_status", "unknown"),
        "access_sentence": parsed.get("access_sentence"),
        "download_status": "downloaded" if local.get("has_tabular_data") else "not_downloaded",
        "local_path": str(TAME_PAIN_ROOT) if local.get("exists") else None,
        "local_profile": local,
        "license": parsed.get("license"),
        "data_use_agreement": parsed.get("data_use_agreement"),
        "version": parsed.get("version"),
        "doi": parsed.get("doi"),
        "topics": parsed.get("topics", []),
        "required_access_procedure": TAME_PAIN_ACCESS_PROCEDURE,
        "stated_counts": counts,
        "stated_counts_note": (
            "These are the authors' published figures, not measurements of local files. The "
            "audio-file count and the annotated-utterance count differ, so a record count "
            "depends on which the analysis treats as a record."
        ),
        "pain_labels": [
            "self-reported pain level, 1-10, collected during a cold pressor task",
            "binary pain / no pain",
            "three-class pain categorisation",
        ] if "self-reported pain" in text.lower() else [],
        "evidence": quote_matching(
            text, "participants", "self-reported pain", "annotated utterances", limit=5
        ),
        "notes": (
            "Nothing was downloaded. The resource requires a data use agreement signed under a "
            "named PhysioNet account, which a person holds, not this pipeline."
        ),
    }


def check_tame_pain_access() -> dict[str, Any]:
    report = build_tame_pain_report()
    ensure(TAME_PAIN_ACCESS_REPORT.parent)
    TAME_PAIN_ACCESS_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    registry.upsert([
        registry.entry(
            "physionet_tame_pain",
            report["name"],
            "PhysioNet",
            TAME_PAIN_URL,
            report["access_status"],
            license=report["license"],
            version=report["version"],
            retrieved_at=report["checked_at"],
            local_path=report["local_path"],
            modalities=report["topics"],
            subjects=report["stated_counts"].get("participants"),
            records=report["stated_counts"].get("annotated_utterances"),
            pain_labels=report["pain_labels"],
            target_available=bool(report["pain_labels"]),
            notes=(
                f'Access policy: "{report["access_sentence"]}". '
                "Subject and record figures are the authors' published counts, not measured "
                "locally. No files downloaded."
            ),
        )
    ])
    registry.record_licence(
        "physionet_tame_pain",
        name=report["name"],
        license=report["license"],
        license_url=TAME_PAIN_URL,
        source_url=TAME_PAIN_URL,
        redistribution="not obtained and not redistributed",
        notes=f"requires {report['data_use_agreement']}",
    )

    return {
        "report": str(TAME_PAIN_ACCESS_REPORT),
        "access_status": report["access_status"],
        "download_status": report["download_status"],
        "license": report["license"],
        "stated_counts": report["stated_counts"],
        "pain_labels": report["pain_labels"],
    }
