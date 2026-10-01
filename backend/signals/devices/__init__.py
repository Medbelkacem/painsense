"""Hardware acquisition adapters, one per protocol.

There is no universal EEG protocol and this package does not pretend otherwise. Each
adapter speaks exactly one documented interface and declares what it can and cannot do:

`openbci_cyton` implements the OpenBCI Cyton serial protocol — 33-byte binary frames, 24-bit
signed samples, the published scale factor. It is a real protocol with a published
specification and the parser follows it byte for byte.

`serial_gateway` speaks a line-delimited JSON protocol that *this platform defines* for an
ESP32 or Arduino front end. It is written down in `docs/eeg-emg.md` because nothing standard
exists at that layer; a sketch has to be written to match it.

`ble_gateway` carries the same JSON over a BLE characteristic, for a battery-powered front
end with no USB tether.

An amplifier not on this list is not supported, and the honest way to add one is another
adapter rather than widening one of these.
"""

from __future__ import annotations

import logging

from backend.signals.devices.base import (
    Adapter,
    Block,
    DeviceInfo,
    DeviceUnavailable,
    InvalidPacket,
    Session,
)
from backend.signals.devices.ble import BleGatewayAdapter
from backend.signals.devices.gateway import SerialGatewayAdapter
from backend.signals.devices.openbci import CytonAdapter

ADAPTERS: tuple[Adapter, ...] = (
    CytonAdapter(),
    SerialGatewayAdapter(),
    BleGatewayAdapter(),
)

logger = logging.getLogger("painsense.signals.devices")

BY_CODE = {adapter.code: adapter for adapter in ADAPTERS}


def get(code: str) -> Adapter:
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(
            f"no acquisition adapter {code!r}; this platform supports "
            + ", ".join(sorted(BY_CODE))
        ) from None


def discover() -> list[DeviceInfo]:
    """Every device every adapter can currently see.

    An adapter whose transport library is missing contributes nothing rather than raising,
    so a deployment without BLE support still discovers its serial amplifiers.
    """
    found: list[DeviceInfo] = []
    for adapter in ADAPTERS:
        try:
            found.extend(adapter.discover())
        except Exception:
            # One broken transport must not hide the others, but it should be visible in
            # the log: a serial library that fails to enumerate is a real problem.
            logger.warning("adapter %s could not enumerate devices", adapter.code, exc_info=True)
    return found


__all__ = [
    "ADAPTERS",
    "BY_CODE",
    "Adapter",
    "BleGatewayAdapter",
    "Block",
    "CytonAdapter",
    "DeviceInfo",
    "DeviceUnavailable",
    "InvalidPacket",
    "SerialGatewayAdapter",
    "Session",
    "discover",
    "get",
]
