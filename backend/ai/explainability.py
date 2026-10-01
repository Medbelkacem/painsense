from dataclasses import dataclass

import numpy as np
import shap
from sklearn.pipeline import Pipeline

from backend.ai import features
from backend.ai.model import Bundle

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


def tree_step(point):
    if isinstance(point, Pipeline):
        prefix = Pipeline(point.steps[:-1]) if len(point.steps) > 1 else None
        return point.steps[-1][1], (prefix.transform if prefix is not None else None)
    return point, None


class WidthMismatch(Exception):
    pass


def shap_values(point, x: np.ndarray, explainer=None) -> np.ndarray:
    tree, transform = tree_step(point)
    rows = transform(x) if transform is not None else x
    if rows.shape[1] != x.shape[1]:
        # A step that adds or removes a column would shift every value onto the wrong
        # feature name. Refuse rather than report an attribution that is quietly wrong.
        raise WidthMismatch(
            f"the pipeline turned {x.shape[1]} features into {rows.shape[1]} columns, so "
            "contributions cannot be attributed to feature names"
        )
    explainer = explainer or shap.TreeExplainer(tree)
    return np.asarray(explainer.shap_values(rows))


def mean_absolute_shap(point, x: np.ndarray) -> np.ndarray:
    return np.abs(shap_values(point, x)).mean(axis=0)


def _explainer(bundle: Bundle):
    if bundle.version not in _explainers:
        tree, _ = tree_step(bundle.point)
        _explainers[bundle.version] = shap.TreeExplainer(tree)
    return _explainers[bundle.version]


def forget(version: str | None = None) -> None:
    if version is None:
        _explainers.clear()
    else:
        _explainers.pop(version, None)


def contributions(
    bundle: Bundle, x: np.ndarray, top_n: int = DEFAULT_TOP_N
) -> list[Contribution]:
    values = shap_values(bundle.point, x.reshape(1, -1), _explainer(bundle)).reshape(-1)
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
