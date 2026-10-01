"""Where a recording is written, and how it is written continuously.

The layout is one directory per session under one directory per participant:

    recordings/<participant>/<session>/
        eeg.csv               sample_index, timestamp_ns, one column per EEG channel
        emg.csv               the same, at the EMG rate
        other.csv             pulse, skin conductance and respiration, where present
        metadata.json         device, rates, channels, consent, provenance
        signal_quality.json   the quality report, written at stop

**Samples are appended as they arrive, not buffered until stop.** A `SessionWriter` holds an
open file handle per modality and flushes each block. A recording that is interrupted — the
process is killed, the device vanishes, the operator closes the laptop — therefore keeps
everything written up to that moment instead of losing the lot. The cost is a partial file
with no `signal_quality.json`, which is exactly how an interrupted session is recognised.

**One file per modality, because the rates differ.** EEG at 250 Hz and surface EMG at 1 kHz
cannot share a row without either resampling or padding, and doing either silently would
misrepresent the data. Each file carries its own sample index and its own timestamps.

CSV rather than a binary format. The volumes here are modest — ten minutes of 8-channel EEG
at 250 Hz is about 12 MB — and a clinician or a reviewer being able to open the file without
a library is worth more than the space. If rates or durations grow by an order of magnitude,
this is the module to change, and nothing above it needs to know.
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Self

import numpy as np

from config import get_settings
from backend.signals import schema

EEG_FILE = "eeg.csv"
EMG_FILE = "emg.csv"
OTHER_FILE = "other.csv"
METADATA_FILE = "metadata.json"
QUALITY_FILE = "signal_quality.json"

#: Which file each modality's channels are written to.
FILE_FOR_MODALITY = {
    schema.EEG: EEG_FILE,
    schema.EMG: EMG_FILE,
    schema.PPG: OTHER_FILE,
    schema.GSR: OTHER_FILE,
    schema.RESPIRATION: OTHER_FILE,
}

INDEX_COLUMN = "sample_index"
TIME_COLUMN = "timestamp_ns"


class StorageError(RuntimeError):
    """The recording could not be written."""


def root() -> Path:
    return get_settings().signal_store_path


def session_key(participant: str, session: str) -> str:
    return f"{participant}/{session}"


def resolve(key: str) -> Path:
    """Turn a stored key into a path, refusing anything that escapes the root."""
    base = root().resolve()
    path = (base / key).resolve()
    if path != base and base not in path.parents:
        raise StorageError(f"storage key {key!r} escapes the recording root")
    return path


def _group(channels: list[str]) -> dict[str, list[str]]:
    """Channels grouped by the file they belong in, in a stable column order."""
    grouped: dict[str, list[str]] = {}
    for code in channels:
        definition = schema.CHANNEL_BY_CODE.get(code)
        if definition is None:
            continue
        grouped.setdefault(FILE_FOR_MODALITY[definition.modality], []).append(code)
    return {name: sorted(codes) for name, codes in grouped.items()}


@dataclass
class _Target:
    path: Path
    columns: list[str]
    handle: object = None
    writer: object = None
    rows: int = 0


@dataclass
class SessionWriter:
    """An open set of files for one recording, appended to block by block."""

    key: str
    channels: list[str]
    channel_rates: dict[str, float]
    targets: dict[str, _Target] = field(default_factory=dict)
    #: Highest sample index seen per file, for the dropped-sample accounting.
    last_index: dict[str, int] = field(default_factory=dict)
    bytes_written: int = 0
    closed: bool = False

    def open(self) -> Self:
        directory = resolve(self.key)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"the session directory could not be created: {exc}") from exc

        for name, codes in _group(self.channels).items():
            path = directory / name
            try:
                handle = path.open("w", newline="", encoding="utf-8")
            except OSError as exc:
                self.close()
                raise StorageError(f"{name} could not be opened for writing: {exc}") from exc
            target = _Target(path=path, columns=codes, handle=handle)
            target.writer = csv.writer(handle)
            target.writer.writerow([INDEX_COLUMN, TIME_COLUMN, *codes])
            self.targets[name] = target
        if not self.targets:
            self.close()
            raise StorageError("no recognised channel to write")
        return self

    def append(
        self, samples: dict[str, np.ndarray], *, indices: np.ndarray, timestamps: np.ndarray
    ) -> int:
        """Write one block and flush it. Returns the rows written across all files."""
        if self.closed:
            raise StorageError("this writer is closed")

        written = 0
        for name, target in self.targets.items():
            present = [code for code in target.columns if code in samples]
            if not present:
                continue
            length = min(len(samples[code]) for code in present)
            length = min(length, len(indices), len(timestamps))
            if length == 0:
                continue
            rows = []
            for position in range(length):
                row = [int(indices[position]), int(timestamps[position])]
                for code in target.columns:
                    if code in samples and position < len(samples[code]):
                        value = samples[code][position]
                        # A gap travels as an empty cell. Writing 0 would make a dropped
                        # lead indistinguishable from a measured zero.
                        row.append("" if not np.isfinite(value) else f"{float(value):.6g}")
                    else:
                        row.append("")
                rows.append(row)
            try:
                target.writer.writerows(rows)
                target.handle.flush()
            except OSError as exc:
                raise StorageError(f"{name} could not be written: {exc}") from exc
            target.rows += len(rows)
            written += len(rows)
            self.last_index[name] = int(indices[length - 1])
        return written

    def rows_per_file(self) -> dict[str, int]:
        return {name: target.rows for name, target in self.targets.items()}

    def close(self) -> None:
        for target in self.targets.values():
            if target.handle is not None:
                try:
                    target.handle.close()
                    self.bytes_written += target.path.stat().st_size
                except OSError:
                    # A file that cannot be closed or stat'ed is already lost; the caller
                    # finds out from the row counts, which are what the metadata records.
                    pass
                target.handle = None
        self.closed = True

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()


def write_metadata(key: str, payload: dict) -> Path:
    path = resolve(key) / METADATA_FILE
    _write_json(path, {"written_at": datetime.now(timezone.utc).isoformat(), **payload})
    return path


def write_quality(key: str, payload: dict) -> Path:
    path = resolve(key) / QUALITY_FILE
    _write_json(path, payload)
    return path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"{path.name} could not be written: {exc}") from exc


def read_metadata(key: str) -> dict:
    path = resolve(key) / METADATA_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_samples(key: str) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Every channel in the session, with the sampling rate each was recorded at.

    Rates come from `metadata.json` rather than from the timestamps, because a recording
    with dropped samples has gaps in its timestamps and inferring a rate from them would
    give a figure slightly below the real one.
    """
    directory = resolve(key)
    metadata = read_metadata(key)
    declared = {
        code: float(rate) for code, rate in (metadata.get("channel_rates") or {}).items()
    }

    samples: dict[str, np.ndarray] = {}
    rates: dict[str, float] = {}
    for name in (EEG_FILE, EMG_FILE, OTHER_FILE):
        path = directory / name
        if not path.exists():
            continue
        columns, values = _read_csv(path)
        for position, code in enumerate(columns):
            samples[code] = values[position]
            rates[code] = declared.get(code, 0.0)
    return samples, rates


def _read_csv(path: Path) -> tuple[list[str], list[np.ndarray]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header or len(header) <= 2:
            return [], []
        codes = header[2:]
        collected: list[list[float]] = [[] for _ in codes]
        for row in reader:
            for position in range(len(codes)):
                cell = row[position + 2] if position + 2 < len(row) else ""
                collected[position].append(float(cell) if cell else np.nan)
    return codes, [np.asarray(column, dtype=float) for column in collected]


def file_manifest(key: str) -> list[dict]:
    """What is actually on disk for this session, measured rather than assumed."""
    directory = resolve(key)
    if not directory.exists():
        return []
    from backend.signals.integrity import sha256_of

    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
        }
        for path in sorted(directory.iterdir())
        if path.is_file()
    ]


def discard(key: str) -> None:
    path = resolve(key)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        parent = path.parent
        if parent != root() and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
