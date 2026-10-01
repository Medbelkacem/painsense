"""The surface area engine and the review flags.

A resuscitation volume is derived from a TBSA figure, so these tests check the arithmetic
against the published charts rather than against whatever the code currently returns.
"""

import pytest

from backend.burns import alerts, tbsa
from database.models import AlertSeverity
from knowledge import burns


def involve(code, depth=burns.DEEP_PARTIAL, fraction=1.0):
    return tbsa.Involvement(code, depth, fraction)


# --- the charts themselves ---------------------------------------------------------------


@pytest.mark.parametrize("band", [name for _low, _high, name in burns.AGE_BANDS])
def test_every_lund_browder_column_totals_one_hundred(band):
    assert burns.total_for_band(band) == 100.0


def test_rule_of_nines_blocks_total_one_hundred():
    assert sum(burns.NINES.values()) == 100.0


@pytest.mark.parametrize(
    ("age", "band"),
    [
        (0, "infant"),
        (0.5, "infant"),
        (0.92, "infant"),
        (0.999, "infant"),
        (1, "young_child"),
        (4.99, "young_child"),
        (5, "child"),
        (9.99, "child"),
        (10, "older_child"),
        (14.99, "older_child"),
        (15, "adolescent"),
        (17.99, "adolescent"),
        (18, "adult"),
        (85, "adult"),
        (None, "adult"),
    ],
)
def test_age_bands_cover_fractional_years(age, band):
    """Regression guard: an eleven-month-old once fell through every band to the adult
    chart, which would have costed their head burn at 7% instead of 19%."""
    assert burns.band_for_age(age) == band


def test_negative_age_is_refused_rather_than_banded():
    with pytest.raises(ValueError):
        burns.band_for_age(-1)


def test_the_head_shrinks_and_the_legs_grow_with_age():
    head = burns.REGION_BY_CODE["HEAD"]
    thigh = burns.REGION_BY_CODE["THIGH_LEFT"]
    assert head.share("infant") == 19.0
    assert head.share("adult") == 7.0
    assert thigh.share("infant") < thigh.share("adult")


# --- totals -------------------------------------------------------------------------------


@pytest.mark.parametrize("age", [0, 3, 8, 12, 16, 40])
def test_a_whole_body_burn_is_one_hundred_percent_at_every_age(age):
    every = [involve(region.code) for region in burns.REGIONS]
    assert tbsa.estimate(every, age_years=age).total_percent == 100.0


def test_whole_body_under_rule_of_nines_is_one_hundred_percent():
    every = [involve(region.code) for region in burns.REGIONS]
    result = tbsa.estimate(every, method=tbsa.RULE_OF_NINES, age_years=40)
    assert result.total_percent == 100.0


def test_an_infant_head_burn_is_costed_at_nineteen_percent():
    assert tbsa.estimate([involve("HEAD")], age_years=0.5).total_percent == 19.0


def test_the_same_burn_on_an_adult_is_seven_percent():
    assert tbsa.estimate([involve("HEAD")], age_years=40).total_percent == 7.0


def test_a_partial_region_contributes_proportionally():
    whole = tbsa.estimate([involve("TRUNK_ANTERIOR")], age_years=40).total_percent
    half = tbsa.estimate([involve("TRUNK_ANTERIOR", fraction=0.5)], age_years=40).total_percent
    assert half == pytest.approx(whole / 2)


def test_rule_of_nines_apportions_within_a_block():
    """Selecting a forearm must not cost a whole arm."""
    forearm = tbsa.estimate(
        [involve("FOREARM_LEFT")], method=tbsa.RULE_OF_NINES, age_years=40
    ).total_percent
    assert 0 < forearm < burns.NINES["ARM_LEFT"]

    whole_arm = tbsa.estimate(
        [involve("UPPER_ARM_LEFT"), involve("FOREARM_LEFT"), involve("HAND_LEFT")],
        method=tbsa.RULE_OF_NINES,
        age_years=40,
    )
    assert whole_arm.total_percent == pytest.approx(9.0, abs=0.01)


# --- the two refusals -----------------------------------------------------------------------


@pytest.mark.parametrize("age", [0, 2, 7, 14.9])
def test_the_adult_chart_is_refused_for_a_child(age):
    with pytest.raises(tbsa.WrongChart):
        tbsa.estimate([involve("HEAD")], method=tbsa.RULE_OF_NINES, age_years=age)


def test_the_adult_chart_is_allowed_from_fifteen():
    assert tbsa.estimate(
        [involve("HEAD")], method=tbsa.RULE_OF_NINES, age_years=15
    ).total_percent > 0


def test_an_unknown_age_with_the_adult_chart_records_the_assumption():
    result = tbsa.estimate([involve("HEAD")], method=tbsa.RULE_OF_NINES)
    assert any("under 15" in note for note in result.assumptions)


def test_superficial_epidermal_injury_is_excluded_from_the_total():
    result = tbsa.estimate(
        [involve("TRUNK_ANTERIOR", burns.SUPERFICIAL_EPIDERMAL)], age_years=40
    )
    assert result.total_percent == 0.0
    assert result.excluded_percent == 13.0
    assert result.contributions[0].counted is False


def test_excluded_area_is_still_reported():
    """Silently dropping it would make an erythema-only assessment look like no burn."""
    result = tbsa.estimate(
        [
            involve("TRUNK_ANTERIOR", burns.SUPERFICIAL_EPIDERMAL),
            involve("FOREARM_LEFT", burns.DEEP_PARTIAL),
        ],
        age_years=40,
    )
    assert result.total_percent == 3.0
    assert result.excluded_percent == 13.0


# --- provisional and duplicate handling --------------------------------------------------------


def test_an_undecided_depth_is_counted_and_marks_the_estimate_provisional():
    result = tbsa.estimate([involve("TRUNK_ANTERIOR", burns.DEPTH_UNCERTAIN)], age_years=40)
    assert result.total_percent == 13.0
    assert result.provisional is True
    assert any("provisional" in warning for warning in result.warnings)


def test_a_region_selected_twice_is_counted_once_at_the_deeper_entry():
    result = tbsa.estimate(
        [
            involve("FOREARM_LEFT", burns.SUPERFICIAL_PARTIAL),
            involve("FOREARM_LEFT", burns.FULL_THICKNESS),
        ],
        age_years=40,
    )
    assert result.total_percent == 3.0
    assert len(result.contributions) == 1
    assert result.contributions[0].depth == burns.FULL_THICKNESS
    assert result.warnings


def test_an_unknown_region_is_refused():
    with pytest.raises(tbsa.UnknownRegion):
        tbsa.Involvement("LEFT_WING", burns.DEEP_PARTIAL)


def test_a_fraction_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError):
        tbsa.Involvement("HEAD", burns.DEEP_PARTIAL, 1.5)


# --- palm method ---------------------------------------------------------------------------


def test_the_palm_method_counts_one_percent_per_palm():
    assert tbsa.estimate_by_palms(3).total_percent == 3.0


def test_the_palm_method_states_what_it_assumed():
    result = tbsa.estimate_by_palms(2)
    assert any("0.8% to 1.0%" in note for note in result.assumptions)


def test_too_many_palms_warns_to_use_a_chart():
    assert tbsa.estimate_by_palms(25).warnings


def test_comparing_methods_explains_why_one_does_not_apply():
    out = tbsa.compare([involve("HEAD")], age_years=3)
    assert isinstance(out[tbsa.LUND_BROWDER], dict)
    assert isinstance(out[tbsa.RULE_OF_NINES], str)
    assert "Lund-Browder" in out[tbsa.RULE_OF_NINES]


def test_an_estimate_carries_its_formula():
    assert tbsa.estimate([involve("HEAD")], age_years=40).as_dict()["formula"]


# --- alerts ----------------------------------------------------------------------------------


def _regions(*entries):
    return [
        {"region_code": code, "depth": depth, "circumferential": circ}
        for code, depth, circ in entries
    ]


def test_a_small_superficial_adult_burn_raises_nothing():
    found = alerts.evaluate(
        regions=_regions(("FOREARM_LEFT", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=3.0,
        age_years=40,
        cause="SCALD",
    )
    assert found == []


def test_the_extent_threshold_is_lower_for_a_child():
    child = alerts.evaluate(
        regions=_regions(("TRUNK_ANTERIOR", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=6.0,
        age_years=4,
        cause="SCALD",
    )
    adult = alerts.evaluate(
        regions=_regions(("TRUNK_ANTERIOR", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=6.0,
        age_years=40,
        cause="SCALD",
    )
    assert any(item.code == "EXTENT" for item in child)
    assert not any(item.code == "EXTENT" for item in adult)


def test_the_extent_threshold_is_lower_for_an_older_adult():
    found = alerts.evaluate(
        regions=_regions(("TRUNK_ANTERIOR", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=6.0,
        age_years=72,
        cause="SCALD",
    )
    assert any(item.code == "EXTENT" for item in found)


@pytest.mark.parametrize("region", sorted(burns.HIGH_RISK_REGIONS))
def test_every_high_risk_site_raises_a_flag_however_small(region):
    found = alerts.evaluate(
        regions=_regions((region, burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=0.5,
        age_years=40,
        cause="SCALD",
    )
    site = next(item for item in found if item.code == "HIGH_RISK_SITE")
    assert site.severity is AlertSeverity.URGENT_REVIEW


def test_a_full_thickness_burn_raises_an_urgent_depth_flag():
    found = alerts.evaluate(
        regions=_regions(("TRUNK_ANTERIOR", burns.FULL_THICKNESS, False)),
        total_percent=5.0,
        age_years=40,
        cause="FLAME",
    )
    depth = next(item for item in found if item.code == "DEPTH")
    assert depth.severity is AlertSeverity.URGENT_REVIEW


def test_a_circumferential_burn_is_flagged():
    found = alerts.evaluate(
        regions=_regions(("FOREARM_LEFT", burns.DEEP_PARTIAL, True)),
        total_percent=3.0,
        age_years=40,
        cause="SCALD",
    )
    assert any(item.code == "CIRCUMFERENTIAL" for item in found)


@pytest.mark.parametrize("cause", ["ELECTRICAL", "CHEMICAL"])
def test_deceptive_causes_are_flagged_whatever_the_area(cause):
    found = alerts.evaluate(
        regions=_regions(("FOREARM_LEFT", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=1.0,
        age_years=40,
        cause=cause,
    )
    assert any(item.code == "CAUSE" for item in found)


def test_airway_features_are_flagged_as_a_prompt_not_a_finding():
    found = alerts.evaluate(
        regions=_regions(("HEAD", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=4.0,
        age_years=40,
        cause="FLAME",
        enclosed_space=True,
        airway_symptoms=["hoarse voice"],
    )
    airway = next(item for item in found if item.code == "AIRWAY")
    assert "not a finding" in airway.message


def test_an_incomplete_assessment_says_so():
    found = alerts.evaluate(
        regions=_regions(("FOREARM_LEFT", burns.DEPTH_UNCERTAIN, False)),
        total_percent=3.0,
        age_years=None,
        cause="SCALD",
        provisional=True,
    )
    codes = {item.code for item in found}
    assert "DEPTH_UNDECIDED" in codes
    assert "AGE_UNKNOWN" in codes


def test_no_rule_ever_clears_a_patient():
    """Absence of a flag is not a clinical opinion, so nothing may assert one."""
    found = alerts.evaluate(
        regions=_regions(("FOREARM_LEFT", burns.SUPERFICIAL_PARTIAL, False)),
        total_percent=1.0,
        age_years=40,
        cause="SCALD",
    )
    assert all("no concern" not in item.message.casefold() for item in found)
