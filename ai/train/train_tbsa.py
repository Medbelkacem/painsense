#!/usr/bin/env python3
"""Fit the burned-surface research model and record it in the model registry.

A thin entry point over `app.cli train-burn-tbsa`, which is where the behaviour lives.
The model estimates the burned share of the body surface from 2D body-mask projections and
is trained on the synthetic MassHumanBurns dataset. It is recorded inactive and is not used
for any clinical estimate; see `docs/burn-model.md` for what it is and is not.

The dataset's imagery archives are around a gigabyte, well over the per-dataset size cap an
unattended worker uses, so they are fetched and extracted by hand and this script is
pointed at the result:

    curl -L -C - -O https://huggingface.co/datasets/HLSS/MassHumanBurns/resolve/main/burn_masks.7z
    curl -L -C - -O https://huggingface.co/datasets/HLSS/MassHumanBurns/resolve/main/labels.npy
    7z x burn_masks.7z
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    # Delegating to the CLI rather than re-importing the trainer keeps one definition of
    # the arguments, the registry write and the "Model not trained" exit code.
    sys.argv = ["app.cli", "train-burn-tbsa", *sys.argv[1:]]
    runpy.run_module("app.cli", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
