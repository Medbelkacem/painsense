"""Reading the PainMonit database into this platform's own signal features.

PainMonit is two databases published together. The experimental half, PMHDB, is 52
volunteers under calibrated contact heat who rate each stimulus as it happens on a
continuous visual analogue scale. The clinical half, PMPDB, is 49 physiotherapy patients
over two sessions each, saying a 0-10 number out loud while the therapist works. Both are
synchronised at 250 Hz and carry skin conductance, blood volume pulse, respiration,
temperature and surface EMG; the experimental half adds ECG and the heater's own
temperature trace, the clinical half adds grip force.

The corpus is read through `app.signals.quality` and `app.signals.features` and not through
an extractor of its own. That is the whole point of this module. A model fitted on numbers
computed by some other code would be handed different numbers at the bedside under the same
names, and nothing anywhere would report the difference — the model would fit, score and
serve on quietly permuted inputs. Every figure trained on here comes out of the same two
functions that measure a recording made on a ward.

Which channels are used, and why the rest are not:

**Skin conductance.** The corpus publishes two EDA traces, one from the Empatica E4 and one
from the RespiBAN. The RespiBAN pair is the one read as this platform's `GSR_PALMAR`: it
sits at 8-25 uS where the E4's sits at 0.6-11, and palmar sites conduct markedly better
than the wrist, so the higher pair is the more palmar of the two. Both are already in
microsiemens, which is what the channel is defined in, so nothing is scaled.

**Pulse and respiration.** Read as `PPG_FINGER` and `RESPIRATION_BELT`. Every feature this
platform derives from either is a timing or a rate — beat intervals, variability, breaths
per minute — so their amplitude does not reach a feature at all. It does reach the quality
check, which asks whether a trace is flat or driven into the amplifier's rails, and those
bounds are this platform's. So each is multiplied by one fixed number, `GAINS` below, that
puts the corpus's median peak where the platform's own convention puts it. Fixed rather
than per-recording: a per-recording normalisation would rescale a genuinely saturated trace
down into range and the clipping check would stop meaning anything.

**EMG and ECG are not used.** The corpus samples everything at 250 Hz, and this platform's
EMG channels declare a 500 Hz minimum because surface EMG carries power well above 125 Hz.
Features taken from a 250 Hz trace are band-limited to half the band the same code computes
over at the bedside, so an amplitude or a median frequency would mean one thing in training
and another in use. `app.signals.quality` already refuses the channel for its rate; this
module does not work around that. There is no ECG channel in `app.signals.schema`.

The run-up recordings beside each clinical session are not read. They are the patient at
rest and are the obvious reference for a within-subject correction, which was tried: on
patient-grouped cross-validation the corrected features scored no better than the absolute
ones and neither beat predicting the mean, so the extra reading earns nothing.

The database is obtained under a signed data usage agreement: academic research only, no
redistribution. It is therefore never copied into this repository. `read` is pointed at
wherever the archives were put, reads them in place, and keeps nothing.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backend.signals import features as feature_module
from backend.signals import quality as quality_module

#: How the corpus is named in the model registry and in provenance.
CORPUS_ID = "painmonit"

#: Required of any publication reporting on the use of this database, by the terms of its
#: data usage agreement. Carried into the model's registry notes so it travels with the
#: model rather than living only in a README.
CITATION = (
    "Gouverneur, P., Badura, A., Li, F. et al. An Experimental and Clinical Physiological "
    "Signal Dataset for Automated Pain Recognition. Sci Data 11, 1051 (2024). "
    "https://doi.org/10.1038/s41597-024-03878-w"
)

LICENCE = (
    "PainMonit Database Usage Agreement, University of Lubeck: academic research only, "
    "no commercial use, no redistribution."
)

EXPERIMENTAL = "experimental"
CLINICAL = "clinical"
HALVES = (EXPERIMENTAL, CLINICAL)

#: Published sampling rate of both halves. Asserted against the recording's own time column
#: on the way in rather than trusted.
SAMPLE_RATE_HZ = 250.0

#: How far the measured rate may sit from the published one before the file is refused. The
#: time column is written to the millisecond, so a few parts in ten thousand is rounding.
RATE_TOLERANCE_HZ = 0.5

#: Where each half lives, as a zip as downloaded or as an extracted tree.
ARCHIVES = {EXPERIMENTAL: "PMED.zip", CLINICAL: "PMCD.zip"}
TREES = {EXPERIMENTAL: "PMHDB", CLINICAL: "PMPDB"}

#: Corpus column -> platform channel, and the factor that puts the column in the channel's
#: units. One for skin conductance, which is already in microsiemens. For the other two the
#: factor is the ratio between the corpus's median peak amplitude, measured over both
#: halves, and the amplitude `app.signals.simulate` treats as a normal trace — 110/1.4 for
#: the pulse and 8.4/1.4 for the belt, rounded. Neither reaches a feature value; see the
#: module docstring.
GAINS = {
    "Eda_RB": ("GSR_PALMAR", 1.0),
    "Bvp": ("PPG_FINGER", 1.0 / 80.0),
    "Resp": ("RESPIRATION_BELT", 1.0 / 6.0),
}

#: The heater's resting temperature. Every subject's trace sits here between stimuli.
BASELINE_TEMPERATURE_C = 32.0

#: One contact-heat stimulus lasts ten seconds, which is the window taken over it and also
#: the shortest recording `app.signals.schema` will report band power for.
STIMULUS_WINDOW_SECONDS = 10.0

#: Skin conductance answers a stimulus over a second or two, so the window starts a little
#: after the heater does rather than at the instant it moves. The same offset is held clear
#: of the next stimulus when a rest window is taken, so no rest window catches the rise.
RESPONSE_LAG_SECONDS = 2.0

#: Clinical windows end at the moment the patient says their number and reach back this far.
#: Twenty seconds holds three or four breaths and twenty-odd beats, which is what the
#: respiratory and variability features need, and still keeps 89% of the ratings — the rest
#: are spoken before twenty seconds of the session have been recorded. Patients are asked
#: every seven seconds on average, so consecutive windows overlap heavily and adjacent rows
#: are near-duplicates; the trainer's grouping is by patient, which is what keeps that out
#: of the held-out error.
CLINICAL_WINDOW_SECONDS = 20.0

_CLINICAL_SESSION = re.compile(r"/(P\d+_\d+)\.csv$")
_EXPERIMENTAL_SUBJECT = re.compile(r"/(S_\d+)-synchronised-data\.csv$")


class NoCorpus(RuntimeError):
    """The corpus is not where it was looked for, or the half asked for is not in it."""


@dataclass(frozen=True)
class Window:
    """One stretch of recording, the features taken off it, and what it is labelled with."""

    subject: str
    session: str
    #: Seconds into the recording where the window ends.
    at: float
    #: The label this window is fitted against: the patient's 0-10 number on the clinical
    #: half, the volunteer's 0-100 visual analogue rating on the experimental half.
    target: float
    #: Experimental half only: 0 for a rest window, 1 to 5 for the subject's calibrated
    #: heat steps in ascending order. None on the clinical half, which has no stimulus.
    level: int | None
    verdict: str
    features: dict[str, float] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def _sessions(root: Path, half: str) -> Iterator[tuple[str, str, object]]:
    """Every session in the half, as (subject, session key, something to read it from).

    The reader is either an open archive member or a path; `_frame` takes both. A zip is
    read in place because the experimental half is 3.3 GB extracted and the agreement it
    came under is not helped by a second copy of it.
    """
    pattern = _CLINICAL_SESSION if half == CLINICAL else _EXPERIMENTAL_SUBJECT
    archive = root / ARCHIVES[half]
    if archive.exists():
        with zipfile.ZipFile(archive) as opened:
            members = sorted(
                name for name in opened.namelist() if pattern.search("/" + name)
            )
        if not members:
            raise NoCorpus(f"{archive} holds no {half} session CSV")
        for name in members:
            key = pattern.search("/" + name).group(1)
            yield _subject_of(key, half), key, (archive, name)
        return

    tree = root / TREES[half] / "raw-data"
    if not tree.is_dir():
        raise NoCorpus(
            f"neither {archive.name} nor {TREES[half]}/raw-data was found under {root}. "
            "Point --dataset at the directory the PainMonit archives were downloaded to."
        )
    found = sorted(path for path in tree.rglob("*.csv") if pattern.search("/" + path.name))
    if not found:
        raise NoCorpus(f"{tree} holds no {half} session CSV")
    for path in found:
        key = pattern.search("/" + path.name).group(1)
        yield _subject_of(key, half), key, path


def _subject_of(key: str, half: str) -> str:
    """The person a session belongs to.

    On the clinical half `P07_2` is the second session of patient seven, and both of their
    sessions have to land on the same side of a split, so the patient is the group and not
    the session.
    """
    return key.split("_")[0] if half == CLINICAL else key


def _frame(source: object, columns: list[str]) -> pd.DataFrame:
    """One session's chosen columns. Semicolon-separated with a comma decimal mark."""
    if isinstance(source, tuple):
        archive, member = source
        with zipfile.ZipFile(archive) as opened, opened.open(member) as handle:
            return pd.read_csv(handle, sep=";", decimal=",", usecols=columns)
    return pd.read_csv(source, sep=";", decimal=",", usecols=columns)


def _rate_of(seconds: np.ndarray, where: str) -> float:
    """The recording's own sampling rate, refused if it is not the published one."""
    steps = np.diff(seconds[: min(len(seconds), 2000)])
    if len(steps) == 0:
        raise NoCorpus(f"{where} carries no samples")
    measured = 1.0 / float(np.median(steps))
    if abs(measured - SAMPLE_RATE_HZ) > RATE_TOLERANCE_HZ:
        raise NoCorpus(
            f"{where} is sampled at {measured:.1f} Hz, not the {SAMPLE_RATE_HZ:g} Hz this "
            "corpus publishes; the gains and window lengths here assume the published rate"
        )
    return SAMPLE_RATE_HZ


def _measure(
    channels: dict[str, np.ndarray], start: int, stop: int, rate: float
) -> tuple[str, dict[str, float], dict[str, str]]:
    """Quality and features for one window, through the platform's own two functions."""
    samples = {code: values[start:stop] for code, values in channels.items()}
    duration = (stop - start) / rate
    report = quality_module.assess(samples, rate=rate, duration=duration)
    extracted = feature_module.extract(samples, rate=rate, report=report)
    return report.verdict, extracted.values, extracted.skipped


def _channels(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        code: frame[column].to_numpy(dtype=float) * gain
        for column, (code, gain) in GAINS.items()
    }


def _clinical_windows(subject: str, session: str, frame: pd.DataFrame) -> list[Window]:
    """One window per spoken rating, reaching back from the moment it was said.

    A rating is a single non-null cell in a column that is otherwise empty, so the labelled
    instants are the only places there is anything to fit against. Ratings sharing a
    timestamp are taken once: the same instant cannot carry two windows.
    """
    seconds = frame["Seconds"].to_numpy(dtype=float)
    rate = _rate_of(seconds, session)
    channels = _channels(frame)
    rates = frame["Pain rates"].to_numpy(dtype=float)
    span = round(CLINICAL_WINDOW_SECONDS * rate)

    out: list[Window] = []
    seen: set[float] = set()
    for end in np.flatnonzero(np.isfinite(rates)):
        if end < span:
            # The rating was spoken before a full window had been recorded.
            continue
        at = round(float(seconds[end]), 3)
        if at in seen:
            continue
        seen.add(at)
        verdict, values, skipped = _measure(channels, end - span, end, rate)
        out.append(
            Window(
                subject=subject,
                session=session,
                at=at,
                target=float(rates[end]),
                level=None,
                verdict=verdict,
                features=values,
                skipped=skipped,
            )
        )
    return out


def _segments(heater: np.ndarray) -> list[tuple[int, int, float]]:
    """The heater trace cut into stretches of one temperature, as (start, stop, celsius)."""
    edges = np.r_[0, np.flatnonzero(np.diff(heater)) + 1]
    return [
        (int(start), int(stop), float(heater[start]))
        for start, stop in zip(edges, np.r_[edges[1:], len(heater)])
    ]


def _experimental_windows(subject: str, frame: pd.DataFrame) -> list[Window]:
    """A window over each heat stimulus, and one over the quiet before each.

    The subject's five calibrated temperatures are ranked rather than read as absolutes:
    they are set per person between their own threshold and tolerance, so 47 C is a
    different step for different people and the step number is the comparable thing.

    The label is the highest visual analogue rating reached over the stimulus and the ten
    seconds after it, because the dial is turned in response and the response is not
    instant. A rest window is labelled with the rating over the rest itself, which is
    normally nothing — the subject has already turned the dial back down.
    """
    seconds = frame["Seconds"].to_numpy(dtype=float)
    rate = _rate_of(seconds, subject)
    channels = _channels(frame)
    heater = frame["Heater_cleaned"].to_numpy(dtype=float)
    covas = frame["COVAS"].to_numpy(dtype=float)
    span = round(STIMULUS_WINDOW_SECONDS * rate)
    lag = round(RESPONSE_LAG_SECONDS * rate)

    segments = _segments(heater)
    steps = sorted({celsius for _, _, celsius in segments if celsius > BASELINE_TEMPERATURE_C})
    level_of = {celsius: index for index, celsius in enumerate(steps, start=1)}

    out: list[Window] = []
    for start, stop, celsius in segments:
        if celsius > BASELINE_TEMPERATURE_C:
            begin = start + lag
            finish = begin + span
            if finish > len(heater):
                continue
            level = level_of[celsius]
            rated = covas[start : min(len(covas), stop + span)]
        else:
            if stop - start < span + lag:
                # Too short to hold a window that stays clear of the next stimulus.
                continue
            finish = stop - lag
            begin = finish - span
            level = 0
            rated = covas[begin:finish]
        if not np.isfinite(rated).any():
            continue
        verdict, values, skipped = _measure(channels, begin, finish, rate)
        out.append(
            Window(
                subject=subject,
                session=subject,
                at=round(float(seconds[finish - 1]), 3),
                target=float(np.nanmax(rated)),
                level=level,
                verdict=verdict,
                features=values,
                skipped=skipped,
            )
        )
    return out


#: What each half's label is, said in the words the publisher uses for it. Stored with the
#: model so the number it produces is never read as something else.
SCALES = {
    EXPERIMENTAL: "COVAS continuous visual analogue scale, 0-100",
    CLINICAL: "patient-spoken numeric rating scale, 0-10",
}

_COLUMNS = {
    EXPERIMENTAL: ["Seconds", *GAINS, "Heater_cleaned", "COVAS"],
    CLINICAL: ["Seconds", *GAINS, "Pain rates"],
}


def read(root: Path, half: str, *, limit_subjects: int | None = None) -> list[Window]:
    """Every labelled window in one half of the corpus.

    `limit_subjects` is for a quick run over the first few people, not for sampling: the
    sessions are read in published order, so it is the first N and not a draw.
    """
    if half not in HALVES:
        raise NoCorpus(f"unknown half {half!r}; expected one of {HALVES}")
    columns = _COLUMNS[half]

    out: list[Window] = []
    subjects: list[str] = []
    for subject, session, source in _sessions(Path(root), half):
        if subject not in subjects:
            if limit_subjects is not None and len(subjects) >= limit_subjects:
                break
            subjects.append(subject)
        frame = _frame(source, columns)
        if half == CLINICAL:
            out.extend(_clinical_windows(subject, session, frame))
        else:
            out.extend(_experimental_windows(subject, frame))
    if not out:
        raise NoCorpus(f"no labelled window could be cut from the {half} half under {root}")
    return out


def table(windows: list[Window]) -> pd.DataFrame:
    """The windows as one frame, one column per feature.

    A feature missing from a window — an unusable channel, a pulse with no findable beats —
    is left as a null rather than filled. Which rows are complete is the trainer's decision
    to make and it needs to see the gaps to make it.
    """
    return pd.DataFrame(
        [
            {
                "subject": window.subject,
                "session": window.session,
                "at": window.at,
                "target": window.target,
                "level": window.level,
                "verdict": window.verdict,
                "skipped": ",".join(sorted(window.skipped)),
                **window.features,
            }
            for window in windows
        ]
    )
