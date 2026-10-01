"""A BLE front end, carrying the same line-delimited JSON as the serial gateway.

Same protocol, different transport. A battery-powered front end with no USB tether is the
safer arrangement for anything attached to a person — there is no cable to a mains-powered
host — so it is worth supporting even though it is the more awkward of the two.

BLE needs `bleak`, which is not a declared dependency because it pulls in a D-Bus stack on
Linux and most deployments use a USB amplifier. It is imported where it is used, and its
absence is reported as "BLE support is not installed" rather than crashing discovery. The
rest of the acquisition path is unaffected.

Two BLE realities shape this adapter:

**Notifications arrive on bleak's event loop, not on the caller's thread.** The platform's
acquisition runner is a thread, so the loop runs in its own thread and notifications land in
a queue the reader drains. Trying to await from the runner would mean an event loop per
recording.

**An MTU is about 20 to 244 bytes.** A JSON line is routinely longer than one notification,
so fragments are reassembled on newline exactly as the serial adapter does, and a
notification boundary mid-number is normal rather than a corrupt packet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time

import numpy as np

from backend.signals.devices.base import (
    Adapter,
    Block,
    DeviceInfo,
    DeviceUnavailable,
    Session,
    track_gaps,
)

logger = logging.getLogger("painsense.signals.devices.ble")

#: Nordic UART Service, which is what almost every ESP32 and nRF front end exposes. A device
#: using its own service passes its UUIDs to `open`.
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#: The characteristic the peripheral notifies on. "TX" is from the peripheral's point of view.
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

DEFAULT_RATE_HZ = 250.0
DISCOVERY_SECONDS = 5.0
MAX_LINE_BYTES = 16_384
#: Notifications are buffered here between the loop thread and the reader. Bounded so a
#: reader that stalls drops new data rather than growing without limit; the drop is counted.
QUEUE_LIMIT = 4096


class BleUnavailable(DeviceUnavailable):
    """BLE support is not installed, or no adapter is present."""


def _bleak():
    try:
        import bleak
    except ImportError as exc:
        raise BleUnavailable(
            "BLE support is not installed. Install `bleak` to acquire over BLE; USB serial "
            "acquisition does not need it."
        ) from exc
    return bleak


class _Loop:
    """An asyncio loop on its own thread, for bleak to live in."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ble-loop")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coroutine, *, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2.0)


class BleGatewaySession(Session):
    def __init__(
        self,
        address: str,
        *,
        mapping: dict[str, str] | None,
        rate: float,
        characteristic: str,
        connect_timeout: float,
    ) -> None:
        super().__init__()
        self._address = address
        self._mapping = mapping or {}
        self._rate = rate
        self._characteristic = characteristic
        self._connect_timeout = connect_timeout
        self._buffer = bytearray()
        self._previous_index: int | None = None
        self._channels: tuple[str, ...] = ()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=QUEUE_LIMIT)
        self._overflowed = 0
        self._loop = _Loop()
        self._client = None
        self._open()

    def _open(self) -> None:
        bleak = _bleak()

        def _on_notify(_sender, data: bytearray) -> None:
            try:
                self._queue.put_nowait(bytes(data))
            except queue.Full:
                # Dropping the newest keeps the queue a window on recent data rather than a
                # growing backlog. Counted, so the quality report can say samples were lost.
                self._overflowed += 1

        client = bleak.BleakClient(self._address)
        try:
            self._loop.call(client.connect(), timeout=self._connect_timeout)
            self._loop.call(
                client.start_notify(self._characteristic, _on_notify),
                timeout=self._connect_timeout,
            )
        except BleUnavailable:
            raise
        except Exception as exc:  # bleak raises its own hierarchy plus asyncio timeouts
            raise DeviceUnavailable(f"{self._address} could not be connected: {exc}") from exc
        self._client = client

    @property
    def connected(self) -> bool:
        return self._client is not None and bool(getattr(self._client, "is_connected", False))

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            adapter=BleGatewayAdapter.code,
            identifier=self._address,
            label=f"BLE gateway {self._address}",
            native_channels=self._channels,
            sample_rate_hz=self._rate,
            unit="uV",
            confirmed=self.connected and bool(self._channels),
            detail={
                "characteristic": self._characteristic,
                "protocol": "newline-delimited JSON over Nordic UART",
                "notification_overflows": self._overflowed,
            },
        )

    def _lines(self) -> list[bytes]:
        out: list[bytes] = []
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                if len(self._buffer) > MAX_LINE_BYTES:
                    self.invalid_packets += 1
                    self._buffer.clear()
                return out
            line = bytes(self._buffer[:end])
            del self._buffer[: end + 1]
            if line.strip():
                out.append(line)

    def _parse(self, line: bytes) -> tuple[int, dict[str, float]] | None:
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.invalid_packets += 1
            return None
        if not isinstance(payload, dict):
            self.invalid_packets += 1
            return None
        index, channels = payload.get("i"), payload.get("ch")
        if not isinstance(index, int) or not isinstance(channels, dict) or not channels:
            self.invalid_packets += 1
            return None
        values: dict[str, float] = {}
        for name, value in channels.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                self.invalid_packets += 1
                return None
            values[self._mapping.get(name, name)] = float(value)
        return index, values

    def read(self, *, timeout: float = 1.0) -> Block | None:
        if self._client is None:
            raise DeviceUnavailable("the session is closed")
        if not self.connected:
            raise DeviceUnavailable(f"{self._address} disconnected")

        deadline = time.monotonic() + timeout
        parsed: list[tuple[int, dict[str, float]]] = []
        while time.monotonic() < deadline:
            try:
                self._buffer.extend(self._queue.get(timeout=0.05))
            except queue.Empty:
                if parsed:
                    break
                continue
            for line in self._lines():
                record = self._parse(line)
                if record is not None:
                    parsed.append(record)

        if not parsed:
            return None

        indices = np.array([index for index, _ in parsed], dtype=np.int64)
        dropped = track_gaps(indices, self._previous_index)
        self.dropped_samples += dropped + self._overflowed
        self._overflowed = 0
        self._previous_index = int(indices[-1])

        codes = sorted({code for _, values in parsed for code in values})
        self._channels = tuple(codes)
        samples = {
            code: np.array([values.get(code, np.nan) for _, values in parsed], dtype=float)
            for code in codes
        }
        return Block(
            samples=samples,
            indices=indices,
            host_time=time.time(),
            dropped=dropped,
            invalid_packets=self.invalid_packets,
        )

    def close(self) -> None:
        if self._client is not None:
            try:
                self._loop.call(self._client.disconnect(), timeout=5.0)
            except Exception:
                logger.debug("disconnecting %s raised", self._address, exc_info=True)
            self._client = None
        self._loop.stop()


class BleGatewayAdapter(Adapter):
    code = "ble_gateway"
    label = "BLE gateway (Nordic UART)"
    protocol = (
        "newline-delimited JSON defined by this platform, over a Nordic UART "
        "characteristic; see docs/eeg-emg.md"
    )
    transport = "Bluetooth Low Energy"

    def discover(self) -> list[DeviceInfo]:
        try:
            bleak = _bleak()
        except BleUnavailable:
            return []
        loop = _Loop()
        try:
            devices = loop.call(
                bleak.BleakScanner.discover(timeout=DISCOVERY_SECONDS),
                timeout=DISCOVERY_SECONDS + 5.0,
            )
        except Exception:
            logger.warning("BLE scan failed", exc_info=True)
            return []
        finally:
            loop.stop()

        return [
            DeviceInfo(
                adapter=self.code,
                identifier=device.address,
                label=device.name or f"BLE device {device.address}",
                native_channels=(),
                sample_rate_hz=DEFAULT_RATE_HZ,
                unit="uV",
                # A scan result says a radio is nearby, nothing more. Whether it speaks this
                # protocol is only known once a notification is parsed.
                confirmed=False,
                detail={
                    "note": (
                        "advertised over BLE; whether it runs a gateway on the Nordic UART "
                        "service is only known once it is connected"
                    )
                },
            )
            for device in devices
        ]

    def open(
        self,
        identifier: str,
        *,
        mapping: dict[str, str] | None = None,
        rate: float = DEFAULT_RATE_HZ,
        characteristic: str = NUS_TX,
        connect_timeout: float = 15.0,
        **_options,
    ) -> BleGatewaySession:
        return BleGatewaySession(
            identifier,
            mapping=mapping,
            rate=rate,
            characteristic=characteristic,
            connect_timeout=connect_timeout,
        )
