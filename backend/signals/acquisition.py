"""The acquisition runner: a thread per recording, pulling from a device into storage.

One thread per open recording, started when the recording starts and joined when it stops.
It reads blocks from the adapter, writes them straight to the session's files, and keeps a
short ring of recent samples so the live view has something to draw. Nothing is held for the
whole recording: a ten-minute session is on disk, not in memory.

Three decisions worth stating.

**A device error does not end the recording.** The adapter reconnects where it can; the
runner counts the failure and keeps going. Acquisition stops only when the operator stops it
or the adapter gives up, and either way everything written so far is intact because writes
are flushed per block.

**A storage error does end it.** If the file cannot be written there is nothing useful to
continue for, so the runner records the error, marks the recording failed and stops. The
alternative — carrying on and silently discarding samples — would produce a recording whose
duration and sample count disagree with its files.

**The time base is anchored once.** The first block's host clock and device index set the
anchor, and every later sample's timestamp is derived from its index. That keeps the spacing
exactly 1/rate instead of inheriting USB and scheduler jitter; see `devices/base.py`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from backend.signals import schema, storage
from backend.signals.devices.base import DeviceUnavailable, Session

logger = logging.getLogger("painsense.signals.acquisition")

#: Samples kept per channel for the live view. At 250 Hz this is about twelve seconds, which
#: is enough to see the trace moving without holding the recording in memory.
LIVE_WINDOW = 3000

#: How long each adapter read is given before the loop comes round again to check whether it
#: has been asked to stop.
READ_TIMEOUT = 0.5


@dataclass
class Progress:
    """What the runner has done so far, read by the API while recording."""

    samples: int = 0
    rows_written: int = 0
    dropped: int = 0
    invalid_packets: int = 0
    reconnects: int = 0
    started_at: float = field(default_factory=time.time)
    last_block_at: float | None = None
    error: str | None = None
    finished: bool = False

    @property
    def elapsed(self) -> float:
        return round(time.time() - self.started_at, 2)

    @property
    def stalled_for(self) -> float | None:
        """Seconds since the last block, or None if none has arrived yet.

        Surfaced because a connected device producing nothing looks identical to a healthy
        one from the connection flag alone, and the operator should be able to tell.
        """
        if self.last_block_at is None:
            return None
        return round(time.time() - self.last_block_at, 2)

    def as_dict(self) -> dict:
        return {
            "samples": self.samples,
            "rows_written": self.rows_written,
            "dropped_samples": self.dropped,
            "invalid_packets": self.invalid_packets,
            "reconnects": self.reconnects,
            "elapsed_seconds": self.elapsed,
            "stalled_for_seconds": self.stalled_for,
            "error": self.error,
            "finished": self.finished,
        }


class Runner:
    """Acquires from one device into one session's files until told to stop."""

    def __init__(
        self,
        *,
        session: Session,
        writer: storage.SessionWriter,
        channel_rates: dict[str, float],
    ) -> None:
        self.session = session
        self.writer = writer
        self.channel_rates = channel_rates
        self.progress = Progress()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._live: dict[str, deque[float]] = {}
        self._anchor: tuple[int, float] | None = None
        self._thread = threading.Thread(
            target=self._run, name="signal-acquisition", daemon=True
        )

    # --- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> Progress:
        self._stop.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            # The adapter is wedged in a blocking read. The files are flushed per block so
            # nothing written is lost; the thread is a daemon and will not hold the process.
            logger.warning("acquisition thread did not stop within %.1fs", timeout)
            self.progress.error = self.progress.error or (
                "the acquisition thread did not stop cleanly; everything written before the "
                "stop is intact"
            )
        with self._lock:
            self.writer.close()
            self.progress.finished = True
        return self.progress

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    # --- the loop ----------------------------------------------------------------------

    def _rate_for(self, codes: list[str]) -> float:
        """The rate to time this block at.

        A block carries channels that may differ in rate. Timestamps are derived per block
        from the fastest channel present, because the device's index advances at its own
        rate and a slower channel's samples are repeats or gaps at that index.
        """
        rates = [self.channel_rates.get(code, 0.0) for code in codes]
        return max(rates) if rates else 0.0

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                block = self.session.read(timeout=READ_TIMEOUT)
            except DeviceUnavailable as exc:
                self.progress.error = str(exc)
                logger.warning("acquisition stopped: %s", exc)
                break
            except Exception as exc:  # an adapter bug must not take the process down
                self.progress.error = f"the acquisition adapter failed: {exc}"
                logger.exception("acquisition adapter raised")
                break

            if block is None or block.length == 0:
                continue

            if self._anchor is None:
                self._anchor = (int(block.indices[0]), block.host_time)
            anchor_index, anchor_time = self._anchor
            rate = self._rate_for(list(block.samples))
            timestamps = block.timestamps(
                rate=rate, anchor_index=anchor_index, anchor_time=anchor_time
            )

            try:
                with self._lock:
                    written = self.writer.append(
                        block.samples, indices=block.indices, timestamps=timestamps
                    )
            except storage.StorageError as exc:
                # Nothing useful to continue for: a recording whose samples are not reaching
                # disk would report a duration its files cannot support.
                self.progress.error = f"the recording could not be written: {exc}"
                logger.error("acquisition halted on a storage error: %s", exc)
                break

            self.progress.samples += block.length
            self.progress.rows_written += written
            self.progress.dropped += block.dropped
            self.progress.last_block_at = time.time()
            status = self.session.status()
            self.progress.invalid_packets = status["invalid_packets"]
            self.progress.reconnects = status["reconnects"]
            self._remember(block.samples)

        try:
            self.session.close()
        except Exception:
            logger.debug("closing the device session raised", exc_info=True)

    def _remember(self, samples: dict[str, np.ndarray]) -> None:
        with self._lock:
            for code, values in samples.items():
                ring = self._live.setdefault(code, deque(maxlen=LIVE_WINDOW))
                ring.extend(float(value) for value in values)

    # --- the live view -----------------------------------------------------------------

    def live(self, *, points: int = 600) -> dict:
        """Recent samples per channel, decimated for display.

        Decimated by striding and the factor is reported, so a reader knows the trace is not
        sample-accurate. Features are computed from the files, never from this.
        """
        with self._lock:
            snapshot = {code: list(ring) for code, ring in self._live.items()}
        channels: dict[str, list[float | None]] = {}
        stride = 1
        for code, values in snapshot.items():
            stride = max(1, len(values) // points)
            channels[code] = [
                None if not np.isfinite(value) else round(value, 4)
                for value in values[::stride]
            ]
        return {
            "channels": channels,
            "decimation": stride,
            "window_samples": LIVE_WINDOW,
            "rates": {
                code: self.channel_rates.get(code, 0.0) for code in snapshot
            },
            "device": self.session.status(),
            "progress": self.progress.as_dict(),
            "notice": (
                "A decimated window of the most recent samples, for display only. The "
                "stored files are what the analysis reads."
            ),
        }


class _Runners:
    """The runners currently acquiring, keyed by recording id."""

    def __init__(self) -> None:
        self._runners: dict[str, Runner] = {}
        self._lock = threading.Lock()

    def add(self, recording_id, runner: Runner) -> None:
        with self._lock:
            self._runners[str(recording_id)] = runner
        runner.start()

    def get(self, recording_id) -> Runner | None:
        with self._lock:
            return self._runners.get(str(recording_id))

    def pop(self, recording_id) -> Runner | None:
        with self._lock:
            return self._runners.pop(str(recording_id), None)

    def active(self) -> list[str]:
        with self._lock:
            return [key for key, runner in self._runners.items() if runner.running]


runners = _Runners()


def primary_rate(channel_rates: dict[str, float]) -> float:
    """The rate to show as the session's own.

    The EEG rate where there is one, because EEG is what the analysis is of; otherwise the
    highest rate present. A session with no channel at all has no rate and says 0.
    """
    eeg = [
        rate
        for code, rate in channel_rates.items()
        if (schema.CHANNEL_BY_CODE.get(code) is not None)
        and schema.CHANNEL_BY_CODE[code].modality == schema.EEG
    ]
    if eeg:
        return max(eeg)
    return max(channel_rates.values(), default=0.0)
