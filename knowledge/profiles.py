"""Patient profiles for populations whose signals do not mean the same thing.

A profile decides four things: which physiological band the recorded vitals are read
against, which scale is the reference the estimate is compared with, whether the patient
can be asked at all, and how much of the estimate's certainty has to be given back
because something in the picture is known to distort the signals.

Profiles come in two kinds. Exactly one PRIMARY profile applies, chosen from age and
care setting. Any number of MODIFIER profiles apply on top, because a pregnant patient in
critical care taking a beta blocker is an ordinary combination rather than a special case.

No profile carries a diagnosis or a treatment recommendation. A profile says what to
compare against and what to distrust, and nothing else.
"""

from dataclasses import dataclass

from knowledge import reference_ranges, scales

PRIMARY = "PRIMARY"
MODIFIER = "MODIFIER"

NEWBORN = "NEWBORN"
INFANT_TODDLER = "INFANT_TODDLER"
CHILD = "CHILD"
ADOLESCENT = "ADOLESCENT"
ADULT = "ADULT"
PREGNANT = "PREGNANT"
OLDER_ADULT = "OLDER_ADULT"
COGNITIVE_IMPAIRMENT = "COGNITIVE_IMPAIRMENT"
CRITICAL_CARE = "CRITICAL_CARE"

SIGNAL_ALTERING_MEDICATION = "SIGNAL_ALTERING_MEDICATION"
FEBRILE = "FEBRILE"
PHYSICALLY_ACTIVE = "PHYSICALLY_ACTIVE"
CHRONIC_PAIN = "CHRONIC_PAIN"


@dataclass(frozen=True)
class Profile:
    code: str
    label: str
    kind: str
    # Which reference_ranges band the vitals are read against. Modifiers leave this None
    # and keep whatever the primary profile chose.
    band: str | None = None
    min_age: float | None = None
    max_age: float | None = None
    can_self_report: bool = True
    # The scale this profile's estimate is compared against.
    reference_scale: str | None = None
    # Other scales a clinician may legitimately use for this profile instead.
    alternative_scales: tuple[str, ...] = ()
    # Signals the literature points at first for this population, among those the
    # platform records.
    priority_signals: tuple[str, ...] = ()
    # Signals the literature points at that this prototype does not measure. Named so the
    # gap is visible rather than quietly absent.
    signals_not_available: tuple[str, ...] = ()
    # Confounder codes always worth considering for this population, whether or not the
    # clinician ticked them.
    confounders: tuple[str, ...] = ()
    # Fraction of the interval width handed back because this profile distorts the
    # signals the estimate rests on. Summed across the applicable profiles and capped.
    confidence_penalty: float = 0.0
    requires_trimester: bool = False
    # Compare against this patient's own earlier readings rather than a population band.
    prefers_own_history: bool = False
    interpretation: str = ""
    note: str = ""

    @property
    def reference_is_observational(self) -> bool:
        if self.reference_scale is None:
            return False
        return scales.BY_CODE[self.reference_scale].observational


PROFILES = (
    Profile(
        NEWBORN,
        "Newborn, 0 to 1 month",
        PRIMARY,
        band=reference_ranges.BY_CODE["NEONATE"].code,
        min_age=0.0,
        max_age=1 / 12,
        can_self_report=False,
        reference_scale=scales.NIPS,
        alternative_scales=(scales.PIPP,),
        priority_signals=("hr", "resp_rate", "spo2", "facial expression", "cry acoustics"),
        signals_not_available=("limb movement",),
        confounders=("HUNGER", "FATIGUE", "HANDLING"),
        confidence_penalty=0.25,
        interpretation=(
            "Cannot be asked. The reference is an observational scale scored by the "
            "clinician. Resting heart rate is high for this age, so a rate that would be "
            "a tachycardia in an adult may be this newborn's baseline; the newborn band "
            "is what the reading is compared against."
        ),
        note=(
            "The behavioural signals this population is normally judged on are not "
            "measured by this prototype. They reach the record only through the "
            "observational scale, as the reference, never as a model input."
        ),
    ),
    Profile(
        INFANT_TODDLER,
        "Infant and young child, 1 month to 3 years",
        PRIMARY,
        # Spans the INFANT and TODDLER bands, so age picks between them.
        band=None,
        min_age=1 / 12,
        max_age=3.0,
        can_self_report=False,
        reference_scale=scales.FLACC,
        alternative_scales=(scales.NIPS,),
        priority_signals=(
            "hr",
            "resp_rate",
            "spo2",
            "temperature_c",
            "facial expression",
            "cry acoustics",
        ),
        signals_not_available=("consolability",),
        confounders=("HUNGER", "FATIGUE", "SEPARATION_DISTRESS"),
        confidence_penalty=0.2,
        interpretation=(
            "Cannot put a number on the pain. The reference is a behavioural scale. "
            "Crying, hunger and tiredness produce the same autonomic picture as pain at "
            "this age, which is the main reason a raised heart rate alone means little."
        ),
    ),
    Profile(
        CHILD,
        "Child, 3 to 7 years",
        PRIMARY,
        band=reference_ranges.BY_CODE["YOUNG_CHILD"].code,
        min_age=3.0,
        max_age=7.0,
        reference_scale=scales.FPS_R,
        alternative_scales=(scales.FLACC,),
        priority_signals=("hr", "resp_rate", "facial expression"),
        signals_not_available=(),
        confounders=("FEAR", "SEPARATION_DISTRESS"),
        confidence_penalty=0.1,
        interpretation=(
            "Can usually choose a face but not handle a number. The faces scale is a "
            "self-report and stays the reference; fear of the examination itself is the "
            "confounder to rule out first."
        ),
    ),
    Profile(
        ADOLESCENT,
        "Older child and adolescent, 7 to 18 years",
        PRIMARY,
        # Spans the OLDER_CHILD and ADOLESCENT bands, so age picks between them.
        band=None,
        min_age=7.0,
        max_age=18.0,
        reference_scale=scales.NRS,
        alternative_scales=(scales.FPS_R, scales.VAS),
        priority_signals=("hr", "resp_rate", "sbp"),
        confounders=("ANXIETY", "FEAR"),
        interpretation=(
            "A numerical rating is usually possible. The physiological band still differs "
            "from the adult one until the end of this range."
        ),
    ),
    Profile(
        ADULT,
        "Adult",
        PRIMARY,
        band=reference_ranges.ADULT,
        min_age=18.0,
        max_age=65.0,
        reference_scale=scales.NRS,
        alternative_scales=(scales.VAS,),
        priority_signals=("hr", "resp_rate", "sbp", "dbp", "spo2"),
        confounders=(),
        interpretation="Numerical rating 0-10, read against the adult band.",
    ),
    Profile(
        PREGNANT,
        "Pregnant patient",
        PRIMARY,
        band=reference_ranges.ADULT,
        reference_scale=scales.NRS,
        alternative_scales=(scales.VAS,),
        priority_signals=("hr", "sbp", "dbp", "resp_rate"),
        confounders=("ANXIETY",),
        confidence_penalty=0.1,
        requires_trimester=True,
        interpretation=(
            "Resting heart rate is physiologically higher and blood volume is increased, "
            "so the heart-rate band is shifted by trimester rather than taken from the "
            "general adult band. Pain that is expected, such as contractions in labour, "
            "has to be told apart from pain that is not; the platform records which of "
            "the two the clinician is looking at and reports the estimate in that light."
        ),
        note=(
            "No medication is suggested for this or any other profile. The platform "
            "produces an estimate and the reasons behind it, nothing more."
        ),
    ),
    Profile(
        OLDER_ADULT,
        "Older adult, 65 and over",
        PRIMARY,
        band=reference_ranges.ADULT,
        min_age=65.0,
        reference_scale=scales.NRS,
        alternative_scales=(scales.VAS, scales.PAINAD),
        priority_signals=("hr", "sbp", "resp_rate"),
        confounders=("BETA_BLOCKER", "SLEEP_DEPRIVATION"),
        confidence_penalty=0.1,
        interpretation=(
            "The cardiac response to pain is often blunted, and medication that holds the "
            "heart rate down is common, so an unremarkable heart rate is weak evidence "
            "against pain. Where cognition is impaired, the cognitive-impairment profile "
            "applies and the reference becomes an observational scale."
        ),
    ),
    Profile(
        COGNITIVE_IMPAIRMENT,
        "Cognitive impairment or dementia",
        PRIMARY,
        band=reference_ranges.ADULT,
        can_self_report=False,
        reference_scale=scales.PAINAD,
        priority_signals=("hr", "resp_rate", "sbp", "facial expression", "vocalisation"),
        signals_not_available=("body language",),
        confounders=("COMMUNICATION_BARRIER", "BETA_BLOCKER"),
        confidence_penalty=0.25,
        interpretation=(
            "Self-report is unreliable or impossible. The reference is an observational "
            "scale, and the behavioural items it rests on are scored by the clinician "
            "because this prototype does not observe them itself."
        ),
    ),
    Profile(
        CRITICAL_CARE,
        "Critical care, sedated or intubated",
        PRIMARY,
        band=reference_ranges.ADULT,
        can_self_report=False,
        reference_scale=scales.CPOT,
        alternative_scales=(scales.BPS,),
        priority_signals=("hr", "sbp", "resp_rate", "spo2", "facial expression"),
        signals_not_available=("muscle tension", "ventilator compliance"),
        confounders=("OPIOID_THERAPY", "SEDATION", "ANALGESIA_RECENT"),
        confidence_penalty=0.35,
        interpretation=(
            "Cannot be asked. Sedation and analgesia are the dominant confounders: both "
            "flatten the autonomic response the estimate reads, so an estimate here is "
            "weaker evidence than the same estimate on a conscious patient. The reference "
            "is CPOT, or BPS where the patient is ventilated and BPS is the unit's tool."
        ),
    ),
    Profile(
        SIGNAL_ALTERING_MEDICATION,
        "On medication that alters the recorded signals",
        MODIFIER,
        confounders=("BETA_BLOCKER", "OPIOID_THERAPY", "SEDATION"),
        confidence_penalty=0.2,
        interpretation=(
            "Beta blockers, opioids and sedatives change the signals the estimate rests "
            "on rather than the pain itself. The estimate is still produced, with less "
            "certainty, and the interface says which medication class is responsible."
        ),
    ),
    Profile(
        FEBRILE,
        "Fever or infection",
        MODIFIER,
        confounders=("FEVER_CONTEXT",),
        confidence_penalty=0.15,
        interpretation=(
            "Fever raises heart rate and respiratory rate on its own. The platform works "
            "out how much of a raised heart rate the recorded temperature would account "
            "for and reports the remainder, rather than reading the whole rise as pain."
        ),
    ),
    Profile(
        PHYSICALLY_ACTIVE,
        "Physical activity or exertion",
        MODIFIER,
        confounders=("RECENT_ACTIVITY",),
        confidence_penalty=0.15,
        interpretation=(
            "Exertion raises heart rate and respiratory rate for several minutes "
            "afterwards. Where activity is recorded, a raised rate is attributed to it "
            "before it is read as pain."
        ),
        note=(
            "The brief suggests an inertial sensor to rule exertion out. This prototype "
            "has no sensor, so activity in the last quarter hour is recorded by the "
            "clinician instead and used the same way."
        ),
    ),
    Profile(
        CHRONIC_PAIN,
        "Established chronic pain",
        MODIFIER,
        confounders=("SLEEP_DEPRIVATION", "OPIOID_THERAPY"),
        confidence_penalty=0.1,
        prefers_own_history=True,
        interpretation=(
            "The baseline is durably shifted, so a population band says little. The "
            "comparison is against this patient's own earlier readings, and the estimate "
            "is reported as a change from them rather than as a departure from a norm."
        ),
    ),
)

BY_CODE = {profile.code: profile for profile in PROFILES}
PRIMARY_PROFILES = tuple(p for p in PROFILES if p.kind == PRIMARY)
MODIFIER_PROFILES = tuple(p for p in PROFILES if p.kind == MODIFIER)

# Age alone never chooses these: they depend on a state the clinician records.
NOT_CHOSEN_BY_AGE = frozenset({PREGNANT, COGNITIVE_IMPAIRMENT, CRITICAL_CARE})

MAX_CONFIDENCE_PENALTY = 0.5


def primary_for_age(age: float | None) -> Profile:
    """The primary profile age on its own implies. Anything that depends on a recorded
    state has to be chosen by the clinician, so this never returns one of those."""
    if age is None:
        return BY_CODE[ADULT]
    for profile in PRIMARY_PROFILES:
        if profile.code in NOT_CHOSEN_BY_AGE:
            continue
        low = profile.min_age if profile.min_age is not None else float("-inf")
        high = profile.max_age if profile.max_age is not None else float("inf")
        if low <= age < high:
            return profile
    return BY_CODE[ADULT]


def resolve(
    primary_code: str | None, modifier_codes=(), *, age: float | None = None
) -> Profile:
    """The primary profile in force: the one recorded, or the one age implies."""
    if primary_code and primary_code in BY_CODE:
        candidate = BY_CODE[primary_code]
        if candidate.kind == PRIMARY:
            return candidate
    return primary_for_age(age)


def applicable(primary: Profile, modifier_codes=()) -> tuple[Profile, ...]:
    chosen = [primary]
    for code in sorted(set(modifier_codes)):
        profile = BY_CODE.get(code)
        if profile is not None and profile.kind == MODIFIER:
            chosen.append(profile)
    return tuple(chosen)


def band_for(primary: Profile, age: float | None = None) -> reference_ranges.Band:
    """The physiological band to read the vitals against. A profile that names a band
    wins over age, which is the point of recording a profile at all: a newborn in an
    adult ward is still a newborn."""
    if primary.band is not None:
        return reference_ranges.BY_CODE[primary.band]
    return reference_ranges.band_for_age(age)


def confidence_penalty(profiles: tuple[Profile, ...]) -> float:
    total = sum(profile.confidence_penalty for profile in profiles)
    return round(min(total, MAX_CONFIDENCE_PENALTY), 3)


def confounders_for(profiles: tuple[Profile, ...]) -> frozenset[str]:
    out: set[str] = set()
    for profile in profiles:
        out.update(profile.confounders)
    return frozenset(out)


def reference_scale_for(primary: Profile) -> str:
    return primary.reference_scale or scales.NRS


def signals_not_available(profiles: tuple[Profile, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for profile in profiles:
        for signal in profile.signals_not_available:
            if signal not in out:
                out.append(signal)
    return tuple(out)


def prefers_own_history(profiles: tuple[Profile, ...]) -> bool:
    return any(profile.prefers_own_history for profile in profiles)


# ---------------------------------------------------------------------------
# What a recorded context resolves to. One definition, so the quality gate, the
# rule engine and the feature set all read the same bands for the same patient.
# ---------------------------------------------------------------------------


def primary_of(ctx) -> Profile:
    return resolve(ctx.profile, ctx.profile_modifiers, age=ctx.age)


def applicable_to(ctx) -> tuple[Profile, ...]:
    return applicable(primary_of(ctx), ctx.profile_modifiers)


def normal_ranges(ctx) -> dict[str, tuple[float, float]]:
    """The resting ranges this patient's vitals are read against, after the band is
    chosen from the profile and shifted for pregnancy where a trimester is known."""
    primary = primary_of(ctx)
    ranges = reference_ranges.normal(band_for(primary, ctx.age))
    if ctx.pregnancy_trimester is not None:
        ranges = reference_ranges.with_pregnancy(ranges, ctx.pregnancy_trimester)
    return ranges


def plausible_ranges(ctx) -> dict[str, tuple[float, float]]:
    return reference_ranges.plausible(band_for(primary_of(ctx), ctx.age))


# Below this age in years, whole years cannot separate the profiles that differ most, so
# the month count decides and the age the platform reasons about is fractional.
MONTH_PRECISION_UNDER_YEARS = 3
