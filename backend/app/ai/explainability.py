"""Per-prediction feature contributions.

SHAP values on the point estimator, reported as contributions to this estimate rather than
as causes of the pain. A contribution says the model moved its output by that much when it
read that value; it does not say the value produced the pain, and the wording in the report
keeps that distinction.

The magnitude band is relative to the largest contribution in the same prediction, so it
answers "which fields drove this estimate" rather than comparing across patients.
"""

from dataclasses import dataclass

import numpy as np
import shap

from app.ai import features
from app.ai.model import Bundle

HIGH_SHARE = 0.6
MODERATE_SHARE = 0.3
DEFAULT_TOP_N = 8

_explainers: dict[str, object] = {}


@dataclass
class Contribution:
    feature: str
    label: str
    value: float
    magnitude: str
    direction: str


def _explainer(bundle: Bundle):
    if bundle.version not in _explainers:
        _explainers[bundle.version] = shap.TreeExplainer(bundle.point)
    return _explainers[bundle.version]


def forget(version: str | None = None) -> None:
    if version is None:
        _explainers.clear()
    else:
        _explainers.pop(version, None)


def contributions(
    bundle: Bundle, x: np.ndarray, top_n: int = DEFAULT_TOP_N
) -> list[Contribution]:
    values = np.asarray(_explainer(bundle).shap_values(x.reshape(1, -1))).reshape(-1)
    largest = float(np.max(np.abs(values))) or 1.0

    ordered = sorted(
        zip(bundle.feature_names, values), key=lambda pair: abs(pair[1]), reverse=True
    )
    out = []
    for name, value in ordered[:top_n]:
        share = abs(value) / largest
        if share >= HIGH_SHARE:
            magnitude = "HIGH"
        elif share >= MODERATE_SHARE:
            magnitude = "MODERATE"
        else:
            magnitude = "LOW"
        out.append(
            Contribution(
                feature=name,
                label=features.LABELS.get(name, name),
                value=round(float(value), 3),
                magnitude=magnitude,
                direction="RAISES" if value > 0 else "LOWERS",
            )
        )
    return out
