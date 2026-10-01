from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from . import acquire, discover, merge, profile, registry, report, statistics
from .fetch import FetchError
from .registry import (
    DATASET_ROOT,
    PIPELINE_RUN_REPORT,
    PROFILE_DIR,
    REPORTS_DIR,
    SOURCES_DIR,
    UNIFIED_FILE,
    ensure,
)
from .schema import DEFAULT_SEED

PROJECT_ROOT = DATASET_ROOT.parent
ACCESS_MARKDOWN = REPORTS_DIR / "access.md"

KAGGLE_SELECTION: tuple[tuple[str, str | None], ...] = (
    ("ziya07/cervical-pain-assessment-dataset-using-vr-mocap", None),
    ("ahsanraza12/pain-detection-biosignals-200-patients", None),
    (
        "messaoudmezati/painspeech-4-arabic-speech-dataset",
        "CC BY-NC 4.0 permits non-commercial use with attribution; this is a non-commercial "
        "academic research prototype and the dataset is not redistributed",
    ),
)

PHYSIONET_SELECTION = ("q-pain",)

SKIP_KIND_MEANING = {
    "already_present": (
        "The archive was already on disk from an earlier run and was left untouched. Raw "
        "data is never silently replaced; `--force` is required to re-fetch."
    ),
    "access_or_licence_refused": (
        "The publisher's terms do not permit this pipeline to fetch it: either the resource "
        "is not open access, or its licence was flagged for review and no reviewer reason was "
        "recorded."
    ),
    "not_discovered": (
        "The resource was not in the discovery report, so its access terms had not been read "
        "yet. Discovery must run before a download is attempted."
    ),
    "unsafe_archive": "The archive contained a member path that would have escaped its directory.",
    "fetch_failed": "The request to the publisher did not return a usable archive.",
}


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2))


def run_step(name: str, arguments: list[str], *, network: bool) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.run(
        [sys.executable, "-m", "dataset.pipeline", *arguments],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=False,
    )
    return {
        "step": name,
        "command": " ".join(["python", "-m", "dataset.pipeline", *arguments]),
        "needs_network": network,
        "exit_code": process.returncode,
        "seconds": round(time.monotonic() - started, 2),
        "stdout_tail": process.stdout.strip().splitlines()[-25:],
        "stderr_tail": process.stderr.strip().splitlines()[-15:],
    }


def access_markdown(steps: list[dict[str, Any]]) -> str:
    entries = registry.load_registry()
    log = registry.load_download_log()

    obtained: dict[str, dict[str, Any]] = {}
    attempts: dict[str, dict[str, Any]] = {}
    for record in log:
        identifier = record["dataset_id"]
        attempts[identifier] = record
        if record.get("status") == "downloaded":
            obtained[identifier] = record
    downloaded = sorted(obtained)
    refused = [
        record for identifier, record in sorted(attempts.items())
        if identifier not in obtained and record.get("status") == "skipped"
    ]

    by_status: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        by_status.setdefault(item["access_status"], []).append(item)

    lines = [
        "# Dataset access report",
        "",
        f"Generated {registry.now()} by `dataset.pipeline run`.",
        "",
        "What each source's publisher permits, what this pipeline therefore did, and what a "
        "person would have to do to obtain the rest. An access status here is read from the "
        "publisher's own page at the time of the run, not assumed.",
        "",
        "## Status of every registered source",
        "",
        "| source | access | licence | records | subjects | obtained |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for status in sorted(by_status):
        for item in sorted(by_status[status], key=lambda row: row["dataset_id"]):
            held_locally = "yes" if item.get("local_path") else "no"
            lines.append(
                f"| `{item['dataset_id']}` | {item['access_status']} | "
                f"{item['license'] or 'unknown'} | "
                f"{item['records'] if item['records'] is not None else '—'} | "
                f"{item['subjects'] if item['subjects'] is not None else '—'} | "
                f"{held_locally} |"
            )
    lines.append("")

    lines += [
        "A record or subject count in that table is only a measurement where the source was "
        "obtained. For a source that was not obtained it is the publisher's stated figure, and "
        "the registry entry's note says so.",
        "",
        "An obtained source shows no record count when its directory holds no machine-readable "
        "table, or holds several tables that are separate entities rather than parts of one "
        "set — adding those together would not give a record count. The per-table measurement "
        "is in `metadata/profiles/<dataset_id>.json`.",
        "",
        "## What was obtained",
        "",
    ]
    if downloaded:
        for identifier in downloaded:
            record = obtained[identifier]
            lines += [
                f"### `{record['dataset_id']}`",
                "",
                f"- Source: {record.get('source')} — {record.get('source_url')}",
                f"- Licence: {record.get('license')}",
                f"- Downloaded: {record.get('downloaded_at')}",
                f"- Archive: {record.get('archive_bytes', 0):,} bytes, "
                f"sha256 `{record.get('archive_sha256')}`",
                f"- Files extracted: {record.get('file_count')}",
                "",
            ]
            if record.get("license_review_reason"):
                lines += [f"- Licence review: {record['license_review_reason']}", ""]
    else:
        lines += ["Nothing was downloaded in this run.", ""]

    lines += ["## What was not downloaded, and why", ""]
    if refused:
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for record in refused:
            by_kind.setdefault(record.get("skip_kind") or "unspecified", []).append(record)
        for kind, records in sorted(by_kind.items()):
            lines += [f"### {kind.replace('_', ' ')}", "", SKIP_KIND_MEANING.get(kind, ""), ""]
            lines += [f"- `{record['dataset_id']}`: {record.get('reason')}" for record in records]
            lines.append("")
    else:
        lines += ["Every selected download succeeded, and none was refused.", ""]

    lines += [
        "## What a person would have to do to obtain the rest",
        "",
        "Each restricted or credentialed source has its procedure recorded in its own access "
        "report under `dataset/metadata`:",
        "",
        "- `biovid_access_report.json` — the agreement form, who authorises it, and the parts "
        "the publisher documents",
        "- `tame_pain_access_report.json` — the PhysioNet data use agreement for that project",
        "- `physionet_access_report.json` — the procedure for each access status PhysioNet uses",
        "",
        "None of those procedures can be completed by a pipeline. Each requires a named person "
        "to agree to terms, and in PhysioNet's credentialed case to hold a human-subjects "
        "training certificate.",
        "",
        "## Steps in this run",
        "",
        "| step | network | exit | seconds |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{step['step']}` | {'yes' if step['needs_network'] else 'no'} | "
        f"{step['exit_code']} | {step['seconds']} |"
        for step in steps
    ]
    lines.append("")
    return "\n".join(lines)


def run_pipeline(*, offline: bool, data_source: str, seed: int) -> int:
    plan: list[tuple[str, list[str], bool]] = [
        ("discover_kaggle", ["discover-kaggle"], True),
        ("discover_physionet", ["discover-physionet"], True),
        ("biovid_access", ["biovid-access"], True),
        ("tame_pain_access", ["tame-pain-access"], True),
    ]
    for reference, review in KAGGLE_SELECTION:
        arguments = ["download-kaggle", "--dataset", reference]
        if review:
            arguments += ["--accept-reviewed-license", review]
        plan.append((f"download_kaggle:{reference}", arguments, True))
    for slug in PHYSIONET_SELECTION:
        plan.append((f"download_physionet:{slug}", ["download-physionet", "--slug", slug], True))
    plan += [
        ("inspect", ["inspect"], False),
        ("normalize", ["normalize"], False),
        ("merge", ["merge", "--data-source", data_source, "--seed", str(seed)], False),
        ("validate", ["validate"], False),
        ("statistics", ["statistics"], False),
    ]

    steps: list[dict[str, Any]] = []
    for name, arguments, network in plan:
        if network and offline:
            steps.append({
                "step": name,
                "command": " ".join(["python", "-m", "dataset.pipeline", *arguments]),
                "needs_network": True,
                "exit_code": None,
                "seconds": 0.0,
                "skipped": "offline",
                "stdout_tail": [],
                "stderr_tail": [],
            })
            continue
        steps.append(run_step(name, arguments, network=network))

    registry.upsert(registry.entries_from_download_log())

    ensure(REPORTS_DIR)
    ACCESS_MARKDOWN.write_text(access_markdown(steps), encoding="utf-8")
    run_report = {
        "started_at": registry.now(),
        "offline": offline,
        "data_source_filter": data_source,
        "seed": seed,
        "steps": steps,
        "failed_steps": [s["step"] for s in steps if s.get("exit_code") not in (0, None)],
        "access_report": str(ACCESS_MARKDOWN),
    }
    ensure(PIPELINE_RUN_REPORT.parent)
    PIPELINE_RUN_REPORT.write_text(json.dumps(run_report, indent=2) + "\n", encoding="utf-8")

    emit({
        "access_report": str(ACCESS_MARKDOWN),
        "run_report": str(PIPELINE_RUN_REPORT),
        "steps": [
            {
                "step": step["step"],
                "exit_code": step["exit_code"],
                "seconds": step["seconds"],
                **({"skipped": step["skipped"]} if step.get("skipped") else {}),
            }
            for step in steps
        ],
        "failed_steps": run_report["failed_steps"],
    })
    return 1 if run_report["failed_steps"] else 0


def _download_kaggle(args: argparse.Namespace) -> int:
    if not args.dataset:
        print("No dataset selected; nothing was downloaded. Pass --dataset owner/dataset-name.")
        return 0
    try:
        result = acquire.download_kaggle(
            args.dataset, force=args.force, licence_override=args.accept_reviewed_license
        )
    except (FetchError, PermissionError, FileExistsError, ValueError, zipfile.BadZipFile) as exc:
        result = {
            "dataset_id": args.dataset,
            "status": "skipped",
            "source": "kaggle",
            "skip_kind": acquire.skip_kind(exc),
            "reason": str(exc),
        }

    registry.log_download(result)
    if result["status"] == "downloaded":
        acquire.record_kaggle_download(args.dataset, result)

    emit({k: v for k, v in result.items() if k != "files"})
    for item in result.get("files", [])[:20]:
        print(f"  {item['bytes']:>12,}  {item['sha256'][:16]}…  {item['path']}")
    return 0


def _download_physionet(args: argparse.Namespace) -> int:
    if not args.slug:
        print("No resource selected; nothing was downloaded. Pass --slug <project-slug>.")
        return 0
    try:
        result = acquire.download_physionet(args.slug, force=args.force)
    except (FetchError, PermissionError, FileExistsError, LookupError, ValueError) as exc:
        result = {
            "dataset_id": args.slug,
            "status": "skipped",
            "source": "physionet",
            "skip_kind": acquire.skip_kind(exc),
            "reason": str(exc),
        }

    registry.log_download(result)
    if result["status"] == "downloaded":
        acquire.record_physionet_download(args.slug, result)

    emit({k: v for k, v in result.items() if k != "files"})
    for item in result.get("files", [])[:20]:
        print(f"  {item['bytes']:>12,}  {item['sha256'][:16]}  {item['path']}")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    if args.path:
        emit(profile.inspect_one(args.path, args.dataset_id, args.out_dir))
    else:
        emit(profile.inspect_all(args.out_dir))
    return 0


def _validate(args: argparse.Namespace) -> int:
    if not args.unified.exists():
        emit({
            "status": "no_input",
            "reason": f"{args.unified} does not exist; run the merge step first",
        })
        return 1
    summary, failed = report.validate(args.unified)
    emit(summary)
    return 2 if failed else 0


def _statistics(args: argparse.Namespace) -> int:
    if not args.unified.exists():
        emit({
            "status": "no_input",
            "reason": f"{args.unified} does not exist; run the merge step first",
        })
        return 1
    emit(statistics.generate(args.unified))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dataset.pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    kaggle = commands.add_parser("discover-kaggle")
    kaggle.add_argument("--page-size", type=int, default=20)
    kaggle.add_argument("--query", action="append")

    physionet = commands.add_parser("discover-physionet")
    physionet.add_argument("--topic", action="append")
    physionet.add_argument("--skip-index", action="store_true")

    commands.add_parser("biovid-access")
    commands.add_parser("tame-pain-access")

    kaggle_download = commands.add_parser("download-kaggle")
    kaggle_download.add_argument("--dataset")
    kaggle_download.add_argument("--force", action="store_true")
    kaggle_download.add_argument("--accept-reviewed-license", metavar="REASON")

    physionet_download = commands.add_parser("download-physionet")
    physionet_download.add_argument("--slug")
    physionet_download.add_argument("--force", action="store_true")

    inspect = commands.add_parser("inspect")
    inspect.add_argument("path", nargs="?", type=Path)
    inspect.add_argument("--dataset-id")
    inspect.add_argument("--out-dir", type=Path, default=PROFILE_DIR)

    normalize = commands.add_parser("normalize")
    normalize.add_argument("--dataset-id", action="append")
    normalize.add_argument("--out-root", type=Path, default=SOURCES_DIR)

    merge_command = commands.add_parser("merge")
    merge_command.add_argument(
        "--data-source", choices=merge.DATA_SOURCE_CHOICES, default="all"
    )
    merge_command.add_argument("--seed", type=int, default=DEFAULT_SEED)
    merge_command.add_argument("--sources-root", type=Path, default=SOURCES_DIR)

    validate = commands.add_parser("validate")
    validate.add_argument("--unified", type=Path, default=UNIFIED_FILE)

    stats = commands.add_parser("statistics")
    stats.add_argument("--unified", type=Path, default=UNIFIED_FILE)

    whole = commands.add_parser("run")
    whole.add_argument("--offline", action="store_true")
    whole.add_argument("--data-source", choices=merge.DATA_SOURCE_CHOICES, default="all")
    whole.add_argument("--seed", type=int, default=DEFAULT_SEED)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "discover-kaggle":
        queries = tuple(args.query) if args.query else discover.KAGGLE_QUERIES
        emit(discover.discover_kaggle(queries, args.page_size))
        return 0
    if args.command == "discover-physionet":
        topics = tuple(args.topic) if args.topic else discover.PHYSIONET_TOPICS
        emit(discover.discover_physionet(topics, args.skip_index))
        return 0
    if args.command == "biovid-access":
        emit(acquire.check_biovid_access())
        return 0
    if args.command == "tame-pain-access":
        emit(acquire.check_tame_pain_access())
        return 0
    if args.command == "download-kaggle":
        return _download_kaggle(args)
    if args.command == "download-physionet":
        return _download_physionet(args)
    if args.command == "inspect":
        return _inspect(args)
    if args.command == "normalize":
        emit(merge.normalize(args.dataset_id, args.out_root))
        return 0
    if args.command == "merge":
        emit(merge.merge(
            data_source=args.data_source, seed=args.seed, sources_root=args.sources_root
        ))
        return 0
    if args.command == "validate":
        return _validate(args)
    if args.command == "statistics":
        return _statistics(args)
    return run_pipeline(
        offline=args.offline, data_source=args.data_source, seed=args.seed
    )
