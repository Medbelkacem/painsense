"""Physiological reference ranges by age band and by physiological state.

Every number in this file is configuration, not code. Each band carries the source it
was taken from in a comment directly above it. A value that could not be traced to a
named source is marked TO VERIFY and the band is marked unverified, which makes the
platform report it as unverified wherever it is used rather than presenting it as
established. Nothing here is invented to fill a gap: a range that is not known is left
out and the field is simply not checked for that band.

Sources referred to below, in full:

  FLEMING   Fleming S. et al., "Normal ranges of heart rate and respiratory rate in
            children from birth to 18 years of age: a systematic review of observational
            studies", The Lancet, 2011, 377(9770), 1011-1018.
            DOI: 10.1016/S0140-6736(10)62226-X
            Gives centile curves, not bands. The bands below are read off those curves
            and are therefore approximations of a continuous function.

  PALS      American Heart Association, Pediatric Advanced Life Support, vital-sign
            tables for age. Widely reproduced; the exact band edges differ between
            editions.

  AAP2017   Flynn J.T. et al., "Clinical Practice Guideline for Screening and Management
            of High Blood Pressure in Children and Adolescents", Pediatrics, 2017,
            140(3). Paediatric blood pressure is defined on age, sex and height
            centiles, so it cannot be reduced to one band per age. It is deliberately
            not banded here.

  HEGER     Hegenbarth M.A. / general paediatric practice for neonatal respiratory rate.
            TO VERIFY: the primary source for the 30-60 breaths/min figure was not
            confirmed.

  SANGHAVI  Sanghavi M., Rutherford J.D., "Cardiovascular Physiology of Pregnancy",
            Circulation, 2014, 130(12), 1003-1008. Resting heart rate rises and blood
            volume increases through gestation.

  MACKOWIAK Mackowiak P.A. et al., on the relation between body temperature and heart
            rate. The "roughly 10 beats per minute per degree Celsius" figure is widely
            quoted. TO VERIFY: the coefficient is reported between about 8 and 10 and is
            not a constant across patients.
"""

from dataclasses import dataclass, field

TO_VERIFY = "TO VERIFY"

ADULT = "ADULT"


@dataclass(frozen=True)
class Band:
    code: str
    label: str
    # Inclusive age bounds in years. None on either side means unbounded.
    min_age: float | None
    max_age: float | None
    source: str
    # Resting ranges a value is compared against, per vital. A vital absent from this
    # mapping is not checked against a reference range for this band.
    normal: dict[str, tuple[float, float]]
    # Outside this, the reading is treated as a probable transcription error rather than
    # as a finding. Falls back to the adult band where a band does not narrow it.
    plausible: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Inside plausible but unusual enough to be worth confirming before anything is read
    # into it. This is a platform heuristic for catching typing slips, not a clinical
    # threshold, and it is left empty for a band where no defensible figure was found.
    # A vital absent here simply gets no "confirm this" prompt for that band.
    outlier: dict[str, tuple[float, float]] = field(default_factory=dict)
    unverified: tuple[str, ...] = ()
    note: str = ""


BANDS = (
    Band(
        "NEONATE",
        "Newborn, 0 to 1 month",
        0.0,
        1 / 12,
        "FLEMING, PALS, HEGER",
        {
            # FLEMING: heart rate rises over the first weeks before falling; the 1st to
            # 99th centile at birth spans roughly 90-190. PALS newborn awake 100-205.
            # The band below is the overlap of the two and is wide on purpose.
            "hr": (100.0, 180.0),
            # HEGER: 30-60 breaths/min. TO VERIFY.
            "resp_rate": (30.0, 60.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.5, 37.5),
        },
        plausible={"hr": (50.0, 260.0), "resp_rate": (10.0, 100.0)},
        unverified=("resp_rate",),
        note=(
            "Blood pressure is not banded for this age: AAP2017 defines it on age, sex "
            "and height centiles. A recorded pressure is stored and shown but is not "
            "compared against a reference range."
        ),
    ),
    Band(
        "INFANT",
        "Infant, 1 to 12 months",
        1 / 12,
        1.0,
        "FLEMING, PALS",
        {
            # FLEMING: median around 140 at 1 month falling towards 125 at 1 year.
            "hr": (100.0, 170.0),
            # FLEMING: 1st-99th centile approximately 25-55 over the first year.
            "resp_rate": (25.0, 55.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.5, 37.5),
        },
        plausible={"hr": (50.0, 240.0), "resp_rate": (10.0, 90.0)},
        note="Blood pressure not banded; see AAP2017.",
    ),
    Band(
        "TODDLER",
        "Young child, 1 to 3 years",
        1.0,
        3.0,
        "FLEMING, PALS",
        {
            "hr": (90.0, 150.0),
            "resp_rate": (20.0, 40.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.5, 37.5),
        },
        plausible={"hr": (50.0, 220.0), "resp_rate": (8.0, 80.0)},
        note="Blood pressure not banded; see AAP2017.",
    ),
    Band(
        "YOUNG_CHILD",
        "Child, 3 to 7 years",
        3.0,
        7.0,
        "FLEMING, PALS",
        {
            "hr": (80.0, 130.0),
            "resp_rate": (18.0, 30.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.3, 37.5),
        },
        plausible={"hr": (45.0, 210.0), "resp_rate": (8.0, 70.0)},
        note="Blood pressure not banded; see AAP2017.",
    ),
    Band(
        "OLDER_CHILD",
        "Child, 7 to 12 years",
        7.0,
        12.0,
        "FLEMING, PALS",
        {
            "hr": (70.0, 120.0),
            "resp_rate": (16.0, 26.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.1, 37.5),
        },
        plausible={"hr": (40.0, 200.0), "resp_rate": (6.0, 60.0)},
        note="Blood pressure not banded; see AAP2017.",
    ),
    Band(
        "ADOLESCENT",
        "Adolescent, 12 to 18 years",
        12.0,
        18.0,
        "FLEMING, PALS",
        {
            "hr": (60.0, 110.0),
            "resp_rate": (12.0, 22.0),
            "sbp": (95.0, 140.0),
            "dbp": (55.0, 90.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.1, 37.9),
        },
        unverified=("sbp", "dbp"),
        note=(
            "Blood pressure converges on the adult band towards the end of this range. "
            "TO VERIFY: the band edges above are the adult ones and are not taken from "
            "AAP2017 centiles."
        ),
    ),
    Band(
        ADULT,
        "Adult, 18 years and over",
        18.0,
        None,
        "General clinical practice",
        {
            "hr": (50.0, 100.0),
            "resp_rate": (10.0, 20.0),
            "sbp": (95.0, 145.0),
            "dbp": (55.0, 95.0),
            "spo2": (95.0, 100.0),
            "temperature_c": (36.0, 37.9),
            "glucose_mmol": (3.9, 11.0),
        },
        plausible={
            "hr": (10.0, 300.0),
            "resp_rate": (2.0, 80.0),
            "sbp": (40.0, 300.0),
            "dbp": (20.0, 200.0),
            "spo2": (30.0, 100.0),
            "temperature_c": (25.0, 45.0),
            "glucose_mmol": (0.5, 60.0),
        },
        outlier={
            "hr": (35.0, 170.0),
            "resp_rate": (6.0, 45.0),
            "sbp": (65.0, 230.0),
            "dbp": (35.0, 130.0),
            "spo2": (75.0, 100.0),
            "temperature_c": (33.5, 41.5),
            "glucose_mmol": (1.5, 35.0),
            "bmi": (12.0, 60.0),
        },
        note=(
            "The reference band every other band falls back to for a vital it does not "
            "itself narrow."
        ),
    ),
)

BY_CODE = {band.code: band for band in BANDS}
ADULT_BAND = BY_CODE[ADULT]


def band_for_age(age: float | None) -> Band:
    """The band an age falls in. An unknown age is treated as adult, which is what the
    rest of the platform already assumes, and the quality gate blocks on a missing age
    before an estimate is produced anyway."""
    if age is None:
        return ADULT_BAND
    for band in BANDS:
        low = band.min_age if band.min_age is not None else float("-inf")
        high = band.max_age if band.max_age is not None else float("inf")
        if low <= age < high:
            return band
    return ADULT_BAND


def normal(band: Band) -> dict[str, tuple[float, float]]:
    return dict(band.normal)


def plausible(band: Band) -> dict[str, tuple[float, float]]:
    """A band narrows only the vitals it names; everything else keeps the adult limits,
    because a figure outside those is a data-entry problem at any age."""
    merged = dict(ADULT_BAND.plausible)
    merged.update(band.plausible)
    return merged


def outlier(band: Band) -> dict[str, tuple[float, float]]:
    """Unusual-but-possible limits, for the bands that have them. Not inherited from the
    adult band: an adult's unusual heart rate says nothing about a newborn's, and a
    borrowed figure would be worse than no prompt at all."""
    if band.code == ADULT:
        return dict(ADULT_BAND.outlier)
    merged = {name: ADULT_BAND.outlier[name] for name in ("bmi",) if name in ADULT_BAND.outlier}
    merged.update(band.outlier)
    return merged


def widest_plausible() -> dict[str, tuple[float, float]]:
    """The union of every band's plausible limits. What an input field has to accept so
    that no band's legitimate reading is refused before a profile is even known."""
    merged: dict[str, tuple[float, float]] = {}
    for band in BANDS:
        for name, (low, high) in plausible(band).items():
            if name in merged:
                current_low, current_high = merged[name]
                merged[name] = (min(current_low, low), max(current_high, high))
            else:
                merged[name] = (low, high)
    return merged


# ---------------------------------------------------------------------------
# Corrections applied on top of a band for a physiological state.
# ---------------------------------------------------------------------------

# SANGHAVI: resting heart rate rises through gestation, by roughly 10-20 bpm at term,
# and blood volume increases by 30-50 per cent. Systolic pressure falls slightly in the
# second trimester and returns towards baseline in the third.
# TO VERIFY: the per-trimester figures below are read from the shape of that review
# rather than quoted from a table in it.
PREGNANCY_HR_SHIFT = {1: 5.0, 2: 12.0, 3: 16.0}
PREGNANCY_SBP_SHIFT = {1: 0.0, 2: -5.0, 3: 0.0}
PREGNANCY_UNVERIFIED = True

# MACKOWIAK: roughly 10 beats per minute per degree Celsius above 37. Reported between
# about 8 and 10 and not constant across patients, so this is used to explain a raised
# heart rate, never to correct a recorded value.
FEVER_HR_PER_DEGREE = 10.0
FEVER_REFERENCE_TEMPERATURE = 37.0
FEVER_UNVERIFIED = True


def with_pregnancy(
    ranges: dict[str, tuple[float, float]], trimester: int | None
) -> dict[str, tuple[float, float]]:
    """Shift the heart-rate and systolic bands for pregnancy. An unknown trimester gets
    no shift rather than an assumed one."""
    if trimester not in PREGNANCY_HR_SHIFT:
        return dict(ranges)

    shifted = dict(ranges)
    for name, shift in (
        ("hr", PREGNANCY_HR_SHIFT[trimester]),
        ("sbp", PREGNANCY_SBP_SHIFT[trimester]),
    ):
        if name in shifted and shift:
            low, high = shifted[name]
            shifted[name] = (low + shift, high + shift)
    return shifted


def fever_heart_rate_allowance(temperature_c: float | None) -> float:
    """How much of a raised heart rate a fever on its own would account for. Zero below
    the reference temperature."""
    if temperature_c is None or temperature_c <= FEVER_REFERENCE_TEMPERATURE:
        return 0.0
    return (temperature_c - FEVER_REFERENCE_TEMPERATURE) * FEVER_HR_PER_DEGREE


def unverified_fields(band: Band) -> tuple[str, ...]:
    return band.unverified
