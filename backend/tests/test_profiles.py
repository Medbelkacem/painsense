from datetime import date, datetime, timedelta, timezone

import pytest

from backend.ai import confounders, metrics, population, quality, trajectory
from knowledge import profiles, reference_ranges, rules, scales
from knowledge.context import ClinicalContext
from backend.tests.test_api import CHEST_CASE, make_patient


def context(**overrides) -> ClinicalContext:
    values = {
        "pain_locations": frozenset({"CHEST_CENTRAL"}),
        "qualities": frozenset({"PRESSURE"}),
        "symptoms": frozenset({"SWEATING"}),
        "duration_hours": 3.0,
        "onset": "SUDDEN",
        "pattern": "CONSTANT",
        "course": "STABLE",
        "radiates": False,
    }
    values.update(overrides)
    return ClinicalContext(**values)


# --- the bands ---------------------------------------------------------------


def test_age_picks_the_band_and_the_newborn_one_is_not_the_adult_one():
    newborn = reference_ranges.band_for_age(0.02)
    adult = reference_ranges.band_for_age(40)
    assert newborn.code == "NEONATE"
    assert adult.code == reference_ranges.ADULT
    assert newborn.normal["hr"] != adult.normal["hr"]


def test_every_band_is_reachable_from_some_age():
    reached = {
        reference_ranges.band_for_age(age).code for age in (0.0, 0.5, 2, 5, 9, 15, 40, 90)
    }
    assert reached == {band.code for band in reference_ranges.BANDS}


def test_an_input_field_accepts_the_widest_band_not_the_adult_one():
    widest = reference_ranges.widest_plausible()
    neonatal = reference_ranges.BY_CODE["NEONATE"].plausible["resp_rate"]
    assert widest["resp_rate"][1] >= neonatal[1]


def test_a_band_without_a_blood_pressure_range_simply_does_not_check_one():
    # Paediatric blood pressure is defined on age, sex and height centiles, so no band is
    # stated. The platform must leave it unchecked rather than borrow the adult one.
    for code in ("NEONATE", "INFANT", "TODDLER", "YOUNG_CHILD"):
        assert "sbp" not in reference_ranges.BY_CODE[code].normal


def test_a_newborn_heart_rate_is_normal_and_the_same_rate_in_an_adult_is_not():
    vitals = {"hr": 150.0, "resp_rate": 45.0}
    assert rules.deranged_for(context(age=0.02, vitals=vitals)) == []
    assert set(rules.deranged_for(context(age=40, vitals=vitals))) == {"hr", "resp_rate"}


def test_pregnancy_shifts_the_heart_rate_band_by_trimester():
    first = profiles.normal_ranges(context(age=30, profile="PREGNANT", pregnancy_trimester=1))
    third = profiles.normal_ranges(context(age=30, profile="PREGNANT", pregnancy_trimester=3))
    assert third["hr"][0] > first["hr"][0]


def test_an_unknown_trimester_shifts_nothing_rather_than_assuming_one():
    plain = profiles.normal_ranges(context(age=30, profile="PREGNANT"))
    assert plain["hr"] == reference_ranges.ADULT_BAND.normal["hr"]


def test_a_newborn_pulse_an_adult_could_not_have_is_blocked_as_implausible():
    report = quality.assess(context(age=0.02, vitals={"hr": 40.0}))
    assert any("plausible range for newborn" in issue for issue in report.blocking)


# --- the profiles ------------------------------------------------------------


def test_age_resolves_to_a_primary_profile_without_a_recorded_one():
    assert profiles.primary_for_age(0.01).code == profiles.NEWBORN
    assert profiles.primary_for_age(1.5).code == profiles.INFANT_TODDLER
    assert profiles.primary_for_age(5).code == profiles.CHILD
    assert profiles.primary_for_age(14).code == profiles.ADOLESCENT
    assert profiles.primary_for_age(40).code == profiles.ADULT
    assert profiles.primary_for_age(80).code == profiles.OLDER_ADULT


def test_a_state_profile_is_never_chosen_by_age_alone():
    chosen = {profiles.primary_for_age(age).code for age in range(100)}
    assert not chosen & profiles.NOT_CHOSEN_BY_AGE


def test_a_recorded_profile_beats_age():
    reading = population.read(context(age=40, profile=profiles.CRITICAL_CARE))
    assert reading.primary == profiles.CRITICAL_CARE
    assert reading.can_self_report is False


def test_every_profile_names_a_scale_that_exists():
    for profile in profiles.PRIMARY_PROFILES:
        assert profile.reference_scale in scales.BY_CODE
        for code in profile.alternative_scales:
            assert code in scales.BY_CODE


def test_a_profile_that_cannot_self_report_is_given_an_observational_scale():
    for profile in profiles.PRIMARY_PROFILES:
        if not profile.can_self_report:
            assert profile.reference_is_observational, profile.code


def test_every_profile_confounder_exists_in_the_knowledge_base():
    from knowledge import confounders as confounder_kb

    for profile in profiles.PROFILES:
        for code in profile.confounders:
            assert code in confounder_kb.BY_CODE, f"{profile.code}: {code}"


def test_modifiers_stack_on_the_primary_profile_and_the_penalty_is_capped():
    ctx = context(
        age=60,
        profile=profiles.CRITICAL_CARE,
        profile_modifiers=frozenset(
            {profiles.SIGNAL_ALTERING_MEDICATION, profiles.FEBRILE, profiles.CHRONIC_PAIN}
        ),
    )
    applicable = profiles.applicable_to(ctx)
    assert len(applicable) == 4
    assert profiles.confidence_penalty(applicable) == profiles.MAX_CONFIDENCE_PENALTY


def test_a_modifier_cannot_be_recorded_as_the_primary_profile():
    assert profiles.resolve(profiles.FEBRILE, age=40).code == profiles.ADULT


# --- the reference scales ----------------------------------------------------


def test_an_observational_total_is_summed_from_its_items_and_clamped():
    items = {
        "FACIAL_EXPRESSION": 1,
        "CRY": 2,
        "BREATHING": 1,
        "ARMS": 1,
        "LEGS": 1,
        "AROUSAL": 1,
    }
    assert scales.total(scales.NIPS, items) == 7.0
    # An item scored above its own maximum is held at that maximum, not added as given.
    assert scales.total(scales.NIPS, {**items, "CRY": 9}) == 7.0


def test_an_unscored_item_counts_as_its_lowest_value_and_is_reported_as_unscored():
    assert scales.total(scales.FLACC, {"FACE": 2}) == 2.0
    assert set(scales.unscored_items(scales.FLACC, {"FACE": 2})) == {
        "LEGS",
        "ACTIVITY",
        "CRY",
        "CONSOLABILITY",
    }


@pytest.mark.parametrize(
    ("code", "raw", "expected"),
    [
        (scales.NRS, 7.0, 7.0),
        (scales.NIPS, 7.0, 10.0),
        (scales.NIPS, 0.0, 0.0),
        (scales.CPOT, 4.0, 5.0),
        # BPS starts at 3, so its lowest total is no pain rather than three tenths of it.
        (scales.BPS, 3.0, 0.0),
        (scales.BPS, 12.0, 10.0),
    ],
)
def test_a_raw_score_projects_onto_the_shared_axis(code, raw, expected):
    assert scales.normalise(code, raw) == expected


def test_the_projection_never_leaves_the_axis():
    for scale in scales.SCALES:
        for raw in (-5.0, scale.minimum, scale.maximum, scale.maximum + 50):
            assert 0.0 <= scales.normalise(scale.code, raw) <= 10.0


def test_a_scale_scored_from_items_lists_items_that_sum_to_its_range():
    for scale in scales.SCALES:
        if scale.items:
            assert scale.item_total_range == (scale.minimum, scale.maximum), scale.code


# --- the features ------------------------------------------------------------


def test_a_relative_change_stays_missing_without_a_baseline():
    assert context(age=40, vitals={"hr": 110.0}).relative_change("hr") is None
    with_baseline = context(age=40, vitals={"hr": 110.0}, baseline_vitals={"hr": 70.0})
    assert round(with_baseline.relative_change("hr"), 3) == 0.571


def test_fever_accounts_for_part_of_a_raised_heart_rate():
    allowance = reference_ranges.fever_heart_rate_allowance(39.0)
    assert allowance == 2 * reference_ranges.FEVER_HR_PER_DEGREE
    assert reference_ranges.fever_heart_rate_allowance(36.5) == 0.0
    assert reference_ranges.fever_heart_rate_allowance(None) == 0.0


# --- confounders -------------------------------------------------------------


def test_a_profile_raises_its_confounders_without_claiming_they_were_recorded():
    analysis = confounders.analyse(
        context(age=0.02, profile=profiles.NEWBORN, vitals={"hr": 150.0})
    )
    codes = {note.code: note.source for note in analysis.notes}
    assert codes["HUNGER"] == confounders.FROM_PROFILE
    assert analysis.recorded == []


def test_a_recorded_confounder_is_told_apart_from_one_the_profile_raised():
    analysis = confounders.analyse(
        context(
            age=0.02,
            profile=profiles.NEWBORN,
            confounders=frozenset({"HANDLING"}),
            vitals={"hr": 150.0},
        )
    )
    sources = {note.code: note.source for note in analysis.notes}
    assert sources["HANDLING"] == confounders.RECORDED
    assert sources["HUNGER"] == confounders.FROM_PROFILE


def test_the_profile_penalty_widens_the_interval_and_is_reported_on_its_own():
    analysis = confounders.analyse(context(age=60, profile=profiles.CRITICAL_CARE))
    assert analysis.profile_widening > 0
    assert analysis.widening >= analysis.profile_widening


# --- the temporal analysis ---------------------------------------------------


def test_phases_split_the_brief_s_own_example_into_a_rise_and_a_fall():
    found = trajectory.phases([0.0, 2.0, 5.0, 8.0, 6.0, 3.0])
    assert [phase.direction for phase in found] == [trajectory.RISING, trajectory.FALLING]


def test_a_flat_series_is_one_plateau():
    found = trajectory.phases([4.0, 4.2, 3.9, 4.1])
    assert [phase.direction for phase in found] == [trajectory.PLATEAU]


def test_a_single_point_has_no_direction():
    assert trajectory.phases([5.0]) == []


def test_episodes_are_found_and_an_open_one_is_not_reported_as_resolved():
    resolved = trajectory.episodes([0.0, 5.0, 7.0, 1.0])
    assert len(resolved) == 1 and resolved[0].resolved and resolved[0].peak == 7.0

    open_now = trajectory.episodes([0.0, 5.0, 7.0])
    assert len(open_now) == 1 and not open_now[0].resolved


def test_two_separate_episodes_are_not_merged():
    found = trajectory.episodes([6.0, 1.0, 7.0])
    assert len(found) == 2


def test_a_calibration_beats_the_median_of_earlier_visits():
    earlier = [
        trajectory.EarlierAssessment(
            created_at=moment, estimated_pain=None, vitals={"hr": 95.0}
        )
        for moment in (date(2026, 1, 1), date(2026, 2, 1))
    ]
    comparison = trajectory.compare(earlier, 5.0, {"hr": 100.0}, baseline={"hr": 70.0})
    assert comparison.source == "CALIBRATION"
    assert comparison.vitals["hr"]["baseline"] == 70.0


# --- the metrics -------------------------------------------------------------


def test_an_estimate_that_always_under_reads_is_reported_as_missing_pain():
    truth = [8.0] * 10
    estimate = [3.0] * 10
    report = metrics.evaluate(truth, estimate)
    moderate = report.under_estimation[0]
    assert moderate.missed == 10 and moderate.miss_rate == 1.0
    assert report.bias < 0


def test_a_perfect_estimate_misses_nothing_and_has_no_bias():
    truth = [0.0, 3.0, 5.0, 8.0, 10.0]
    report = metrics.evaluate(truth, truth)
    assert report.mae == 0.0 and report.bias == 0.0
    assert all(entry.missed == 0 for entry in report.under_estimation)
    assert report.band_accuracy == 1.0


def test_the_confusion_matrix_is_square_over_the_bands_and_totals_the_sample():
    report = metrics.evaluate([0.0, 2.0, 5.0, 8.0, 10.0], [1.0, 3.0, 4.0, 9.0, 10.0])
    assert len(report.confusion) == len(metrics.BAND_ORDER)
    assert all(len(row) == len(metrics.BAND_ORDER) for row in report.confusion)
    assert sum(sum(row) for row in report.confusion) == report.n


def test_group_metrics_put_the_worst_served_population_first():
    truth = [8.0, 8.0, 8.0, 8.0]
    estimate = [8.0, 8.0, 2.0, 2.0]
    report = metrics.evaluate(
        truth, estimate, profiles=["ADULT", "ADULT", "NEWBORN", "NEWBORN"]
    )
    assert [row.key for row in report.by_profile] == ["NEWBORN", "ADULT"]
    assert report.by_profile[0].moderate_miss_rate == 1.0


# --- the whole flow ----------------------------------------------------------


def test_a_newborn_runs_through_profile_calibration_and_an_observational_reference(
    client, doctor_headers
):
    born = datetime.now(timezone.utc).date() - timedelta(days=12)
    patient = make_patient(
        client,
        doctor_headers,
        birth_date=born.isoformat(),
        profile_code=profiles.NEWBORN,
        condition_codes=[],
        medications=[],
    )

    calibration = client.put(
        f"/api/patients/{patient['id']}/calibration",
        headers=doctor_headers,
        json={
            "readings": 3,
            "minutes_at_rest": 10,
            "hr": 132,
            "resp_rate": 42,
            "spo2": 98,
            "temperature_c": 36.9,
        },
    )
    assert calibration.status_code == 200, calibration.text
    assert calibration.json()["hr"] == 132

    created = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={
            **CHEST_CASE,
            "patient_id": patient["id"],
            "profile_code": profiles.NEWBORN,
            "measurement": {"hr": 176, "resp_rate": 58, "spo2": 94, "temperature_c": 37.2},
            "self_report": {
                "scale_code": scales.NIPS,
                "items": {
                    "FACIAL_EXPRESSION": 1,
                    "CRY": 2,
                    "BREATHING": 1,
                    "ARMS": 1,
                    "LEGS": 1,
                    "AROUSAL": 1,
                },
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    report = body["self_report_detail"]
    assert report["scale_code"] == scales.NIPS
    assert report["raw_score"] == 7.0 and report["raw_max"] == 7.0
    assert report["observed"] is True
    assert report["nrs"] == 10.0

    estimate = client.post(
        f"/api/assessments/{body['id']}/predict", headers=doctor_headers, json={}
    )
    assert estimate.status_code in (200, 201), estimate.text
    prediction = estimate.json()["prediction"]

    reading = prediction["population"]
    assert reading["primary"] == profiles.NEWBORN
    assert reading["can_self_report"] is False
    assert reading["reference_scale"] == scales.NIPS
    assert reading["confidence_penalty"] > 0
    assert prediction["profile_penalty"] > 0

    # A rate of 176 is inside the newborn band, so it must not be reported as deranged.
    assert not any("Heart rate" in issue for issue in prediction["quality_issues"])


def test_the_profile_catalogue_offers_every_profile_scale_and_band(client, doctor_headers):
    body = client.get("/api/patient-profiles", headers=doctor_headers).json()
    assert {entry["code"] for entry in body["primary"]} == {
        profile.code for profile in profiles.PRIMARY_PROFILES
    }
    assert {entry["code"] for entry in body["modifiers"]} == {
        profile.code for profile in profiles.MODIFIER_PROFILES
    }
    assert {entry["code"] for entry in body["scales"]} == set(scales.BY_CODE)
    assert {entry["code"] for entry in body["bands"]} == set(reference_ranges.BY_CODE)
    assert "no diagnosis" in body["notice"] or "carries no diagnosis" in body["notice"]


def test_an_unknown_profile_is_refused(client, doctor_headers):
    patient = make_patient(client, doctor_headers)
    response = client.post(
        "/api/assessments",
        headers=doctor_headers,
        json={**CHEST_CASE, "patient_id": patient["id"], "profile_code": "NOT_A_PROFILE"},
    )
    assert response.status_code == 422
    assert "NOT_A_PROFILE" in str(response.json()["detail"])
