"""Where the infectious disease pipeline keeps its state.

`raw/` is written once per download and never rewritten: a preprocessing step that wants a
different shape writes into `processed/` instead. Everything else can be rebuilt from
`raw/` plus the code, which is what makes a pipeline run reproducible.
"""

from __future__ import annotations

from pathlib import Path

from config import get_settings


def root() -> Path:
    return get_settings().epidemic_data_path


def raw(source: str | None = None, dataset_id: str | None = None) -> Path:
    path = root() / "raw"
    if source:
        path = path / source
    if dataset_id:
        path = path / dataset_id
    return path


def processed(dataset_id: str | None = None) -> Path:
    path = root() / "processed"
    return path / dataset_id if dataset_id else path


def metadata(*parts: str) -> Path:
    return root().joinpath("metadata", *parts)


def reports(*parts: str) -> Path:
    return root().joinpath("reports", *parts)


def models(*parts: str) -> Path:
    return root().joinpath("models", *parts)


def surveillance_table() -> Path:
    return processed() / "surveillance.parquet"


def epidemiology_summary(disease: str) -> Path:
    return processed() / "epidemiology" / f"{disease}.json"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative(path: Path) -> str:
    """A registry entry records a path relative to the data root, so a registry written on
    one machine still reads correctly on another."""
    try:
        return str(path.resolve().relative_to(root().resolve()))
    except ValueError:
        return str(path)
