"""What an acquisition adapter has to provide, and how samples are timed.

Two things in here are worth reading before writing an adapter.

**The device's sample index is authoritative, the host clock is not.** Every amplifier
numbers its samples, and that counter is the only reliable record of how many samples were
produced and which were lost. Host arrival time tells you when a *block* reached the
process, which includes USB latency, scheduler jitter and whatever the OS did in between —
useless for spacing samples a few milliseconds apart. So per-sample timestamps are derived
from the index and the nominal rate, anchored once to the host clock at the first block, and
`Block.host_time` keeps the arrival time separately for anyone who wants it.

**A gap in the index is a dropped sample, not a shorter recording.** An adapter reports
`dropped` so the quality report can say samples went missing rather than silently
concatenating across the hole. Fabricating values to fill a gap would be inventing sensor
readings, so nothing does that; the gap is recorded and the stored file carries NaN.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Self

import numpy as np


class DeviceUnavailable(RuntimeError):
    """The device could not be found, opened, or has gone away."""


class InvalidPacket(ValueError):
    """A frame did not match the protocol.

    Carried rather than raised out of `read`: a corrupt frame on a serial line is routine,
    and the correct response is to count it, resynchronise and keep going. A recording that
    aborted on the first bad byte would be useless on real hardware.
    """


@dataclass(frozen=True)
class DeviceInfo:
    adapter: str
    #: What `open` is called with — a serial port path, a BLE address.
    identifier: str
    label: str
    #: Channels the device itself offers, in the order it sends them.
    native_channels: tuple[str, ...]
    sample_rate_hz: float
    unit: str
    #: True where the adapter confirmed the device answered, rather than inferring it from
    #: a USB descriptor. A port that looks like a Cyton is not a Cyton until it replies.
    confirmed: bool = False
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "adapter": self.adapter,
            "identifier": self.identifier,
            "label": self.label,
            "native_channels": list(self.native_channels),
            "sample_rate_hz": self.sample_rate_hz,
            "unit": self.unit,
            "confirmed": self.confirmed,
            "detail": self.detail,
        }


@dataclass
class Block:
    """One run of consecutive samples as they arrived."""

    #: Platform channel code to values, already scaled into the channel's unit.
    samples: dict[str, np.ndarray]
    #: The device's own sample index for each sample.
    indices: np.ndarray
    #: When the block reached this process, as a host epoch time.
    host_time: float
    #: Samples the device's index says were produced but never arrived.
    dropped: int = 0
    #: Frames that did not match the protocol and were resynchronised past.
    invalid_packets: int = 0

    @property
    def length(self) -> int:
        return len(self.indices)

    def timestamps(
        self, *, rate: float, anchor_index: int, anchor_time: float
    ) -> np.ndarray:
        """Per-sample times as integer nanoseconds since the epoch.

        Derived from the index and the nominal rate rather than measured, for the reason in
        the module docstring. The anchor is set once per recording so the whole session
        shares one time base.

        Nanoseconds as int64, not float seconds. An epoch time is about 1.7e9, where float64
        resolves roughly 240 nanoseconds — so adding a 0.5 millisecond sample interval to it
        loses part of the interval, and the spacing of a 2 kHz EMG recording comes back
        visibly uneven. int64 nanoseconds is exact over three centuries, which is the same
        reason `datetime64[ns]` is defined that way.
        """
        anchor_ns = round(anchor_time * 1e9)
        if rate <= 0:
            return np.full(self.length, anchor_ns, dtype=np.int64)
        offsets = np.rint((self.indices - anchor_index) * (1e9 / rate)).astype(np.int64)
        return anchor_ns + offsets


class Session(ABC):
    """An open acquisition session on one device."""

    #: Counters a caller can read at any time; the API surfaces them during recording.
    def __init__(self) -> None:
        self.invalid_packets = 0
        self.dropped_samples = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self._opened_at = time.time()

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @property
    @abstractmethod
    def info(self) -> DeviceInfo: ...

    @abstractmethod
    def read(self, *, timeout: float = 1.0) -> Block | None:
        """The samples available now, or None if none arrived within `timeout`.

        Must not raise for a corrupt frame. Raises `DeviceUnavailable` only when the device
        is gone and reconnection has failed.
        """

    @abstractmethod
    def close(self) -> None: ...

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "invalid_packets": self.invalid_packets,
            "dropped_samples": self.dropped_samples,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "open_seconds": round(time.time() - self._opened_at, 1),
        }

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class Adapter(ABC):
    code: str
    label: str
    #: What this adapter speaks, stated plainly so a reader does not assume more.
    protocol: str
    transport: str

    @abstractmethod
    def discover(self) -> list[DeviceInfo]:
        """Devices this adapter can see now. Never raises for a missing transport."""

    @abstractmethod
    def open(
        self,
        identifier: str,
        *,
        mapping: dict[str, str] | None = None,
        **options,
    ) -> Session:
        """Open a session.

        `mapping` maps the device's native channel names onto this platform's channel codes.
        Without it an adapter uses its own default, and a channel the mapping does not name
        is not recorded — a device with eight inputs and two electrodes attached should
        record two channels, not eight of which six are noise.
        """

    def describe(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "protocol": self.protocol,
            "transport": self.transport,
        }


def track_gaps(indices: np.ndarray, previous: int | None, *, modulus: int | None = None) -> int:
    """Samples missing between `previous` and the first index of this block.

    `modulus` is for a device whose counter wraps — the Cyton's is a single byte — where a
    drop and a wrap look alike and the smaller interpretation is the right one to take.
    """
    if previous is None or len(indices) == 0:
        return 0
    step = int(indices[0]) - previous
    if modulus:
        step %= modulus
    return max(0, step - 1)
