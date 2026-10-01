"""Estimating the burned share of the body surface.

Three methods, each with the patients it is for, and a calculation that shows its work.
A resuscitation volume is derived from this number, so a total that cannot be traced back
to the regions and percentages that produced it is not good enough.

Two refusals are built in rather than left to the caller.

*The adult chart is not applied to a child.* An infant's head is about 19% of its body
surface and an adult's about 7%. Costing a child's head burn at adult percentages
understates it by more than half, so `RULE_OF_NINES` on a patient under 15 raises
`WrongChart` instead of returning a number that looks reasonable.

*Superficial epidermal injury is not counted.* Ordinary erythema is excluded from every
published method. It is still recorded and still reported, under its own heading, so the
exclusion is visible rather than silent.

An area whose depth has not yet been decided is counted, and the estimate is marked
provisional. An open assessment should not read as reassuring because nobody has looked
yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from knowledge import burns

LUND_BROWDER = "LUND_BROWDER"
RULE_OF_NINES = "RULE_OF_NINES"
PALM = "PALM"
METHODS = (LUND_BROWDER, RULE_OF_NINES, PALM)

#: Below this age the Rule of Nines is refused outright.
ADULT_CHART_MINIMUM_AGE = 15

#: The palm method is for scattered small burns. Past this many palms the error in
#: counting them exceeds the error in charting the regions properly.
PALM_SENSIBLE_LIMIT = 15


class WrongChart(ValueError):
    """The method chosen does not apply to this patient."""


class UnknownRegion(ValueError):
    """A region code that is not on the chart."""


@dataclass(frozen=True)
class Involvement:
    """One burned area, as selected on the body chart.

    `fraction` is how much of the named region is involved, from 0 to 1. Selecting a whole
    forearm is 1.0; a patch over a third of it is 0.33. The fraction is the clinician's or
    the patient's estimate, and the contribution it produces is only ever as good as it is.
    """

    region_code: str
    depth: str
    fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.region_code not in burns.REGION_BY_CODE:
            raise UnknownRegion(f"unknown body region {self.region_code!r}")
        if self.depth not in burns.DEPTH_BY_CODE:
            raise ValueError(f"unknown burn depth {self.depth!r}")
        if not 0.0 <= self.fraction <= 1.0:
            raise ValueError(f"fraction must be between 0 and 1, got {self.fraction}")


@dataclass
class Contribution:
    region_code: str
    region_label: str
    depth: str
    depth_label: str
    fraction: float
    region_percent: float
    contribution: float
    counted: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "region_code": self.region_code,
            "region_label": self.region_label,
            "depth": self.depth,
            "depth_label": self.depth_label,
            "fraction_of_region": self.fraction,
            "region_percent_of_body": self.region_percent,
            "contribution_percent": self.contribution,
            "counted": self.counted,
            "reason": self.reason,
        }


@dataclass
class Estimate:
    method: str
    age_years: float | None
    age_band: str
    total_percent: float
    excluded_percent: float
    contributions: list[Contribution] = field(default_factory=list)
    #: True while any involved area's depth is undecided. The total is a working figure
    #: until a clinician has assessed every area.
    provisional: bool = False
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    palms: float | None = None

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "age_years": self.age_years,
            "age_band": self.age_band,
            "total_percent": self.total_percent,
            "excluded_superficial_percent": self.excluded_percent,
            "provisional": self.provisional,
            "palms": self.palms,
            "contributions": [item.as_dict() for item in self.contributions],
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "formula": FORMULAE[self.method],
        }


FORMULAE = {
    LUND_BROWDER: (
        "For each burned area: the region's share of body surface for the patient's age "
        "band, from Lund and Browder's chart, multiplied by the fraction of that region "
        "involved. Superficial epidermal injury is excluded. Contributions are summed."
    ),
    RULE_OF_NINES: (
        "For each burned area: the adult percentage of the Rule of Nines block the region "
        "belongs to, apportioned by the region's share of that block, multiplied by the "
        "fraction involved. Superficial epidermal injury is excluded. Contributions are "
        "summed. Adults only."
    ),
    PALM: (
        f"The patient's own palm with fingers together is taken as {burns.PALM_PERCENT}% "
        "of their body surface. The total is the number of palms the burned area covers. "
        "For scattered small burns, and always a clinician-reviewed estimate."
    ),
}


def _nines_percent(region: burns.Region) -> float:
    """The region's share of body surface under the Rule of Nines.

    The Rule of Nines costs whole blocks — a whole arm is 9%. A region inside a block gets
    the block's percentage apportioned by its share of that block under the adult
    Lund-Browder chart, so selecting a forearm does not cost a whole arm.
    """
    block_total = sum(
        other.share("adult")
        for other in burns.REGIONS
        if other.nines_group == region.nines_group
    )
    if block_total <= 0:
        return 0.0
    return round(burns.NINES[region.nines_group] * region.share("adult") / block_total, 4)


def estimate(
    involvements: list[Involvement],
    *,
    method: str = LUND_BROWDER,
    age_years: float | None = None,
) -> Estimate:
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    if method == PALM:
        raise ValueError("the palm method takes a palm count; call estimate_by_palms")

    band = burns.band_for_age(age_years)
    result = Estimate(method=method, age_years=age_years, age_band=band, total_percent=0.0,
                      excluded_percent=0.0)

    if method == RULE_OF_NINES and burns.is_child(age_years):
        raise WrongChart(
            f"the Rule of Nines uses adult proportions and this patient is {age_years:g}. "
            "A child's head is a far larger share of the body surface and the legs a "
            "smaller one, so the adult chart would understate a head burn by more than "
            "half. Use Lund-Browder."
        )
    if method == RULE_OF_NINES and age_years is None:
        result.assumptions.append(
            "the patient's age was not supplied and the adult Rule of Nines was applied; "
            "if this patient is under 15 the estimate is wrong and Lund-Browder should be "
            "used instead"
        )
    if method == LUND_BROWDER and age_years is None:
        result.assumptions.append(
            "the patient's age was not supplied, so the adult column of the Lund-Browder "
            "chart was used"
        )

    seen: dict[str, Involvement] = {}
    for item in involvements:
        # The same region selected twice would double-count it. The deeper of the two is
        # kept, because a region recorded as both partial and full thickness is one burn
        # described twice and the worse description is the safer one to cost.
        existing = seen.get(item.region_code)
        if existing is None or _severity(item.depth) > _severity(existing.depth):
            if existing is not None:
                result.warnings.append(
                    f"{burns.REGION_BY_CODE[item.region_code].label} was selected more "
                    "than once; the deepest entry was costed and the others ignored"
                )
            seen[item.region_code] = item
        elif existing is not None:
            result.warnings.append(
                f"{burns.REGION_BY_CODE[item.region_code].label} was selected more than "
                "once; the deepest entry was costed and the others ignored"
            )

    for item in sorted(seen.values(), key=lambda entry: entry.region_code):
        region = burns.REGION_BY_CODE[item.region_code]
        depth = burns.DEPTH_BY_CODE[item.depth]
        percent = region.share(band) if method == LUND_BROWDER else _nines_percent(region)
        contribution = round(percent * item.fraction, 4)
        counted = depth.counts_towards_tbsa
        result.contributions.append(
            Contribution(
                region_code=region.code,
                region_label=region.label,
                depth=depth.code,
                depth_label=depth.label,
                fraction=item.fraction,
                region_percent=percent,
                contribution=contribution if counted else 0.0,
                counted=counted,
                reason=(
                    "counted"
                    if counted
                    else "superficial epidermal injury is excluded from every published "
                    "surface area method"
                ),
            )
        )
        if counted:
            result.total_percent += contribution
        else:
            result.excluded_percent += contribution
        if depth.code == burns.DEPTH_UNCERTAIN:
            result.provisional = True

    result.total_percent = round(result.total_percent, 2)
    result.excluded_percent = round(result.excluded_percent, 2)

    if result.provisional:
        result.warnings.append(
            "at least one area has no decided depth. It is counted so the total is not "
            "optimistic, and the estimate stays provisional until a clinician assesses it"
        )
    if result.total_percent > 100:
        result.warnings.append(
            "the contributions sum to more than 100% of the body surface, which cannot be "
            "right; check the selected regions and fractions"
        )
    return result


def estimate_by_palms(palms: float, *, age_years: float | None = None) -> Estimate:
    """The palm method, for burns too scattered to chart region by region."""
    if palms < 0:
        raise ValueError("a palm count cannot be negative")
    result = Estimate(
        method=PALM,
        age_years=age_years,
        age_band=burns.band_for_age(age_years),
        total_percent=round(palms * burns.PALM_PERCENT, 2),
        excluded_percent=0.0,
        palms=palms,
        assumptions=[
            (
                "the patient's palm with fingers together is taken as "
                f"{burns.PALM_PERCENT}% of their body surface; published figures range "
                "from 0.8% to 1.0%"
            ),
            (
                "only areas a clinician judged partial-thickness or deeper should have "
                "been counted in the palm total"
            ),
        ],
    )
    if palms > PALM_SENSIBLE_LIMIT:
        result.warnings.append(
            f"{palms:g} palms is about {result.total_percent:g}% of the body surface. "
            "Past roughly 15 palms the counting error exceeds the charting error; use "
            "Lund-Browder instead"
        )
    return result


_SEVERITY_ORDER = (
    burns.SUPERFICIAL_EPIDERMAL,
    burns.SUPERFICIAL_PARTIAL,
    burns.DEEP_PARTIAL,
    burns.DEPTH_UNCERTAIN,
    burns.FULL_THICKNESS,
)


def _severity(depth: str) -> int:
    """Rank for deduplication. Uncertain sits high so it is not discarded for a shallower
    entry while the assessment is still open."""
    return _SEVERITY_ORDER.index(depth) if depth in _SEVERITY_ORDER else 0


def compare(involvements: list[Involvement], *, age_years: float | None = None) -> dict:
    """Both charts side by side, where both apply.

    Offered because the two methods disagree, sometimes by several percent, and a
    clinician deciding a resuscitation volume should see the disagreement rather than
    whichever number the interface happened to show.
    """
    out: dict[str, dict | str] = {
        LUND_BROWDER: estimate(involvements, method=LUND_BROWDER, age_years=age_years).as_dict()
    }
    try:
        out[RULE_OF_NINES] = estimate(
            involvements, method=RULE_OF_NINES, age_years=age_years
        ).as_dict()
    except WrongChart as exc:
        out[RULE_OF_NINES] = str(exc)
    return out
