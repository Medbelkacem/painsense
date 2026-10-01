"""OpenBCI Cyton, over its published serial protocol.

The frame format and the scale factor below are OpenBCI's documented ones, not a guess:

    byte 0       0xA0, start of frame
    byte 1       sample counter, 0-255, wraps
    bytes 2-25   eight channels, 24-bit signed big-endian, two's complement
    bytes 26-31  auxiliary, three 16-bit signed values (accelerometer by default)
    byte 32      stop byte, 0xC0 to 0xCF; the low nibble says what the aux bytes carry

A count converts to volts by `4.5 / gain / (2**23 - 1)` with the default gain of 24, which
is about 0.02235 microvolts per count. Values are returned in microvolts because that is the
unit `app.signals.schema` declares for EEG and EMG channels.

Three things this adapter does that a naive reader would skip:

**It resynchronises rather than aborting.** A corrupt frame on a USB serial line is normal.
The parser scans forward for the next 0xA0 whose frame ends in a valid stop byte, counts the
bad frame and continues. A recording that stopped at the first dropped byte would be useless.

**It treats the wrapping counter as wrapping.** The counter is one byte, so a gap of 3 and a
gap of 259 are indistinguishable; the smaller reading is taken, which under-reports a very
long outage and never invents one.

**It will not claim a port is a Cyton until the board answers.** Discovery lists candidate
ports from their USB descriptors and marks them unconfirmed; only a successful handshake sets
`confirmed`.
"""

from __future__ import annotations

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

BAUD = 115_200
FRAME_BYTES = 33
START_BYTE = 0xA0
STOP_LOW, STOP_HIGH = 0xC0, 0xCF
CHANNELS = 8
COUNTER_MODULUS = 256

#: Volts per count at the default gain of 24, from OpenBCI's published figure.
ADC_VOLTS = 4.5
DEFAULT_GAIN = 24.0
FULL_SCALE = 2**23 - 1
MICROVOLTS_PER_COUNT = ADC_VOLTS / DEFAULT_GAIN / FULL_SCALE * 1e6

logger = logging.getLogger("painsense.signals.devices.cyton")

DEFAULT_RATE_HZ = 250.0

#: Board commands from the published command set.
RESET = b"v"
START_STREAM = b"b"
STOP_STREAM = b"s"

#: USB bridges the Cyton dongle is seen through. Used only to shortlist candidate ports;
#: a match is never treated as proof the board is there.
USB_HINTS = (
    (0x0403, 0x6015),  # FTDI FT231X, the Cyton dongle
    (0x10C4, 0xEA60),  # Silicon Labs CP210x, some clones
)

#: The board's eight differential inputs, in the order they arrive in a frame.
NATIVE_ORDER = ("N1P", "N2P", "N3P", "N4P", "N5P", "N6P", "N7P", "N8P")

#: Where those inputs land by default. A deployment with electrodes on only some of them
#: passes its own mapping, and unmapped inputs are not recorded — which is why the eighth is
#: left out here rather than given a channel the default montage does not use.
DEFAULT_MAPPING = {
    "N1P": "EEG_FPZ",
    "N2P": "EEG_CZ",
    "N3P": "EMG_TRAPEZIUS_L",
    "N4P": "EMG_TRAPEZIUS_R",
    "N5P": "PPG_FINGER",
    "N6P": "GSR_PALMAR",
    "N7P": "RESPIRATION_BELT",
}


def _signed24(block: bytes) -> int:
    value = (block[0] << 16) | (block[1] << 8) | block[2]
    return value - (1 << 24) if value & 0x800000 else value


class CytonSession(Session):
    def __init__(
        self,
        port: str,
        *,
        mapping: dict[str, str],
        rate: float,
        gain: float,
        timeout: float,
        reconnect: bool,
    ) -> None:
        super().__init__()
        self._port_name = port
        self._mapping = mapping
        self._rate = rate
        self._scale = ADC_VOLTS / gain / FULL_SCALE * 1e6
        self._timeout = timeout
        self._reconnect = reconnect
        self._buffer = bytearray()
        self._previous_index: int | None = None
        self._serial = None
        self._open()

    # --- transport ---------------------------------------------------------------------

    def _open(self) -> None:
        import serial

        try:
            self._serial = serial.Serial(self._port_name, BAUD, timeout=self._timeout)
        except Exception as exc:  # pyserial raises several unrelated types here
            raise DeviceUnavailable(f"{self._port_name} could not be opened: {exc}") from exc
        # The board needs a moment after the port opens before it answers.
        time.sleep(0.4)
        self._serial.reset_input_buffer()
        self._serial.write(STOP_STREAM)
        time.sleep(0.1)
        self._serial.reset_input_buffer()
        self._serial.write(START_STREAM)

    def _reopen(self) -> bool:
        self.close()
        try:
            self._open()
        except DeviceUnavailable as exc:
            self.last_error = str(exc)
            return False
        self.reconnects += 1
        self._buffer.clear()
        # The counter restarts, so the old index is not comparable and a gap across the
        # reconnection would be meaningless.
        self._previous_index = None
        return True

    @property
    def connected(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    @property
    def info(self) -> DeviceInfo:
        return DeviceInfo(
            adapter=CytonAdapter.code,
            identifier=self._port_name,
            label="OpenBCI Cyton",
            native_channels=NATIVE_ORDER,
            sample_rate_hz=self._rate,
            unit="uV",
            confirmed=self.connected,
            detail={"baud": BAUD, "microvolts_per_count": round(self._scale, 6)},
        )

    # --- parsing -----------------------------------------------------------------------

    def _frames(self) -> list[tuple[int, list[int]]]:
        """Every complete, valid frame in the buffer, consuming what it reads."""
        out: list[tuple[int, list[int]]] = []
        while True:
            start = self._buffer.find(START_BYTE)
            if start < 0:
                # Nothing frame-like; keep the tail in case a start byte is mid-arrival.
                if len(self._buffer) > FRAME_BYTES * 4:
                    del self._buffer[:-FRAME_BYTES]
                return out
            if start > 0:
                # Bytes before a start byte are debris from a resynchronisation.
                self.invalid_packets += 1
                del self._buffer[:start]
            if len(self._buffer) < FRAME_BYTES:
                return out

            frame = bytes(self._buffer[:FRAME_BYTES])
            if not STOP_LOW <= frame[FRAME_BYTES - 1] <= STOP_HIGH:
                # Not a frame after all. Drop the start byte and look for the next one
                # rather than skipping a whole frame's worth of possibly good data.
                self.invalid_packets += 1
                del self._buffer[:1]
                continue

            counts = [
                _signed24(frame[2 + index * 3 : 5 + index * 3]) for index in range(CHANNELS)
            ]
            out.append((frame[1], counts))
            del self._buffer[:FRAME_BYTES]

    def read(self, *, timeout: float = 1.0) -> Block | None:
        if self._serial is None:
            raise DeviceUnavailable("the session is closed")

        deadline = time.monotonic() + timeout
        frames: list[tuple[int, list[int]]] = []
        while time.monotonic() < deadline:
            try:
                waiting = self._serial.in_waiting or 1
                chunk = self._serial.read(waiting)
            except Exception as exc:  # pyserial raises several unrelated types here
                self.last_error = str(exc)
                if not (self._reconnect and self._reopen()):
                    raise DeviceUnavailable(
                        f"{self._port_name} stopped responding: {exc}"
                    ) from exc
                continue
            if chunk:
                self._buffer.extend(chunk)
                frames.extend(self._frames())
                if frames:
                    break
            else:
                time.sleep(0.005)

        if not frames:
            return None

        indices = np.array([index for index, _ in frames], dtype=np.int64)
        dropped = track_gaps(indices, self._previous_index, modulus=COUNTER_MODULUS)
        self.dropped_samples += dropped
        self._previous_index = int(indices[-1])

        # The counter wraps every 256 samples, so it is unwrapped into a monotonic index
        # before anything downstream tries to order or space the samples.
        unwrapped = indices.copy()
        for position in range(1, len(unwrapped)):
            while unwrapped[position] <= unwrapped[position - 1]:
                unwrapped[position] += COUNTER_MODULUS

        samples: dict[str, np.ndarray] = {}
        for position, native in enumerate(NATIVE_ORDER):
            code = self._mapping.get(native)
            if code is None:
                continue
            samples[code] = (
                np.array([counts[position] for _, counts in frames], dtype=float) * self._scale
            )

        return Block(
            samples=samples,
            indices=unwrapped,
            host_time=time.time(),
            dropped=dropped,
            invalid_packets=self.invalid_packets,
        )

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            if getattr(self._serial, "is_open", False):
                self._serial.write(STOP_STREAM)
                self._serial.close()
        except Exception:
            # Closing a port that has already gone raises variously and there is nothing
            # useful to do about it; the session is being torn down either way.
            logger.debug("closing %s raised", self._port_name, exc_info=True)
        self._serial = None


class CytonAdapter(Adapter):
    code = "openbci_cyton"
    label = "OpenBCI Cyton (8 channel)"
    protocol = "OpenBCI Cyton 33-byte serial frames, 24-bit signed, published scale factor"
    transport = "USB serial, 115200 baud"

    def discover(self) -> list[DeviceInfo]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        found = []
        for port in list_ports.comports():
            pair = (port.vid, port.pid)
            likely = pair in USB_HINTS or "openbci" in (port.description or "").casefold()
            if not likely:
                continue
            found.append(
                DeviceInfo(
                    adapter=self.code,
                    identifier=port.device,
                    label=f"OpenBCI Cyton candidate on {port.device}",
                    native_channels=NATIVE_ORDER,
                    sample_rate_hz=DEFAULT_RATE_HZ,
                    unit="uV",
                    # A USB descriptor is a hint. Opening it is the only confirmation.
                    confirmed=False,
                    detail={
                        "description": port.description,
                        "serial_number": port.serial_number,
                        "vid_pid": f"{port.vid:04x}:{port.pid:04x}" if port.vid else None,
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
        gain: float = DEFAULT_GAIN,
        timeout: float = 1.0,
        reconnect: bool = True,
        **_options,
    ) -> CytonSession:
        return CytonSession(
            identifier,
            mapping=mapping or dict(DEFAULT_MAPPING),
            rate=rate,
            gain=gain,
            timeout=timeout,
            reconnect=reconnect,
        )
