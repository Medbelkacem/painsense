"""Model artifacts and the active version.

A trained model is three estimators saved together: the point estimate and the two
conditional quantiles that form the interval. They are stored as one artifact because a
point estimate whose interval came from a different fit would be misleading.

The registry row in the database is the authority on which version is active. The artifact
on disk is the payload. If the row points at an artifact that is not there, loading fails
loudly rather than falling back to an older model the clinician was not told about.
"""

from dataclasses import dataclass
from pathlib import Path

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import ModelVersion

ARTIFACT_SUFFIX = ".joblib"


class ModelUnavailable(Exception):
    """No model is active, or its artifact is missing."""


@dataclass
class Bundle:
    version: str
    algorithm: str
    point: object
    lower: object
    upper: object
    feature_names: tuple[str, ...]
    observed_coverage: float
    residual_sd: float
    dataset_version: str


def artifact_path(version: str) -> Path:
    return get_settings().model_store_path / f"{version}{ARTIFACT_SUFFIX}"


def save(bundle: Bundle) -> Path:
    path = artifact_path(bundle.version)
    joblib.dump(bundle, path)
    return path


_cache: dict[str, Bundle] = {}


def load(version: str) -> Bundle:
    if version in _cache:
        return _cache[version]
    path = artifact_path(version)
    if not path.exists():
        raise ModelUnavailable(f"artifact for model {version} is missing from {path.parent}")
    bundle = joblib.load(path)
    _cache[version] = bundle
    return bundle


def forget(version: str | None = None) -> None:
    if version is None:
        _cache.clear()
    else:
        _cache.pop(version, None)


def active_row(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))


def active(db: Session) -> tuple[Bundle, ModelVersion]:
    row = active_row(db)
    if row is None:
        raise ModelUnavailable("no model has been trained yet")
    return load(row.version), row


def activate(db: Session, version: str) -> ModelVersion:
    rows = db.scalars(select(ModelVersion)).all()
    target = next((row for row in rows if row.version == version), None)
    if target is None:
        raise ModelUnavailable(f"model {version} is not registered")
    for row in rows:
        row.is_active = row.version == version
    db.commit()
    return target
