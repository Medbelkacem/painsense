import hashlib
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Self

import pyarrow as pa
import pyarrow.parquet as pq

PARQUET = "parquet"
JSONL = "jsonl"
FORMATS = (PARQUET, JSONL)

COMPRESSION = "zstd"


def _json_safe(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class ChunkedWriter:
    def __init__(self, path: Path, schema: pa.Schema, storage_format: str = PARQUET):
        if storage_format not in FORMATS:
            raise ValueError(f"unknown storage format {storage_format!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.schema = schema
        self.storage_format = storage_format
        self.rows_written = 0
        if storage_format == PARQUET:
            self._writer = pq.ParquetWriter(path, schema, compression=COMPRESSION)
            self._handle = None
        else:
            self._writer = None
            self._handle = path.open("w", encoding="utf-8")

    def write(self, rows: list[dict]) -> None:
        if not rows:
            return
        if self._writer is not None:
            columns = {name: [row.get(name) for row in rows] for name in self.schema.names}
            self._writer.write_table(pa.table(columns, schema=self.schema))
        else:
            for row in rows:
                line = {name: _json_safe(row.get(name)) for name in self.schema.names}
                self._handle.write(json.dumps(line, separators=(",", ":")) + "\n")
        self.rows_written += len(rows)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
        if self._handle is not None:
            self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def write_table(path: Path, rows: list[dict], schema: pa.Schema | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema is None:
        table = pa.Table.from_pylist(rows)
    else:
        columns = {name: [row.get(name) for row in rows] for name in schema.names}
        table = pa.table(columns, schema=schema)
    pq.write_table(table, path, compression=COMPRESSION)
    return path


def read_table(path: Path, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(path, columns=columns)


def iter_rows(
    path: Path, columns: list[str] | None = None, batch_size: int = 20000
) -> Iterator[dict]:
    handle = pq.ParquetFile(path)
    for batch in handle.iter_batches(batch_size=batch_size, columns=columns):
        yield from batch.to_pylist()


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def row_count(path: Path) -> int:
    if path.suffix == ".parquet":
        return pq.ParquetFile(path).metadata.num_rows
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
