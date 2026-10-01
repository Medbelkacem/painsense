"""Reference data for burn assessment: regions, depth categories and surface-area charts.

Nothing here is derived from data. It is the published clinical reference material the
assessment module works from, written out so that a calculation can be shown with its
inputs rather than presented as a number from nowhere.

Two charts are carried, because they answer the same question for different patients.
The Rule of Nines divides an adult into multiples of nine and is quick at the bedside.
Lund and Browder's chart gives a head and lower limbs that change with age, and is the
one to use for a child: an infant's head is about 19% of its surface against an adult's
7%, so applying adult percentages to a child understates a head burn by more than half.
`tbsa.py` refuses to use the adult chart on a child for that reason.

Both charts are expressed over the same region list, so a region selected once can be
costed under either method and the two compared.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- depth ----------------------------------------------------------------------------

SUPERFICIAL_EPIDERMAL = "SUPERFICIAL_EPIDERMAL"
SUPERFICIAL_PARTIAL = "SUPERFICIAL_PARTIAL"
DEEP_PARTIAL = "DEEP_PARTIAL"
FULL_THICKNESS = "FULL_THICKNESS"
DEPTH_UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class Depth:
    code: str
    label: str
    #: The older terminology, kept as a secondary label because it is still what many
    #: clinicians and most patients say.
    legacy_label: str
    #: Whether this depth counts towards the burned surface area. Superficial epidermal
    #: injury — ordinary erythema, sunburn — is excluded from every published TBSA method,
    #: and including it is the most common way a resuscitation estimate goes wrong.
    counts_towards_tbsa: bool
    appearance: str
    sensation: str
    note: str = ""


DEPTHS: tuple[Depth, ...] = (
    Depth(
        SUPERFICIAL_EPIDERMAL,
        "Superficial epidermal",
        "First degree",
        False,
        "Dry, red, no blisters. Blanches with pressure.",
        "Painful.",
        "Excluded from the surface area total, as in every published TBSA method.",
    ),
    Depth(
        SUPERFICIAL_PARTIAL,
        "Superficial partial-thickness",
        "Second degree, superficial",
        True,
        "Moist, pink, blisters. Blanches with pressure and refills.",
        "Very painful, often more so than a deeper burn.",
    ),
    Depth(
        DEEP_PARTIAL,
        "Deep partial-thickness",
        "Second degree, deep",
        True,
        "Blotchy red or pale, may blister. Sluggish or absent blanching.",
        "Reduced to pinprick; pressure may still be felt.",
    ),
    Depth(
        FULL_THICKNESS,
        "Full-thickness",
        "Third degree",
        True,
        "White, waxy, leathery or charred. Does not blanch.",
        "Insensate in the burned area itself.",
        "Reduced sensation here does not mean the patient is comfortable: the surrounding "
        "partial-thickness margin is usually painful, and a low pain score must not be "
        "read as a less serious burn.",
    ),
    Depth(
        DEPTH_UNCERTAIN,
        "Uncertain, requires clinician assessment",
        "Indeterminate",
        True,
        "Not yet established.",
        "Not yet established.",
        "Counted towards the surface area so an estimate is not optimistic while the "
        "assessment is open. The total is marked provisional until a clinician decides.",
    ),
)

DEPTH_BY_CODE = {entry.code: entry for entry in DEPTHS}
#: Depths that contribute to the burned surface area.
COUNTED_DEPTHS = frozenset(entry.code for entry in DEPTHS if entry.counts_towards_tbsa)

# --- cause ------------------------------------------------------------------------------

CAUSES = (
    ("THERMAL_CONTACT", "Thermal contact with a hot object"),
    ("SCALD", "Hot liquid or steam"),
    ("FLAME", "Flame"),
    ("ELECTRICAL", "Electrical"),
    ("CHEMICAL", "Chemical"),
    ("RADIATION", "Radiation, including sun"),
    ("FRICTION", "Friction"),
    ("OTHER", "Other"),
)

CAUSE_CODES = frozenset(code for code, _ in CAUSES)

#: Causes whose visible surface injury routinely understates the damage beneath it, and
#: which therefore raise a review flag regardless of the estimated area.
DECEPTIVE_CAUSES = frozenset({"ELECTRICAL", "CHEMICAL"})

# --- regions ------------------------------------------------------------------------------

LEFT, RIGHT, MIDLINE = "LEFT", "RIGHT", "MIDLINE"

#: Age-banded percentages from Lund and Browder's chart, for the three areas whose share
#: of the body surface changes as a person grows. Each value is for *one half* of the
#: named area, which is how the chart is published; `Region.share` doubles it where a
#: region covers both halves.
#: Bands are the published ones: under 1, 1-4, 5-9, 10-14, 15-17, adult. Each is written
#: as [lower, upper) over *fractional* years, not whole ones. An eleven-month-old is 0.92
#: years old, and a band written as whole years 0 to 0 would not contain them — they would
#: fall through every band to the adult chart and have a head burn costed at 7% instead of
#: 19%. The chart's own first row is "under 1", so that is what is encoded.
AGE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 1.0, "infant"),
    (1.0, 5.0, "young_child"),
    (5.0, 10.0, "child"),
    (10.0, 15.0, "older_child"),
    (15.0, 18.0, "adolescent"),
    (18.0, float("inf"), "adult"),
)

LUND_BROWDER_VARIABLE: dict[str, dict[str, float]] = {
    # One half of the head.
    "head_half": {
        "infant": 9.5,
        "young_child": 8.5,
        "child": 6.5,
        "older_child": 5.5,
        "adolescent": 4.5,
        "adult": 3.5,
    },
    # One half of one thigh.
    "thigh_half": {
        "infant": 2.75,
        "young_child": 3.25,
        "child": 4.0,
        "older_child": 4.25,
        "adolescent": 4.5,
        "adult": 4.75,
    },
    # One half of one lower leg.
    "leg_half": {
        "infant": 2.5,
        "young_child": 2.5,
        "child": 2.75,
        "older_child": 3.0,
        "adolescent": 3.25,
        "adult": 3.5,
    },
}


@dataclass(frozen=True)
class Region:
    code: str
    label: str
    side: str
    #: Fixed share of total body surface under Lund-Browder, where the region's share does
    #: not change with age. None where it does, and `variable` names the chart row.
    fixed_percent: float | None
    variable: str | None
    #: How many halves of the variable area this region covers — a whole thigh is two.
    halves: int
    #: The Rule of Nines block this region belongs to, and that block's adult percentage.
    nines_group: str
    #: A burn here warrants clinician review whatever its size: these are the regions where
    #: a small burn threatens function, airway or continence.
    high_risk: bool = False
    note: str = ""

    def share(self, band: str) -> float:
        """This region's percentage of total body surface for the given age band."""
        if self.fixed_percent is not None:
            return self.fixed_percent
        return round(LUND_BROWDER_VARIABLE[self.variable][band] * self.halves, 4)


REGIONS: tuple[Region, ...] = (
    Region("HEAD", "Head", MIDLINE, None, "head_half", 2, "HEAD_NECK", True,
           "Includes the face and scalp. Its share of the body surface falls steeply with age."),
    Region("NECK", "Neck", MIDLINE, 2.0, None, 0, "HEAD_NECK", True,
           "A circumferential neck burn can compromise the airway."),
    Region("TRUNK_ANTERIOR", "Anterior trunk", MIDLINE, 13.0, None, 0, "TRUNK_ANTERIOR"),
    Region("TRUNK_POSTERIOR", "Posterior trunk", MIDLINE, 13.0, None, 0, "TRUNK_POSTERIOR"),
    Region("BUTTOCK_LEFT", "Left buttock", LEFT, 2.5, None, 0, "TRUNK_POSTERIOR"),
    Region("BUTTOCK_RIGHT", "Right buttock", RIGHT, 2.5, None, 0, "TRUNK_POSTERIOR"),
    Region("GENITALIA", "Perineum and genitalia", MIDLINE, 1.0, None, 0, "PERINEUM", True,
           "Small in area and high in consequence; always flagged for review."),
    Region("UPPER_ARM_LEFT", "Left upper arm", LEFT, 4.0, None, 0, "ARM_LEFT"),
    Region("UPPER_ARM_RIGHT", "Right upper arm", RIGHT, 4.0, None, 0, "ARM_RIGHT"),
    Region("FOREARM_LEFT", "Left forearm", LEFT, 3.0, None, 0, "ARM_LEFT"),
    Region("FOREARM_RIGHT", "Right forearm", RIGHT, 3.0, None, 0, "ARM_RIGHT"),
    Region("HAND_LEFT", "Left hand", LEFT, 2.5, None, 0, "ARM_LEFT", True,
           "Function is at stake even with a small area."),
    Region("HAND_RIGHT", "Right hand", RIGHT, 2.5, None, 0, "ARM_RIGHT", True,
           "Function is at stake even with a small area."),
    Region("THIGH_LEFT", "Left thigh", LEFT, None, "thigh_half", 2, "LEG_LEFT"),
    Region("THIGH_RIGHT", "Right thigh", RIGHT, None, "thigh_half", 2, "LEG_RIGHT"),
    Region("LOWER_LEG_LEFT", "Left lower leg", LEFT, None, "leg_half", 2, "LEG_LEFT"),
    Region("LOWER_LEG_RIGHT", "Right lower leg", RIGHT, None, "leg_half", 2, "LEG_RIGHT"),
    Region("FOOT_LEFT", "Left foot", LEFT, 3.5, None, 0, "LEG_LEFT", True,
           "Function is at stake even with a small area."),
    Region("FOOT_RIGHT", "Right foot", RIGHT, 3.5, None, 0, "LEG_RIGHT", True,
           "Function is at stake even with a small area."),
)

REGION_BY_CODE = {entry.code: entry for entry in REGIONS}
HIGH_RISK_REGIONS = frozenset(entry.code for entry in REGIONS if entry.high_risk)

#: Rule of Nines blocks and their adult percentages. Each sums the regions that make it up,
#: which is why both methods can be applied to the same selection.
NINES: dict[str, float] = {
    "HEAD_NECK": 9.0,
    "TRUNK_ANTERIOR": 18.0,
    "TRUNK_POSTERIOR": 18.0,
    "ARM_LEFT": 9.0,
    "ARM_RIGHT": 9.0,
    "LEG_LEFT": 18.0,
    "LEG_RIGHT": 18.0,
    "PERINEUM": 1.0,
}

NINES_LABELS = {
    "HEAD_NECK": "Head and neck",
    "TRUNK_ANTERIOR": "Anterior trunk",
    "TRUNK_POSTERIOR": "Posterior trunk",
    "ARM_LEFT": "Left arm",
    "ARM_RIGHT": "Right arm",
    "LEG_LEFT": "Left leg",
    "LEG_RIGHT": "Right leg",
    "PERINEUM": "Perineum",
}

#: The patient's own palm with the fingers held together, as a share of their total body
#: surface. Published figures range from 0.8% to 1.0%; 1.0% is the common bedside
#: convention and the one recorded here, with the figure stated on every result so a
#: reader knows what was assumed.
PALM_PERCENT = 1.0


def band_for_age(age_years: float | None) -> str:
    """The Lund-Browder age band for a patient, defaulting to adult when age is unknown.

    An unknown age falling back to adult is recorded by the caller as an assumption rather
    than hidden, because for a child it is the wrong chart.
    """
    if age_years is None:
        return "adult"
    if age_years < 0:
        raise ValueError(f"age cannot be negative, got {age_years}")
    for low, high, name in AGE_BANDS:
        if low <= age_years < high:
            return name
    return "adult"


def is_child(age_years: float | None) -> bool:
    return age_years is not None and age_years < 15


def total_for_band(band: str) -> float:
    """Every region's share summed. Each published chart totals 100; this proves it."""
    return round(sum(region.share(band) for region in REGIONS), 4)
