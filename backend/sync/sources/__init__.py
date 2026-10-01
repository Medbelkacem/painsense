"""The publishers this platform synchronises with.

A connector is looked up by the `code` on its `external_sources` row. Removing a connector
from this tuple stops it being polled without deleting the datasets it found, which is why
`get` raises rather than returning a stand-in: a run against a source with no adapter is a
configuration error worth seeing, not something to paper over.
"""

from __future__ import annotations

from backend.sync.sources.base import Acquired, Connector, RemoteDataset, Unavailable
from backend.sync.sources.cdc import CDC_SOCRATA
from backend.sync.sources.github import GITHUB
from backend.sync.sources.huggingface import HUGGING_FACE
from backend.sync.sources.kaggle import KAGGLE
from backend.sync.sources.physionet import PHYSIONET
from backend.sync.sources.who import WHO_GHO

CONNECTORS: tuple[Connector, ...] = (
    WHO_GHO,
    CDC_SOCRATA,
    KAGGLE,
    PHYSIONET,
    HUGGING_FACE,
    GITHUB,
)

BY_CODE = {connector.code: connector for connector in CONNECTORS}


def get(code: str) -> Connector:
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(f"no connector for source {code!r}") from None


__all__ = [
    "BY_CODE",
    "CDC_SOCRATA",
    "CONNECTORS",
    "GITHUB",
    "HUGGING_FACE",
    "KAGGLE",
    "PHYSIONET",
    "WHO_GHO",
    "Acquired",
    "Connector",
    "RemoteDataset",
    "Unavailable",
    "get",
]
