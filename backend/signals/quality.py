"""Whether a recording is good enough for its features to mean anything.

Each check answers a question a reader of the analysis would otherwise have to take on
trust, and each one names the channel it failed on. Quality is reported per channel and
then summarised, because a usable EEG beside a detached EMG electrode is a common and
recoverable situation — the EEG features are fine and the EMG ones are not, and one overall
verdict would hide that.

The checks are deliberately crude. They catch the failures that actually happen when
electrodes are applied by someone who is not a technician: a lead that is not connected, a
lead that has come off mid-recording, an amplifier driven into its rails, and mains hum
swamping the signal. They are not a substitute for looking at the trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.signals import schema

GOOD = "GOOD"
ADEQUATE = "ADEQUATE"
POOR = "POOR"
UNUSABLE = "UNUSABLE"

#: Worst-first, so a summary is the worst channel's verdict.
ORDER = (GOOD, ADEQUATE, POOR, UNUSABLE)

#: Share of samples at or beyond the amplifier's range before the channel is unusable.
SATURATION_UNUSABLE = 0.05
SATURATION_POOR = 0.01

#: Share of total power in a narrow band around the mains frequency. Above the first the
#: signal is mostly hum; above the second it is contaminated but readable.
MAINS_UNUSABLE = 0.5
MAINS_POOR = 0.2

#: Width of the notch the mains check measures over, in hertz.
MAINS_WIDTH = 2.0


@dataclass
class ChannelQuality:
    channel: str
    verdict: str
    findings: list[str] = field(default_factory=list)
    sd: float = 0.0
    saturated_share: float = 0.0
    mains_share: float = 0.0
    missing_share: float = 0.0

    @property
    def usable(self) -> bool:
        return self.verdict in (GOOD, ADEQUATE)

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "verdict": self.verdict,
            "findings": self.findings,
            "sd": round(self.sd, 4),
            "saturated_share": round(self.saturated_share, 5),
            "mains_share": round(self.mains_share, 4),
            "missing_share": round(self.missing_share, 5),
        }


@dataclass
class Report:
    sample_rate_hz: float
    duration_seconds: float
    channels: list[ChannelQuality] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """The worst verdict among the EEG and EMG channels.

        Deliberately not the worst of all channels. The pulse, skin conductance and
        respiration channels are supporting information the brief asks to show where
        available, and a slipped chest belt must not invalidate a clean EEG and EMG
        recording. Their quality is still reported per channel and still decides whether
        their own figures are derived.

        With no primary channel at all the worst of whatever is present is used, because a
        recording of only supporting channels cannot support this analysis either.
        """
        if not self.channels:
            return UNUSABLE
        primary = [
            item.verdict
            for item in self.channels
            if (schema.CHANNEL_BY_CODE.get(item.channel) is not None)
            and schema.CHANNEL_BY_CODE[item.channel].modality in schema.PRIMARY_MODALITIES
        ]
        return max(primary or [item.verdict for item in self.channels], key=ORDER.index)

    @property
    def supporting_verdicts(self) -> dict[str, str]:
        """Per-channel verdicts for the supporting channels, reported but not decisive."""
        return {
            item.channel: item.verdict
            for item in self.channels
            if (schema.CHANNEL_BY_CODE.get(item.channel) is not None)
            and schema.CHANNEL_BY_CODE[item.channel].modality in schema.SUPPORTING_MODALITIES
        }

    @property
    def usable_channels(self) -> list[str]:
        return [item.channel for item in self.channels if item.usable]

    def for_channel(self, code: str) -> ChannelQuality | None:
        return next((item for item in self.channels if item.channel == code), None)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "sample_rate_hz": self.sample_rate_hz,
            "duration_seconds": round(self.duration_seconds, 2),
            "usable_channels": self.usable_channels,
            "supporting_channels": self.supporting_verdicts,
            "channels": [item.as_dict() for item in self.channels],
            "findings": self.findings,
        }


def _mains_share(values: np.ndarray, rate: float) -> float:
    """Share of total power sitting within a narrow band of a mains frequency."""
    if len(values) < 32 or rate <= 0:
        return 0.0
    spectrum = np.abs(np.fft.rfft(values - values.mean())) ** 2
    freqs = np.fft.rfftfreq(len(values), d=1.0 / rate)
    total = float(spectrum.sum())
    if total <= 0:
        return 0.0
    worst = 0.0
    for mains in schema.MAINS_HZ:
        if mains >= rate / 2:
            continue
        band = (freqs >= mains - MAINS_WIDTH / 2) & (freqs <= mains + MAINS_WIDTH / 2)
        worst = max(worst, float(spectrum[band].sum()) / total)
    return worst


def assess_channel(code: str, values: np.ndarray, rate: float) -> ChannelQuality:
    definition = schema.CHANNEL_BY_CODE.get(code)
    result = ChannelQuality(channel=code, verdict=GOOD)

    finite = np.isfinite(values)
    result.missing_share = float((~finite).mean()) if len(values) else 1.0
    usable = values[finite]
    if len(usable) < 2:
        result.verdict = UNUSABLE
        result.findings.append("the channel carries no finite sample")
        return result
    if result.missing_share > 0.2:
        result.verdict = POOR
        result.findings.append(
            f"{result.missing_share * 100:.1f}% of samples are missing or not finite"
        )

    result.sd = float(np.std(usable))
    floor = definition.flatline_sd if definition is not None else schema.DEFAULT_FLATLINE_SD
    if result.sd < floor:
        result.verdict = UNUSABLE
        result.findings.append(
            f"the channel is flat (SD {result.sd:.4f}), which means the electrode is not "
            "connected or the lead is broken rather than that the patient is still"
        )
        return result

    if definition is not None:
        result.saturated_share = float((np.abs(usable) >= definition.saturation).mean())
        if result.saturated_share >= SATURATION_UNUSABLE:
            result.verdict = UNUSABLE
            result.findings.append(
                f"{result.saturated_share * 100:.1f}% of samples are at or beyond the "
                f"amplifier range of {definition.saturation:g} {definition.unit}; the trace "
                "is clipped and its amplitude features are meaningless"
            )
        elif result.saturated_share >= SATURATION_POOR:
            result.verdict = _worse(result.verdict, POOR)
            result.findings.append(
                f"{result.saturated_share * 100:.1f}% of samples are clipped"
            )
        if rate < definition.minimum_rate_hz:
            result.verdict = _worse(result.verdict, POOR)
            result.findings.append(
                f"sampled at {rate:g} Hz, below the {definition.minimum_rate_hz:g} Hz this "
                f"channel needs to carry its band"
            )

    result.mains_share = _mains_share(usable, rate)
    if result.mains_share >= MAINS_UNUSABLE:
        result.verdict = UNUSABLE
        result.findings.append(
            f"{result.mains_share * 100:.0f}% of the channel's power is mains hum; the "
            "signal is buried in interference"
        )
    elif result.mains_share >= MAINS_POOR:
        result.verdict = _worse(result.verdict, POOR)
        result.findings.append(
            f"{result.mains_share * 100:.0f}% of the channel's power is mains hum"
        )

    if result.verdict == GOOD and (
        result.saturated_share > 0 or result.mains_share > 0.05 or result.missing_share > 0
    ):
        result.verdict = ADEQUATE
    return result


def _worse(current: str, candidate: str) -> str:
    return max((current, candidate), key=ORDER.index)


def assess(samples: dict[str, np.ndarray], *, rate: float, duration: float) -> Report:
    report = Report(sample_rate_hz=rate, duration_seconds=duration)
    for code, values in samples.items():
        report.channels.append(assess_channel(code, np.asarray(values, dtype=float), rate))

    if duration < schema.MINIMUM_DURATION_SECONDS:
        report.findings.append(
            f"the recording is {duration:.1f} s long. Band power needs at least "
            f"{schema.MINIMUM_DURATION_SECONDS:g} s to hold enough cycles of the slowest "
            "band to be worth reporting"
        )
    unusable = [item.channel for item in report.channels if not item.usable]
    if unusable:
        report.findings.append(
            "features were not derived for " + ", ".join(sorted(unusable))
        )
    if not any(
        schema.CHANNEL_BY_CODE.get(item.channel) is not None
        and schema.CHANNEL_BY_CODE[item.channel].modality in schema.PRIMARY_MODALITIES
        for item in report.channels
    ):
        report.findings.append(
            "the recording holds no EEG or EMG channel, which is what this analysis is of"
        )
    if not report.channels:
        report.findings.append("the recording holds no channel")
    return report
