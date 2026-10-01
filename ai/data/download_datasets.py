#!/usr/bin/env python3
"""Catalogue the configured burn datasets and retrieve what their licences permit.

A thin entry point over `app.sync`, which is where the behaviour lives. Running it here
rather than through `python -m app.cli sync` buys one thing: the report is grouped by
dataset with the licence and the access route spelled out, which is what you want when
deciding whether a dataset is worth requesting.

Nothing here works around an access control. A dataset whose licence is not recognised, or
whose publisher requires an agreement, is catalogued with the steps a person would follow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from backend.sync import licensing  # noqa: E402
from backend.sync import sources as connectors  # noqa: E402

#: The sources the burn work cares about. Everything else a deployment has configured is
#: left alone; this is a focused report, not a full synchronisation.
BURN_SOURCES = {
    "huggingface": {
        "queries": [],
        "datasets": ["HLSS/MassHumanBurns", "shubhambaid/skin-burn-dataset"],
    },
    "github": {"repositories": ["VEDAs-Lab/EBIS", "xjtu-mia/BurnAnalysis"]},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="report licences and access status without retrieving anything",
    )
    parser.add_argument(
        "--source",
        choices=sorted(BURN_SOURCES),
        help="one source only; default is every burn source",
    )
    arguments = parser.parse_args()

    wanted = {arguments.source: BURN_SOURCES[arguments.source]} if arguments.source else BURN_SOURCES
    report: list[dict] = []
    for code, config in wanted.items():
        connector = connectors.get(code)
        try:
            found = connector.discover(config)
        except connectors.Unavailable as exc:
            report.append({"source": code, "error": str(exc)})
            continue
        for row in found:
            verdict = licensing.verdict(row.licence)
            refusal = licensing.refusal(row.access_status, verdict)
            report.append(
                {
                    "source": code,
                    "dataset": row.external_id,
                    "url": row.source_url,
                    "licence": row.licence,
                    "licence_verdict": verdict.value,
                    "access_status": row.access_status.value,
                    "retrievable": refusal is None,
                    "refused_because": refusal,
                    "access_procedure": licensing.procedure(row.access_status)
                    if refusal
                    else [],
                    "size_claimed_bytes": row.bytes_claimed,
                    "notes": row.notes,
                }
            )

    print(json.dumps(report, indent=2))
    retrievable = [entry for entry in report if entry.get("retrievable")]
    print(
        f"\n{len(retrievable)} of {len(report)} dataset(s) may be retrieved automatically.",
        file=sys.stderr,
    )
    if arguments.discover_only:
        return 0
    print(
        "To retrieve them into the platform, run a synchronisation, which records each "
        "copy with its digest and provenance:\n"
        "  cd backend && python -m app.cli sync --source huggingface",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
