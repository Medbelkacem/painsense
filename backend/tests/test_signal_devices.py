"""The acquisition adapters, driven by exact bytes through a fake serial port.

No hardware is attached in CI and none is needed: a protocol parser is testable by feeding
it the frames the protocol specifies. These construct Cyton frames byte by byte from the
published format and assert the decoded microvolts, which is the only way to know the scale
factor and the two's-complement handling are right without an amplifier on the bench.
"""

import json

import numpy as np
import pytest

from backend.signals.devices import base, gateway, openbci
from backend.signals.devices.base import DeviceUnavailable

# --- a fake serial port ------------------------------------------------------------------


class FakeSerial:
    """Stands in for `serial.Serial`, handing out a scripted byte stream.

    `fail_after` makes `read` raise once the given number of calls have been made, which is
    how disconnection mid-recording is reproduced.
    """

    def __init__(self, payload: bytes = b"", *, fail_after: int | None = None):
        self.payload = bytearray(payload)
        self.written = bytearray()
        self.is_open = True
        self.reads = 0
        self.fail_after = fail_after
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self.payload)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise OSError("device reports readiness to read but returned no data")
        chunk = bytes(self.payload[:size])
        del self.payload[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False
        self.closed = True

    def feed(self, data: bytes) -> None:
        self.payload.extend(data)


@pytest.fixture
def serial_factory(monkeypatch):
    """Install a FakeSerial for whatever the adapter under test opens."""
    created: list[FakeSerial] = []

    def _install(*ports: FakeSerial):
        queue = list(ports)

        def _factory(_port, _baud, timeout=None):
            port = queue.pop(0) if queue else FakeSerial()
            created.append(port)
            return port

        import serial

        monkeypatch.setattr(serial, "Serial", _factory)
        monkeypatch.setattr("time.sleep", lambda _seconds: None)
        return created

    return _install


# --- Cyton frame construction -------------------------------------------------------------


def cyton_frame(counter: int, counts: list[int], *, stop: int = 0xC0) -> bytes:
    """One 33-byte frame, built from the published format."""
    frame = bytearray([openbci.START_BYTE, counter & 0xFF])
    for value in counts:
        unsigned = value & 0xFFFFFF
        frame += bytes(((unsigned >> 16) & 0xFF, (unsigned >> 8) & 0xFF, unsigned & 0xFF))
    frame += bytes(6)  # auxiliary bytes
    frame.append(stop)
    assert len(frame) == openbci.FRAME_BYTES
    return bytes(frame)


def test_the_published_scale_factor_is_used():
    assert openbci.MICROVOLTS_PER_COUNT == pytest.approx(0.02235, abs=1e-5)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\x00\x00\x00", 0),
        (b"\x00\x00\x01", 1),
        (b"\x7f\xff\xff", 8388607),
        (b"\xff\xff\xff", -1),
        (b"\x80\x00\x00", -8388608),
    ],
)
def test_twenty_four_bit_two_complement_decoding(raw, expected):
    assert openbci._signed24(raw) == expected


def test_a_frame_decodes_to_the_expected_microvolts(serial_factory):
    counts = [0, 1000, -1000, 8388607, -8388608, 500, -500, 42]
    serial_factory(FakeSerial(cyton_frame(0, counts)))

    session = openbci.CytonAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert block is not None
    assert block.length == 1
    for position, native in enumerate(openbci.NATIVE_ORDER):
        code = openbci.DEFAULT_MAPPING.get(native)
        if code is None:
            continue
        want = counts[position] * openbci.MICROVOLTS_PER_COUNT
        assert block.samples[code][0] == pytest.approx(want, rel=1e-9)
    assert len(block.samples) == len(openbci.DEFAULT_MAPPING), (
        "an input the default montage leaves spare must not arrive as a channel"
    )
    session.close()


def test_the_board_is_told_to_start_streaming(serial_factory):
    created = serial_factory(FakeSerial(cyton_frame(0, [0] * 8)))
    session = openbci.CytonAdapter().open("/dev/fake")
    assert openbci.START_STREAM in bytes(created[0].written)
    session.close()
    assert openbci.STOP_STREAM in bytes(created[0].written)


def test_many_frames_come_back_in_order(serial_factory):
    frames = b"".join(cyton_frame(index, [index * 10] * 8) for index in range(20))
    serial_factory(FakeSerial(frames))

    session = openbci.CytonAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert block.length == 20
    assert list(np.diff(block.indices)) == [1] * 19
    first = block.samples["EEG_FPZ"]
    assert first[0] == pytest.approx(0.0)
    assert first[19] == pytest.approx(190 * openbci.MICROVOLTS_PER_COUNT, rel=1e-9)
    session.close()


# --- corruption and resynchronisation ------------------------------------------------------


def test_garbage_before_a_frame_is_counted_and_skipped(serial_factory):
    stream = b"\x11\x22\x33" + cyton_frame(7, [100] * 8)
    serial_factory(FakeSerial(stream))

    session = openbci.CytonAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert block.length == 1
    assert session.invalid_packets >= 1
    session.close()


def test_a_bad_stop_byte_is_refused_and_the_parser_resynchronises(serial_factory):
    bad = cyton_frame(1, [50] * 8, stop=0x99)
    good = cyton_frame(2, [60] * 8)
    serial_factory(FakeSerial(bad + good))

    session = openbci.CytonAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert block is not None
    assert session.invalid_packets >= 1
    # The good frame still arrives: a corrupt frame must not take the stream down.
    assert 60 * openbci.MICROVOLTS_PER_COUNT == pytest.approx(
        block.samples["EEG_FPZ"][-1], rel=1e-9
    )
    session.close()


def test_a_truncated_trailing_frame_waits_for_the_rest(serial_factory):
    whole = cyton_frame(1, [10] * 8)
    port = FakeSerial(whole + cyton_frame(2, [20] * 8)[:17])
    serial_factory(port)

    session = openbci.CytonAdapter().open("/dev/fake")
    first = session.read(timeout=0.3)
    assert first.length == 1, "the partial frame must not be parsed"

    port.feed(cyton_frame(2, [20] * 8)[17:])
    second = session.read(timeout=0.5)
    assert second.length == 1
    assert second.samples["EEG_FPZ"][0] == pytest.approx(
        20 * openbci.MICROVOLTS_PER_COUNT, rel=1e-9
    )
    session.close()


def test_dropped_samples_are_counted_from_the_index_gap(serial_factory):
    port = FakeSerial(cyton_frame(10, [0] * 8))
    serial_factory(port)
    session = openbci.CytonAdapter().open("/dev/fake")
    session.read(timeout=0.3)

    # The next frame is numbered 15: four samples were produced and never arrived.
    port.feed(cyton_frame(15, [0] * 8))
    block = session.read(timeout=0.5)

    assert block.dropped == 4
    assert session.dropped_samples == 4
    session.close()


def test_a_wrapping_counter_is_not_read_as_a_huge_drop(serial_factory):
    port = FakeSerial(cyton_frame(254, [0] * 8))
    serial_factory(port)
    session = openbci.CytonAdapter().open("/dev/fake")
    session.read(timeout=0.3)

    port.feed(cyton_frame(1, [0] * 8))  # 254 -> 1 across the wrap is two missing
    block = session.read(timeout=0.5)

    assert block.dropped == 2, "a single-byte counter wrap must not read as 253 drops"
    session.close()


def test_the_counter_is_unwrapped_into_a_monotonic_index(serial_factory):
    frames = b"".join(cyton_frame(index % 256, [0] * 8) for index in range(253, 260))
    serial_factory(FakeSerial(frames))
    session = openbci.CytonAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert list(np.diff(block.indices)) == [1] * (block.length - 1)
    assert block.indices[-1] > block.indices[0]
    session.close()


# --- disconnection and reconnection ----------------------------------------------------------


def test_a_disconnection_is_reported_when_reconnection_is_off(serial_factory):
    serial_factory(FakeSerial(cyton_frame(0, [0] * 8), fail_after=1))
    session = openbci.CytonAdapter().open("/dev/fake", reconnect=False)
    session.read(timeout=0.3)
    with pytest.raises(DeviceUnavailable, match="stopped responding"):
        session.read(timeout=0.3)


def test_reconnection_is_attempted_and_counted(serial_factory):
    first = FakeSerial(cyton_frame(0, [0] * 8), fail_after=1)
    second = FakeSerial(cyton_frame(0, [77] * 8))
    serial_factory(first, second)

    session = openbci.CytonAdapter().open("/dev/fake", reconnect=True)
    session.read(timeout=0.3)
    block = session.read(timeout=1.0)

    assert session.reconnects == 1
    assert session.last_error
    assert block is not None
    assert block.samples["EEG_FPZ"][0] == pytest.approx(
        77 * openbci.MICROVOLTS_PER_COUNT, rel=1e-9
    )
    session.close()


def test_a_port_that_cannot_be_opened_raises(monkeypatch):
    import serial

    def _refuse(*_args, **_kwargs):
        raise serial.SerialException("no such device")

    monkeypatch.setattr(serial, "Serial", _refuse)
    with pytest.raises(DeviceUnavailable, match="could not be opened"):
        openbci.CytonAdapter().open("/dev/nope")


def test_reading_a_closed_session_raises(serial_factory):
    serial_factory(FakeSerial(cyton_frame(0, [0] * 8)))
    session = openbci.CytonAdapter().open("/dev/fake")
    session.close()
    with pytest.raises(DeviceUnavailable, match="closed"):
        session.read(timeout=0.1)


# --- channel mapping -------------------------------------------------------------------------


def test_only_mapped_inputs_are_recorded(serial_factory):
    """Eight inputs with two electrodes attached should record two channels."""
    serial_factory(FakeSerial(cyton_frame(0, list(range(8)))))
    session = openbci.CytonAdapter().open(
        "/dev/fake", mapping={"N1P": "EEG_FPZ", "N5P": "EMG_TRAPEZIUS_L"}
    )
    block = session.read(timeout=0.5)

    assert set(block.samples) == {"EEG_FPZ", "EMG_TRAPEZIUS_L"}
    assert block.samples["EMG_TRAPEZIUS_L"][0] == pytest.approx(
        4 * openbci.MICROVOLTS_PER_COUNT, rel=1e-9
    )
    session.close()


def test_discovery_never_claims_an_unconfirmed_port_is_an_amplifier():
    for info in openbci.CytonAdapter().discover():
        assert info.confirmed is False


def test_discovery_without_pyserial_returns_nothing(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "serial.tools", None)
    # The adapter must degrade to an empty list rather than raising into discovery.
    assert isinstance(openbci.CytonAdapter().discover(), list)


# --- the JSON gateway -------------------------------------------------------------------------


def line(index: int, channels: dict[str, float]) -> bytes:
    return (json.dumps({"i": index, "ch": channels}) + "\n").encode()


def test_the_gateway_parses_its_json_protocol(serial_factory):
    stream = b"".join(
        line(index, {"EEG_FPZ": index * 1.5, "EMG_TRAPEZIUS_L": -index}) for index in range(5)
    )
    serial_factory(FakeSerial(stream))

    session = gateway.SerialGatewayAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert block.length == 5
    assert block.samples["EEG_FPZ"][4] == pytest.approx(6.0)
    assert block.samples["EMG_TRAPEZIUS_L"][4] == pytest.approx(-4.0)
    session.close()


@pytest.mark.parametrize(
    "bad",
    [
        b"not json at all\n",
        b'{"i": 1}\n',
        b'{"ch": {"EEG_FPZ": 1.0}}\n',
        b'{"i": "one", "ch": {"EEG_FPZ": 1.0}}\n',
        b'{"i": 1, "ch": {}}\n',
        b'{"i": 1, "ch": {"EEG_FPZ": "loud"}}\n',
        b'{"i": 1, "ch": {"EEG_FPZ": true}}\n',
        b'[1, 2, 3]\n',
    ],
)
def test_an_invalid_packet_is_counted_and_skipped(serial_factory, bad):
    serial_factory(FakeSerial(bad + line(2, {"EEG_FPZ": 9.0})))
    session = gateway.SerialGatewayAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert session.invalid_packets >= 1
    assert block is not None
    assert block.samples["EEG_FPZ"][-1] == pytest.approx(9.0)
    session.close()


def test_a_channel_absent_from_one_line_becomes_a_gap_not_a_zero(serial_factory):
    stream = line(1, {"EEG_FPZ": 1.0, "EEG_CZ": 2.0}) + line(2, {"EEG_FPZ": 3.0})
    serial_factory(FakeSerial(stream))

    session = gateway.SerialGatewayAdapter().open("/dev/fake")
    block = session.read(timeout=0.5)

    assert np.isnan(block.samples["EEG_CZ"][1]), "a missing value must be a gap, not 0"
    assert block.samples["EEG_FPZ"][1] == pytest.approx(3.0)
    session.close()


def test_a_line_longer_than_the_cap_is_discarded(serial_factory):
    serial_factory(FakeSerial(b"x" * (gateway.MAX_LINE_BYTES + 10)))
    session = gateway.SerialGatewayAdapter().open("/dev/fake")
    assert session.read(timeout=0.3) is None
    assert session.invalid_packets >= 1
    session.close()


def test_the_gateway_maps_device_names_onto_platform_codes(serial_factory):
    serial_factory(FakeSerial(line(1, {"ch0": 5.0})))
    session = gateway.SerialGatewayAdapter().open("/dev/fake", mapping={"ch0": "EEG_FPZ"})
    block = session.read(timeout=0.5)
    assert "EEG_FPZ" in block.samples
    session.close()


def test_the_gateway_declares_its_protocol_is_not_a_standard():
    described = gateway.SerialGatewayAdapter().describe()
    assert "not a standard eeg protocol" in described["protocol"].casefold()


# --- timestamps -------------------------------------------------------------------------------


def test_timestamps_come_from_the_index_and_rate_not_arrival_time():
    """Host arrival time cannot space samples milliseconds apart; the index can."""
    block = base.Block(
        samples={"EEG_FPZ": np.zeros(5)},
        indices=np.array([100, 101, 102, 103, 104]),
        host_time=1_700_000_000.0,
    )
    stamps = block.timestamps(rate=250.0, anchor_index=100, anchor_time=1_700_000_000.0)

    assert stamps.dtype == np.int64, "float seconds cannot space samples exactly"
    assert stamps[0] == 1_700_000_000_000_000_000
    # Exactly 4 ms apart at 250 Hz, with no drift from float rounding.
    assert list(np.diff(stamps)) == [4_000_000] * 4


def test_timestamps_stay_exact_at_a_high_emg_rate():
    """At 2 kHz the interval is 0.5 ms, which float64 epoch seconds cannot hold exactly."""
    block = base.Block(
        samples={"EMG_TRAPEZIUS_L": np.zeros(1000)},
        indices=np.arange(1000),
        host_time=1_700_000_000.0,
    )
    stamps = block.timestamps(rate=2000.0, anchor_index=0, anchor_time=1_700_000_000.0)
    assert set(np.diff(stamps)) == {500_000}


def test_gap_tracking_handles_a_first_block():
    assert base.track_gaps(np.array([5, 6, 7]), None) == 0


def test_gap_tracking_counts_a_hole():
    assert base.track_gaps(np.array([10, 11]), 7) == 2


def test_every_adapter_describes_its_transport_and_protocol():
    from backend.signals import devices

    for adapter in devices.ADAPTERS:
        described = adapter.describe()
        assert described["protocol"] and described["transport"]


def test_an_unknown_adapter_is_refused():
    from backend.signals import devices

    with pytest.raises(KeyError, match="no acquisition adapter"):
        devices.get("telepathy")


def test_ble_without_bleak_reports_unavailable_rather_than_crashing(monkeypatch):
    from backend.signals.devices import ble

    monkeypatch.setitem(__import__("sys").modules, "bleak", None)
    assert ble.BleGatewayAdapter().discover() == []
