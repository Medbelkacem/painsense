"""An ESP32 or Arduino front end, over a line-delimited JSON protocol.

There is no standard protocol at this layer, so this platform defines one. That is stated
plainly because the alternative — implying a universal EEG wire format exists — would send
someone looking for a specification that does not exist. A sketch has to be written to match
what is below, and `docs/eeg-emg.md` carries it in full with a worked example.

One JSON object per line, newline terminated:

    {"i": 1024, "ch": {"EEG_FPZ": 12.5, "EMG_TRAPEZIUS_L": -34.1}}

`i` is the device's own sample index, which must increase by one per sample so a gap is
detectable. `ch` maps channel names to values already in the channel's declared unit —
microvolts for EEG and EMG. An optional `t` carries the device's own millisecond clock, kept
in the block detail but not used for spacing, for the reason in `base.py`.

A line that is not valid JSON, or lacks `i` or `ch`, is counted as an invalid packet and
skipped. Scaling is the firmware's job: this adapter will not guess a gain, because a wrong
guess produces plausible numbers in the wrong units, which is worse than refusing.

**This protocol carries no safety guarantee.** An ESP32 is not an isolated biomedical
amplifier. It is a transport for a front end that already has instrumentation amplification
and isolation — see the safety section of the documentation.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("painsense.signals.devices.gateway")

DEFAULT_BAUD = 115_200
DEFAULT_RATE_HZ = 500.0

#: Handshake. A gateway that answers this is confirmed; one that does not is a candidate.
IDENTIFY = b"?\n"
IDENTIFY_TIMEOUT = 1.5

#: A single line longer than this is not a sample, it is a runaway. Capped so a device
#: emitting binary into a line protocol cannot grow the buffer without bound.
MAX_LINE_BYTES = 16_384

#: USB-serial bridges common on ESP32 and Arduino boards, for shortlisting ports only.
USB_HINTS = (
    (0x10C4, 0xEA60),  # Silicon Labs CP2102, most ESP32 devkits
    (0x1A86, 0x7523),  # WCH CH340
    (0x1A86, 0x55D4),  # WCH CH9102
    (0x0403, 0x6001),  # FTDI FT232
    (0x2341, None),    # Arduino
    (0x303A, None),    # Espressif native USB
)


def _hinted(vid: int | None, pid: int | None) -> bool:
    return any(
        vid == hint_vid and (hint_pid is None or pid == hint_pid)
        for hint_vid, hint_pid in USB_HINTS
    )


class GatewaySession(Session):
    def __init__(
        self,
        port: str,
        *,
        mapping: dict[str, str] | None,
        rate: float,
        baud: int,
        timeout: float,
        reconnect: bool,
    ) -> None:
        super().__init__()
        self._port_name = port
        self._mapping = mapping or {}
        self._rate = rate
        self._baud = baud
        self._timeout = timeout
        self._reconnect = reconnect
        self._buffer = bytearray()
        self._previous_index: int | None = None
        self._channels: tuple[str, ...] = ()
        self._serial = None
        self._open()

    def _open(self) -> None:
        import serial

        try:
            self._serial = serial.Serial(self._port_name, self._baud, timeout=self._timeout)
        except Exception as exc:  # pyserial raises several unrelated types here
            raise DeviceUnavailable(f"{self._port_name} could not be opened: {exc}") from exc
        time.sleep(0.3)
        self._serial.reset_input_buffer()

    def _reopen(self) -> bool:
        self.close()
        try:
            self._open()
        except DeviceUnavailable as exc:
            self.last_error = str(exc)
            return False
        self.reconnects += 1
        self._buffer.clear()
        self._previous_index = None
        return True

    @property
    def connected(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            adapter=SerialGatewayAdapter.code,
            identifier=self._port_name,
            label=f"Serial gateway on {self._port_name}",
            native_channels=self._channels,
            sample_rate_hz=self._rate,
            unit="uV",
            confirmed=self.connected and bool(self._channels),
            detail={"baud": self._baud, "protocol": "newline-delimited JSON"},
        )

    def _lines(self) -> list[bytes]:
        out: list[bytes] = []
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                if len(self._buffer) > MAX_LINE_BYTES:
                    # No newline in a very long run: the device is not speaking this
                    # protocol. Discard and count it rather than buffering for ever.
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
            code = self._mapping.get(name, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                self.invalid_packets += 1
                return None
            values[code] = float(value)
        return index, values

    def read(self, *, timeout: float = 1.0) -> Block | None:
        if self._serial is None:
            raise DeviceUnavailable("the session is closed")

        deadline = time.monotonic() + timeout
        parsed: list[tuple[int, dict[str, float]]] = []
        while time.monotonic() < deadline:
            try:
                chunk = self._serial.read(self._serial.in_waiting or 1)
            except Exception as exc:  # pyserial raises several unrelated types here
                self.last_error = str(exc)
                if not (self._reconnect and self._reopen()):
                    raise DeviceUnavailable(
                        f"{self._port_name} stopped responding: {exc}"
                    ) from exc
                continue
            if chunk:
                self._buffer.extend(chunk)
                for line in self._lines():
                    record = self._parse(line)
                    if record is not None:
                        parsed.append(record)
                if parsed:
                    break
            else:
                time.sleep(0.005)

        if not parsed:
            return None

        indices = np.array([index for index, _ in parsed], dtype=np.int64)
        dropped = track_gaps(indices, self._previous_index)
        self.dropped_samples += dropped
        self._previous_index = int(indices[-1])

        # A channel absent from one line and present in another would misalign the columns,
        # so the union is taken and a missing value becomes NaN — a recorded gap, not a zero.
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
        if self._serial is None:
            return
        try:
            if getattr(self._serial, "is_open", False):
                self._serial.close()
        except Exception:
            logger.debug("closing %s raised", self._port_name, exc_info=True)
        self._serial = None


class SerialGatewayAdapter(Adapter):
    code = "serial_gateway"
    label = "ESP32 / Arduino serial gateway"
    protocol = (
        "newline-delimited JSON defined by this platform; see docs/eeg-emg.md. Not a "
        "standard EEG protocol and not claimed to be one"
    )
    transport = "USB serial, 115200 baud by default"

    def discover(self) -> list[DeviceInfo]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        found = []
        for port in list_ports.comports():
            if not _hinted(port.vid, port.pid):
                continue
            found.append(
                DeviceInfo(
                    adapter=self.code,
                    identifier=port.device,
                    label=f"Serial gateway candidate on {port.device}",
                    native_channels=(),
                    sample_rate_hz=DEFAULT_RATE_HZ,
                    unit="uV",
                    confirmed=False,
                    detail={
                        "description": port.description,
                        "vid_pid": f"{port.vid:04x}:{port.pid:04x}" if port.vid else None,
                        "note": (
                            "a USB-serial bridge was recognised; whether a gateway sketch "
                            "is running on it is only known once it is opened"
                        ),
                    },
                )
            )
        return found

    def open(
        self,
        identifier: str,
        *,
        mapping: dict[str, str] | None = None,
        rate: float = DEFAULT_RATE_HZ,
        baud: int = DEFAULT_BAUD,
        timeout: float = 1.0,
        reconnect: bool = True,
        **_options,
    ) -> GatewaySession:
        return GatewaySession(
            identifier,
            mapping=mapping,
            rate=rate,
            baud=baud,
            timeout=timeout,
            reconnect=reconnect,
        )
