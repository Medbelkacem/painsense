from knowledge import causes, questions, rules
from knowledge.context import ClinicalContext, Criteria


def chest_case(**overrides) -> ClinicalContext:
    values = {
        "age": 58,
        "sex": "M",
        "pain_locations": frozenset({"CHEST_CENTRAL"}),
        "qualities": frozenset({"PRESSURE"}),
        "radiates": True,
    }
    values.update(overrides)
    return ClinicalContext(**values)


def test_a_missing_value_cannot_satisfy_a_threshold():
    assert not Criteria(vitals=(("hr", "gt", 100.0),)).matches(chest_case())
    assert not Criteria(min_age=40).matches(chest_case(age=None))


def test_criteria_combine_as_any_within_a_field_and_all_across_fields():
    ctx = chest_case(symptoms=frozenset({"FEVER"}))
    assert Criteria(symptoms=("FEVER", "CHILLS")).matches(ctx)
    assert not Criteria(symptoms=("FEVER",), regions=("ABDOMEN",)).matches(ctx)
    assert not Criteria(all_symptoms=("FEVER", "CHILLS")).matches(ctx)


def test_the_question_set_follows_the_site():
    chest = {question.code for question in questions.applicable(chest_case())}
    back = {
        question.code
        for question in questions.applicable(
            chest_case(pain_locations=frozenset({"BACK_LUMBAR"}))
        )
    }
    assert "CHEST_EXERTIONAL" in chest and "CHEST_EXERTIONAL" not in back
    assert "BACK_STRAIGHT_LEG_RAISE" in back and "BACK_STRAIGHT_LEG_RAISE" not in chest


def test_pregnancy_is_asked_only_where_it_applies():
    abdominal = {"pain_locations": frozenset({"ABD_RLQ"})}
    woman = {
        question.code
        for question in questions.applicable(chest_case(sex="F", age=28, **abdominal))
    }
    man = {
        question.code
        for question in questions.applicable(chest_case(sex="M", age=28, **abdominal))
    }
    older = {
        question.code
        for question in questions.applicable(chest_case(sex="F", age=70, **abdominal))
    }
    assert "ABD_PREGNANCY_STATUS" in woman
    assert "ABD_PREGNANCY_STATUS" not in man
    assert "ABD_PREGNANCY_STATUS" not in older


def test_a_follow_up_appears_once_its_question_is_answered():
    ctx = chest_case()
    assert "CHEST_RELIEVED_BY_REST" not in {q.code for q in questions.applicable(ctx)}
    ctx.answers["CHEST_EXERTIONAL"] = True
    assert "CHEST_RELIEVED_BY_REST" in {q.code for q in questions.applicable(ctx)}


def test_every_question_declares_options_when_it_needs_them():
    for question in questions.QUESTIONS:
        assert question.kind in questions.KINDS
        if question.kind in ("SINGLE", "MULTI"):
            assert question.options, f"{question.code} offers no options"
        if question.kind == "NUMBER":
            assert question.unit, f"{question.code} has no unit"


def test_every_answer_a_rule_or_cause_reads_is_a_real_question():
    known = set(questions.BY_CODE)
    referenced = set()
    for rule in rules.RED_FLAGS:
        referenced.update(code for code, _ in rule.criteria.answer_equals)
    for cause in causes.CAUSES:
        for signal in cause.signals:
            referenced.update(code for code, _ in signal.criteria.answer_equals)
            referenced.update(code for code, _ in signal.criteria.answer_at_least)
            referenced.update(code for code, _ in signal.criteria.answer_at_most)
    assert referenced <= known, f"unknown question codes: {sorted(referenced - known)}"


def test_the_ischaemic_pattern_leads_on_an_exertional_presentation():
    ctx = chest_case(
        conditions=frozenset({"CAD"}),
        symptoms=frozenset({"SWEATING"}),
        answers={
            "CHEST_EXERTIONAL": True,
            "CHEST_RELIEVED_BY_REST": True,
            "CHEST_RADIATION_SITE": ["LEFT_ARM"],
        },
    )
    top = causes.candidates(ctx)[0]
    assert top.cause.code == "ISCHAEMIC_CHEST_PATTERN"
    assert "Brought on by exertion" in top.matched
    assert "Raised troponin" in top.missing


def test_a_cause_reports_what_is_missing_as_well_as_what_matched():
    for match in causes.candidates(chest_case()):
        assert len(match.matched) + len(match.missing) == len(match.cause.signals)


def test_bands_follow_the_configured_table():
    assert rules.band(0.0)[0] == "NONE"
    assert rules.band(2.4)[0] == "MILD"
    assert rules.band(5.0)[0] == "MODERATE"
    assert rules.band(8.2)[0] == "SEVERE"
    assert rules.band(10.0)[0] == "EXTREME"


def test_a_low_saturation_raises_a_high_severity_alert():
    alerts = rules.evaluate(chest_case(vitals={"spo2": 88.0}))
    assert any(alert.code == "SPO2_LOW" and alert.severity == rules.HIGH for alert in alerts)


def test_recorded_context_is_attached_to_a_vitals_alert():
    ctx = chest_case(vitals={"hr": 118.0}, confounders=frozenset({"ANXIETY"}))
    alert = next(alert for alert in rules.evaluate(ctx) if alert.code == "MODERATE_TACHYCARDIA")
    assert "Anxiety" in alert.context_notes


def test_an_alert_without_that_context_carries_no_note():
    alert = next(
        alert
        for alert in rules.evaluate(chest_case(vitals={"hr": 118.0}))
        if alert.code == "MODERATE_TACHYCARDIA"
    )
    assert alert.context_notes == []


def test_the_priority_indicator_lists_what_it_is_made_of():
    ctx = chest_case(vitals={"spo2": 88.0}, conditions=frozenset({"CAD", "DIABETES_T2"}))
    alerts = rules.evaluate(ctx)
    priority = rules.priority(ctx, 7.0, alerts)
    assert 0 <= priority.score <= 10
    assert abs(sum(factor.points for factor in priority.factors) - priority.score) < 0.05
    assert any("Estimated pain" in factor.label for factor in priority.factors)


def test_the_priority_indicator_is_capped_at_ten():
    ctx = chest_case(
        age=90,
        symptoms=frozenset({"SYNCOPE", "FOCAL_DEFICIT", "BLEEDING"}),
        conditions=frozenset({"CAD", "CANCER_ACTIVE", "DIABETES_T2", "NEUROPATHY"}),
        vitals={
            "spo2": 84.0,
            "sbp": 78.0,
            "hr": 140.0,
            "resp_rate": 34.0,
            "temperature_c": 34.0,
        },
    )
    assert rules.priority(ctx, 10.0, rules.evaluate(ctx)).score == 10.0


def test_a_record_with_nothing_in_it_triggers_nothing():
    assert rules.evaluate(ClinicalContext()) == []
    assert rules.priority(ClinicalContext(), None, []).score == 0.0
