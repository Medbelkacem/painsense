import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from backend.ai.quality import IMPLAUSIBLE
from database.models import (
    AlertSeverity,
    AssessmentStatus,
    Attribution,
    Availability,
    BurnDepth,
    Course,
    DataQuality,
    DocumentKind,
    Granularity,
    JobStatus,
    LicenceVerdict,
    Onset,
    OnsetSpeed,
    PainSiteRole,
    Pattern,
    Profession,
    QualityStatus,
    RecordingState,
    ReviewAgreement,
    ReviewState,
    Role,
    RunStatus,
    Sex,
    SignalSource,
    SmokingStatus,
    SourceAccess,
    SyncOutcome,
    SyncStage,
    TbsaMethod,
)
from knowledge import profiles, scales
from knowledge.context import FUNCTIONAL_MAX
from knowledge.wards import WARDS

Text = Annotated[str, Field(max_length=4000)]
ShortText = Annotated[str, Field(max_length=255)]
Ward = Literal[WARDS]
DurationUnit = Literal["minutes", "hours", "days", "months", "years"]
HOURS_PER_UNIT = {"minutes": 1 / 60, "hours": 1.0, "days": 24.0, "months": 730.0, "years": 8766.0}

# Algerian numbers: a mobile is 0 then 5, 6 or 7 and eight digits; a landline is 0, a
# one-digit area code and seven digits. +213 and 00213 stand in for the leading 0.
_MOBILE = re.compile(r"^0[5-7]\d{8}$")
_LANDLINE = re.compile(r"^0[1-4]\d{7}$")


def algerian_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[\s().-]", "", value)
    if not digits:
        return None
    if digits.startswith("+213"):
        digits = "0" + digits[4:]
    elif digits.startswith("00213"):
        digits = "0" + digits[5:]
    if not (_MOBILE.match(digits) or _LANDLINE.match(digits)):
        raise ValueError(
            "enter an Algerian number: a mobile such as 05 51 23 45 67 or a landline such "
            "as 033 12 34 56, with or without +213"
        )
    return digits
Nrs = Annotated[float, Field(ge=0, le=10)]
ImpactScore = Annotated[int, Field(ge=0, le=FUNCTIONAL_MAX)]
Language = Literal["en", "fr", "ar"]

_hr = IMPLAUSIBLE["hr"]
_rr = IMPLAUSIBLE["resp_rate"]
_sbp = IMPLAUSIBLE["sbp"]
_dbp = IMPLAUSIBLE["dbp"]
_spo2 = IMPLAUSIBLE["spo2"]
_temp = IMPLAUSIBLE["temperature_c"]
_glucose = IMPLAUSIBLE["glucose_mmol"]


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]


class UserOut(Model):
    id: uuid.UUID
    email: str
    display_name: str
    clinic_name: str | None = None
    phone: str | None = None
    profession: Profession = Profession.DOCTOR
    role: Role
    registration_number: str | None = None
    speciality: str | None = None
    is_active: bool = True
    last_login_at: datetime | None = None
    preferred_language: Language = "en"
    locked_until: datetime | None = None
    patient_id: uuid.UUID | None = None
    patient_code: str | None = None


class ProfileUpdate(BaseModel):
    display_name: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    clinic_name: ShortText | None = None
    phone: ShortText | None = None
    speciality: ShortText | None = None
    registration_number: ShortText | None = None
    preferred_language: Language | None = None


class PasswordChange(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=12, max_length=256)]


class SessionOut(Model):
    id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    user_agent: str | None
    client_ip: str | None


class RegistrationRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=256)]
    display_name: Annotated[str, Field(min_length=2, max_length=120)]
    clinic_name: Annotated[str, Field(min_length=2, max_length=160)]
    phone: Annotated[str, Field(min_length=5, max_length=48)]
    profession: Profession
    speciality: ShortText | None = None
    registration_number: ShortText | None = None

    @model_validator(mode="after")
    def speciality_for_doctors(self) -> "RegistrationRequest":
        if self.profession is Profession.DOCTOR and not (self.speciality or "").strip():
            raise ValueError("speciality is required for a doctor")
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    csrf_token: str
    user: UserOut


class DoctorCreate(BaseModel):
    email: EmailStr
    display_name: ShortText
    password: Annotated[str, Field(min_length=12, max_length=256)]
    role: Role = Role.DOCTOR
    profession: Profession = Profession.DOCTOR
    clinic_name: ShortText | None = None
    phone: ShortText | None = None
    registration_number: ShortText | None = None
    speciality: ShortText | None = None
    patient_id: uuid.UUID | None = None


class DoctorUpdate(BaseModel):
    display_name: ShortText | None = None
    clinic_name: ShortText | None = None
    phone: ShortText | None = None
    profession: Profession | None = None
    role: Role | None = None
    speciality: ShortText | None = None
    registration_number: ShortText | None = None
    is_active: bool | None = None
    patient_id: uuid.UUID | None = None


class PatientIdentity(BaseModel):
    given_name: Annotated[str, Field(min_length=1, max_length=120)]
    family_name: Annotated[str, Field(min_length=1, max_length=120)]
    phone: ShortText | None = None
    emergency_contact_name: ShortText | None = None
    emergency_contact_phone: ShortText | None = None

    @field_validator("phone", "emergency_contact_phone")
    @classmethod
    def algerian(cls, value: str | None) -> str | None:
        return algerian_phone(value)

    @field_validator("given_name", "family_name", "emergency_contact_name")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("cannot be blank")
        return value


class MedicationIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    dose: ShortText | None = None
    frequency: ShortText | None = None
    started_on: date | None = None
    is_analgesic: bool = False
    note: Text | None = None


class MedicationOut(Model):
    id: uuid.UUID
    name: str
    dose: str | None
    frequency: str | None
    started_on: date | None
    is_analgesic: bool
    note: str | None


class ConditionOut(Model):
    disease_code: str
    diagnosed_year: int | None
    note: str | None


def _recorded_sex(value: Sex) -> Sex:
    if value not in (Sex.F, Sex.M):
        raise ValueError("sex must be F or M")
    return value


class PatientBase(BaseModel):
    sex: Sex
    age_years: Annotated[int, Field(ge=0, le=120)]
    birth_date: date | None = None
    ward: Ward | None = None
    smoking_status: SmokingStatus = SmokingStatus.UNKNOWN
    medical_history: Text | None = None
    previous_surgeries: Text | None = None
    allergies: Text | None = None
    family_history: Text | None = None
    lifestyle_notes: Text | None = None

    @field_validator("birth_date")
    @classmethod
    def not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > datetime.now(timezone.utc).date():
            raise ValueError("date of birth is in the future")
        return value

    @field_validator("sex")
    @classmethod
    def female_or_male(cls, value: Sex) -> Sex:
        return _recorded_sex(value)


class PatientCreate(PatientBase):
    identity: PatientIdentity
    condition_codes: list[str] = Field(default_factory=list)
    medications: list[MedicationIn] = Field(default_factory=list)
    is_synthetic: bool = False


class PatientUpdate(BaseModel):
    identity: PatientIdentity | None = None
    sex: Sex | None = None
    age_years: Annotated[int, Field(ge=0, le=120)] | None = None
    birth_date: date | None = None
    ward: Ward | None = None
    smoking_status: SmokingStatus | None = None
    medical_history: Text | None = None
    previous_surgeries: Text | None = None
    allergies: Text | None = None
    family_history: Text | None = None
    lifestyle_notes: Text | None = None
    condition_codes: list[str] | None = None
    medications: list[MedicationIn] | None = None

    @field_validator("sex")
    @classmethod
    def female_or_male(cls, value: Sex | None) -> Sex | None:
        return None if value is None else _recorded_sex(value)


class FindingOut(BaseModel):
    code: str
    level: Literal["WARNING", "URGENT"]
    message: str


class ClinicianOut(BaseModel):
    display_name: str
    speciality: str | None = None
    registration_number: str | None = None


class PatientSummary(BaseModel):
    id: uuid.UUID
    code: str
    display_name: str
    sex: Sex
    age: int | None
    ward: str | None
    is_synthetic: bool
    archived: bool
    assessment_count: int
    latest_assessment_at: datetime | None
    latest_estimated_pain: float | None
    latest_self_report: float | None
    trend: Literal["RISING", "FALLING", "STABLE", "UNKNOWN"]


class PatientDetail(PatientSummary):
    identity: PatientIdentity | None
    age_years: int | None
    birth_date: date | None
    smoking_status: SmokingStatus
    medical_history: str | None
    previous_surgeries: str | None
    allergies: str | None
    family_history: str | None
    lifestyle_notes: str | None
    conditions: list[ConditionOut]
    medications: list[MedicationOut]
    warnings: list[FindingOut]
    created_at: datetime


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    limit: int
    offset: int


Side = Literal["LEFT", "RIGHT", "BILATERAL", "MIDLINE", "NOT_APPLICABLE"]


class LocationIn(BaseModel):
    code: Annotated[str, Field(max_length=48)]
    side: Side = "NOT_APPLICABLE"
    is_primary: bool = False


class AnatomicalSiteIn(BaseModel):
    structure_code: Annotated[str, Field(max_length=48)]

    side: Side
    role: PainSiteRole = PainSiteRole.SECONDARY
    sequence: Annotated[int, Field(ge=0, le=100)] = 0
    radiation_from_code: Annotated[str, Field(max_length=48)] | None = None
    radiation_from_side: Side | None = None
    quality_codes: list[str] = Field(default_factory=list, max_length=12)
    onset: Onset = Onset.UNKNOWN
    pattern: Pattern = Pattern.UNKNOWN
    course: Course = Course.UNKNOWN
    intensity: Nrs | None = None
    is_primary: bool = False
    note: ShortText | None = None

    @model_validator(mode="after")
    def role_and_primary_agree(self) -> "AnatomicalSiteIn":
        if self.is_primary:
            self.role = PainSiteRole.PRIMARY
        elif self.role is PainSiteRole.PRIMARY:
            self.is_primary = True
        if self.role is not PainSiteRole.RADIATING:
            self.radiation_from_code = None
            self.radiation_from_side = None
        return self


class AnatomicalSiteOut(AnatomicalSiteIn):
    label: str
    latin: str
    structure_type: str
    region: str
    subregion: str | None
    location_code: str
    breadcrumb: list[str]


class MedicationUseIn(BaseModel):
    class_code: Annotated[str, Field(max_length=48)]
    name: ShortText | None = None
    dose_category: Literal["LOW", "STANDARD", "HIGH", "UNKNOWN"] = "UNKNOWN"
    frequency: Literal[
        "SINGLE",
        "DAILY",
        "TWICE_DAILY",
        "THREE_TIMES_DAILY",
        "FOUR_TIMES_DAILY",
        "AS_NEEDED",
        "CONTINUOUS",
        "UNKNOWN",
    ] = "UNKNOWN"
    hours_since_last_dose: Annotated[float, Field(ge=0, le=24 * 90)] | None = None
    pain_effect: Literal["NONE", "PARTIAL", "GOOD", "UNKNOWN"] = "UNKNOWN"
    sedation_effect: Literal["NONE", "MILD", "MARKED", "UNKNOWN"] = "UNKNOWN"


class MedicationUseOut(MedicationUseIn):
    class_label: str
    analgesic: bool
    sedating: bool


class MeasurementIn(BaseModel):
    recorded_at: datetime | None = None
    hr: Annotated[float, Field(ge=_hr[0], le=_hr[1])] | None = None
    resp_rate: Annotated[float, Field(ge=_rr[0], le=_rr[1])] | None = None
    sbp: Annotated[float, Field(ge=_sbp[0], le=_sbp[1])] | None = None
    dbp: Annotated[float, Field(ge=_dbp[0], le=_dbp[1])] | None = None
    spo2: Annotated[float, Field(ge=_spo2[0], le=_spo2[1])] | None = None
    temperature_c: Annotated[float, Field(ge=_temp[0], le=_temp[1])] | None = None
    glucose_mmol: Annotated[float, Field(ge=_glucose[0], le=_glucose[1])] | None = None
    weight_kg: Annotated[float, Field(gt=0, le=400)] | None = None
    height_cm: Annotated[float, Field(gt=30, le=260)] | None = None

    @field_validator("dbp")
    @classmethod
    def diastolic_below_systolic(cls, value, info):
        systolic = info.data.get("sbp")
        if value is not None and systolic is not None and value >= systolic:
            raise ValueError("diastolic pressure must be below systolic pressure")
        return value


class MeasurementOut(Model):
    recorded_at: datetime
    hr: float | None
    resp_rate: float | None
    sbp: float | None
    dbp: float | None
    spo2: float | None
    temperature_c: float | None
    glucose_mmol: float | None
    weight_kg: float | None
    height_cm: float | None
    bmi: float | None


class SelfReportIn(BaseModel):
    """The reference score for this assessment.

    Either `nrs` directly, for a 0-10 rating, or a `scale_code` with the score on that
    instrument's own range. An observational scale may instead be given as per-item scores
    in `items`, and the total is then computed rather than trusted.
    """

    nrs: Nrs | None = None
    scale_code: Annotated[str, Field(max_length=16)] = scales.NRS
    raw_score: Annotated[float, Field(ge=0, le=100)] | None = None
    items: dict[str, float] = Field(default_factory=dict)
    observed: bool | None = None
    reported_at: datetime | None = None
    note: Text | None = None

    @model_validator(mode="after")
    def resolve_against_the_scale(self):
        if self.scale_code not in scales.BY_CODE:
            raise ValueError(f"unknown pain scale {self.scale_code}")
        scale = scales.BY_CODE[self.scale_code]

        if self.items:
            unknown = sorted(set(self.items) - {item.code for item in scale.items})
            if unknown:
                raise ValueError(f"{self.scale_code} has no items {', '.join(unknown)}")
            self.raw_score = scales.total(self.scale_code, self.items)
        elif self.raw_score is None:
            if self.nrs is None:
                raise ValueError("give a score, either as nrs, raw_score or items")
            if scale.code != scales.NRS:
                raise ValueError(
                    f"{self.scale_code} is scored on its own range, so give raw_score or "
                    "items rather than nrs"
                )
            self.raw_score = float(self.nrs)

        if not scale.minimum <= self.raw_score <= scale.maximum:
            raise ValueError(
                f"{self.scale_code} is scored between {scale.minimum:g} and {scale.maximum:g}"
            )
        if scale.steps and self.raw_score not in scale.steps:
            raise ValueError(
                f"{self.scale_code} accepts only "
                + ", ".join(str(step) for step in scale.steps)
            )

        projected = scales.normalise(self.scale_code, self.raw_score)
        if self.nrs is not None and scale.code == scales.NRS and self.nrs != projected:
            raise ValueError("nrs and raw_score disagree")
        self.nrs = projected
        if self.observed is None:
            self.observed = scale.observational
        return self


class SelfReportOut(Model):
    nrs: float
    scale_code: str
    raw_score: float | None
    raw_max: float | None
    items: dict
    observed: bool
    reported_at: datetime
    note: str | None


class FunctionalImpactIn(BaseModel):
    mobility: ImpactScore | None = None
    sleep: ImpactScore | None = None
    work: ImpactScore | None = None
    daily_activity: ImpactScore | None = None
    self_care: ImpactScore | None = None


class ScaleItemOut(BaseModel):
    code: str
    label: str
    minimum: int
    maximum: int
    anchors: list[str]


class ScaleOut(BaseModel):
    code: str
    label: str
    kind: str
    minimum: float
    maximum: float
    steps: list[int]
    population: str
    note: str
    items: list[ScaleItemOut]


class PatientProfileOut(BaseModel):
    code: str
    label: str
    kind: str
    min_age: float | None
    max_age: float | None
    can_self_report: bool
    reference_scale: str | None
    alternative_scales: list[str]
    priority_signals: list[str]
    signals_not_available: list[str]
    confounders: list[str]
    confidence_penalty: float
    requires_trimester: bool
    prefers_own_history: bool
    interpretation: str
    note: str


class ReferenceBandOut(BaseModel):
    code: str
    label: str
    min_age: float | None
    max_age: float | None
    source: str
    normal: dict[str, list[float]]
    unverified: list[str]
    note: str


class ProfileCatalogue(BaseModel):
    primary: list[PatientProfileOut]
    modifiers: list[PatientProfileOut]
    scales: list[ScaleOut]
    bands: list[ReferenceBandOut]
    notice: str


class CalibrationIn(BaseModel):
    """A short calibration taken with the patient at rest."""

    readings: Annotated[int, Field(ge=1, le=20)] = 1
    minutes_at_rest: Annotated[float, Field(ge=0, le=240)] | None = None
    hr: Annotated[float, Field(ge=_hr[0], le=_hr[1])] | None = None
    resp_rate: Annotated[float, Field(ge=_rr[0], le=_rr[1])] | None = None
    sbp: Annotated[float, Field(ge=_sbp[0], le=_sbp[1])] | None = None
    dbp: Annotated[float, Field(ge=_dbp[0], le=_dbp[1])] | None = None
    spo2: Annotated[float, Field(ge=_spo2[0], le=_spo2[1])] | None = None
    temperature_c: Annotated[float, Field(ge=_temp[0], le=_temp[1])] | None = None
    note: Text | None = None

    @model_validator(mode="after")
    def at_least_one_reading(self):
        if not any(
            getattr(self, name) is not None
            for name in ("hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c")
        ):
            raise ValueError("a calibration needs at least one resting measurement")
        return self


class CalibrationOut(Model):
    recorded_at: datetime
    readings: int
    minutes_at_rest: float | None
    hr: float | None
    resp_rate: float | None
    sbp: float | None
    dbp: float | None
    spo2: float | None
    temperature_c: float | None
    note: str | None


class AssessmentBase(BaseModel):
    onset: Onset = Onset.UNKNOWN
    onset_speed: OnsetSpeed = OnsetSpeed.UNKNOWN
    started_at: datetime | None = None
    duration_value: Annotated[float, Field(ge=0, le=100_000)] | None = None
    duration_unit: DurationUnit | None = None
    pattern: Pattern = Pattern.UNKNOWN
    course: Course = Course.UNKNOWN
    recurrent: bool = False
    episodes_per_day: Annotated[float, Field(ge=0, le=100)] | None = None
    episode_minutes: Annotated[float, Field(ge=0, le=10_000)] | None = None
    night_pain: bool = False
    morning_pain: bool = False
    afternoon_pain: bool = False
    evening_pain: bool = False
    variable_timing: bool = False
    pain_after_activity: bool = False
    pain_at_rest: bool = False
    functional_impact: FunctionalImpactIn = Field(default_factory=FunctionalImpactIn)
    radiates: bool = False
    radiation_description: Text | None = None
    radiation_numbness: bool = False
    radiation_tingling: bool = False
    radiation_weakness: bool = False
    recent_trauma: bool = False
    recent_surgery: bool = False
    symptoms_note: Text | None = None
    aggravating_note: Text | None = None
    relieving_note: Text | None = None
    # The population this patient is read as. Left out, age decides.
    profile_code: Annotated[str, Field(max_length=48)] | None = None
    profile_modifiers: list[Annotated[str, Field(max_length=48)]] = Field(
        default_factory=list, max_length=8
    )
    pregnancy_trimester: Annotated[int, Field(ge=1, le=3)] | None = None
    expected_pain: bool = False

    @model_validator(mode="after")
    def duration_has_a_unit(self):
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("a duration needs both a number and a unit")
        return self

    @model_validator(mode="after")
    def profile_is_known(self):
        if self.profile_code is not None:
            entry = profiles.BY_CODE.get(self.profile_code)
            if entry is None or entry.kind != profiles.PRIMARY:
                raise ValueError(f"unknown patient profile {self.profile_code}")
        unknown = sorted(
            code
            for code in self.profile_modifiers
            if profiles.BY_CODE.get(code) is None
            or profiles.BY_CODE[code].kind != profiles.MODIFIER
        )
        if unknown:
            raise ValueError(f"unknown profile modifiers: {', '.join(unknown)}")
        return self

    @field_validator("started_at")
    @classmethod
    def not_in_the_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if moment > datetime.now(timezone.utc) + timedelta(hours=1):
            raise ValueError("the pain cannot have started in the future")
        return value


class AssessmentCreate(AssessmentBase):
    patient_id: uuid.UUID
    locations: list[LocationIn] = Field(default_factory=list, max_length=20)
    anatomical_sites: list[AnatomicalSiteIn] = Field(default_factory=list, max_length=30)
    quality_codes: list[str] = Field(default_factory=list, max_length=20)
    symptom_codes: list[str] = Field(default_factory=list, max_length=40)
    factor_codes: list[str] = Field(default_factory=list, max_length=30)
    confounder_codes: list[str] = Field(default_factory=list, max_length=20)
    medications: list[MedicationUseIn] = Field(default_factory=list, max_length=20)
    answers: dict[str, object] = Field(default_factory=dict)
    measurement: MeasurementIn | None = None
    self_report: SelfReportIn | None = None


class AssessmentUpdate(BaseModel):
    onset: Onset | None = None
    onset_speed: OnsetSpeed | None = None
    started_at: datetime | None = None
    duration_value: Annotated[float, Field(ge=0, le=100_000)] | None = None
    duration_unit: DurationUnit | None = None
    pattern: Pattern | None = None
    course: Course | None = None
    recurrent: bool | None = None
    episodes_per_day: Annotated[float, Field(ge=0, le=100)] | None = None
    episode_minutes: Annotated[float, Field(ge=0, le=10_000)] | None = None
    night_pain: bool | None = None
    morning_pain: bool | None = None
    afternoon_pain: bool | None = None
    evening_pain: bool | None = None
    variable_timing: bool | None = None
    pain_after_activity: bool | None = None
    pain_at_rest: bool | None = None
    functional_impact: FunctionalImpactIn | None = None
    radiates: bool | None = None
    radiation_description: Text | None = None
    radiation_numbness: bool | None = None
    radiation_tingling: bool | None = None
    radiation_weakness: bool | None = None
    recent_trauma: bool | None = None
    recent_surgery: bool | None = None
    symptoms_note: Text | None = None
    aggravating_note: Text | None = None
    relieving_note: Text | None = None
    locations: list[LocationIn] | None = None
    anatomical_sites: Annotated[list[AnatomicalSiteIn], Field(max_length=30)] | None = None
    quality_codes: list[str] | None = None
    symptom_codes: list[str] | None = None
    factor_codes: list[str] | None = None
    confounder_codes: list[str] | None = None
    medications: Annotated[list[MedicationUseIn], Field(max_length=20)] | None = None
    answers: dict[str, object] | None = None
    measurement: MeasurementIn | None = None
    self_report: SelfReportIn | None = None

    @model_validator(mode="after")
    def duration_has_a_unit(self):
        if (self.duration_value is None) != (self.duration_unit is None):
            raise ValueError("a duration needs both a number and a unit")
        return self


class ReviewIn(BaseModel):
    agreement: ReviewAgreement = ReviewAgreement.AGREE
    comment: Text | None = None


class NoteIn(BaseModel):
    body: Annotated[str, Field(min_length=1, max_length=4000)]


class NoteOut(Model):
    id: uuid.UUID
    body: str
    created_at: datetime
    author_id: uuid.UUID


class ContributionOut(Model):
    feature: str
    label: str
    contribution: float
    rank: int


class CategoryOut(BaseModel):
    cause_code: str
    label: str
    group: str
    score: float
    matched: list[str]
    missing: list[str]
    pain_types: list[str]
    note: str


class AlertOut(Model):
    rule_code: str
    severity: str
    label: str
    advice: str
    context_notes: list[str]


class PredictionOut(BaseModel):
    created_at: datetime
    model_name: str | None
    model_version: str | None
    dataset_version: str | None
    feature_schema_version: str | None
    inference_ms: float | None
    refused: bool
    refusal_reason: str | None
    estimated_pain: float | None
    interval_low: float | None
    interval_high: float | None
    band: str | None
    band_label: str | None
    interval_nominal_level: float | None
    interval_observed_coverage: float | None
    priority_score: float | None
    priority_level: str | None
    priority_label: str | None
    priority_disclaimer: str
    priority_factors: list[dict]
    trajectory: str
    baseline: dict
    # Which population the estimate was read under, which scale it is to be checked
    # against, and how much certainty the profile cost.
    population: dict
    profile_code: str | None
    reference_scale: str | None
    can_self_report: bool
    profile_penalty: float
    data_quality: DataQuality
    data_quality_score: float | None
    quality_issues: list[str]
    missing_fields: list[str]
    confounder_notes: list[dict]

    features: dict[str, float | None]
    contributions: list[ContributionOut]
    categories: list[CategoryOut]
    alerts: list[AlertOut]


class AssessmentSummary(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_code: str
    status: AssessmentStatus
    created_at: datetime
    patient_age_years: int | None
    location_labels: list[str]
    estimated_pain: float | None
    band: str | None
    priority_score: float | None
    priority_level: str | None
    trajectory: str | None
    self_report: float | None
    alert_count: int
    is_synthetic: bool


class AssessmentDetail(AssessmentSummary):
    doctor_id: uuid.UUID
    recorded_by: ClinicianOut | None
    validated_by_name: str | None
    updated_at: datetime
    validated_at: datetime | None
    review_agreement: ReviewAgreement | None
    review_comment: str | None
    onset: Onset
    onset_speed: OnsetSpeed
    started_at: datetime | None
    duration_value: float | None
    duration_unit: DurationUnit | None
    duration_hours: float | None
    duration_label: str
    pattern: Pattern
    course: Course
    recurrent: bool
    episodes_per_day: float | None
    episode_minutes: float | None
    night_pain: bool
    morning_pain: bool
    afternoon_pain: bool
    evening_pain: bool
    variable_timing: bool
    pain_after_activity: bool
    pain_at_rest: bool
    functional_impact: FunctionalImpactIn
    radiates: bool
    radiation_description: str | None
    radiation_numbness: bool
    radiation_tingling: bool
    radiation_weakness: bool
    recent_trauma: bool
    recent_surgery: bool
    symptoms_note: str | None
    aggravating_note: str | None
    relieving_note: str | None
    locations: list[LocationIn]
    anatomical_sites: list[AnatomicalSiteOut]
    quality_codes: list[str]
    symptom_codes: list[str]
    factor_codes: list[str]
    confounder_codes: list[str]
    medications: list[MedicationUseOut]
    answers: dict[str, object]
    measurement: MeasurementOut | None
    self_report_detail: SelfReportOut | None
    prediction: PredictionOut | None
    notes: list[NoteOut]
    document_count: int
    warnings: list[FindingOut]
    urgent_review: bool

    completeness: float
    missing_fields: list[str]


class AssessmentPage(BaseModel):
    items: list[AssessmentSummary]
    total: int
    limit: int
    offset: int


class HistoryPoint(BaseModel):
    assessment_id: uuid.UUID
    created_at: datetime
    estimated_pain: float | None
    self_report: float | None
    priority_score: float | None
    band: str | None
    hr: float | None
    resp_rate: float | None
    sbp: float | None
    dbp: float | None
    spo2: float | None
    temperature_c: float | None


class HistoryOut(BaseModel):
    patient_id: uuid.UUID
    patient_code: str
    points: list[HistoryPoint]
    trend: Literal["RISING", "FALLING", "STABLE", "UNKNOWN"]
    change_from_previous: float | None


class ComparisonField(BaseModel):
    field: str
    label: str
    previous: object | None
    current: object | None
    change: float | None


class ComparisonOut(BaseModel):
    previous_id: uuid.UUID
    current_id: uuid.UUID
    previous_at: datetime
    current_at: datetime
    fields: list[ComparisonField]
    symptoms_added: list[str]
    symptoms_resolved: list[str]
    sites_added: list[str]
    sites_resolved: list[str]
    sites_unchanged: list[str]

    distribution_changed: bool


class TimelineEvent(BaseModel):
    at: datetime
    kind: Literal[
        "ASSESSMENT",
        "PREDICTION",
        "SELF_REPORT",
        "MEASUREMENT",
        "MEDICATION",
        "DOCUMENT",
        "REPORT",
        "REVIEW",
        "NOTE",
    ]
    title: str
    detail: str | None
    assessment_id: uuid.UUID | None
    value: float | None = None
    level: str | None = None


class TimelineOut(BaseModel):
    patient_id: uuid.UUID
    patient_code: str
    events: list[TimelineEvent]


class BaselineVital(BaseModel):
    field: str
    label: str
    baseline: float
    current: float | None
    delta: float | None
    readings: int
    departed: bool


class BaselineOut(BaseModel):
    patient_id: uuid.UUID
    assessments_used: int
    vitals: list[BaselineVital]
    previous_pain: float | None
    current_pain: float | None
    trajectory: str
    pain_change: float | None


class LocationOut(Model):
    code: str
    label: str
    region: str
    parent_code: str | None


class AnatomicalRegionOut(Model):
    code: str
    label: str
    display_order: int


class AnatomicalStructureTypeOut(Model):
    code: str
    label: str
    description: str
    display_order: int


class AnatomicalStructureOut(Model):
    code: str
    label: str
    latin: str
    structure_type: str
    region: str
    location_code: str
    location_left: str | None
    location_right: str | None
    laterality: Literal["PAIRED", "MIDLINE", "LEFT", "RIGHT"]
    sides: list[Side]
    synonyms: list[str]
    sex: Literal["F", "M"] | None
    parent_code: str | None
    subregion: str | None
    system: str | None
    has_mesh: bool
    pain_selectable: bool
    description: str
    note: str


class AnatomicalRelationOut(BaseModel):
    relation: str
    code: str
    label: str
    structure_type: str


class AnatomicalStructureDetail(AnatomicalStructureOut):
    breadcrumb: list[dict]
    related: list[AnatomicalRelationOut]
    children: list[str]


class AnatomySearchHit(BaseModel):
    code: str
    label: str
    latin: str
    structure_type: str
    region: str
    subregion: str | None
    sides: list[Side]
    breadcrumb: list[str]


class AnatomicalTypeGroup(BaseModel):
    type: str
    label: str
    structures: list[str]


class AnatomicalRegionGroup(BaseModel):
    region: str
    label: str
    types: list[AnatomicalTypeGroup]


class AnatomyOntology(BaseModel):
    notice: str
    regions: list[AnatomicalRegionOut]
    structure_types: list[AnatomicalStructureTypeOut]
    systems: list[dict]
    structures: list[AnatomicalStructureOut]
    tree: list[AnatomicalRegionGroup]
    counts: dict[str, int]


class QualityOut(Model):
    code: str
    label: str
    neuropathic_hint: bool


class PainTypeOut(Model):
    code: str
    label: str
    group: str
    parent_code: str | None
    description: str


class SymptomOut(Model):
    code: str
    label: str
    group: str
    systemic: bool
    alarm: bool


class DiseaseOut(Model):
    code: str
    label: str
    category: str
    pain_relevant: bool


class FactorOut(Model):
    code: str
    label: str
    kind: str


class ConfounderOut(Model):
    code: str
    label: str
    affects: list[str]
    note: str


class MedicationClassOut(Model):
    code: str
    label: str
    analgesic: bool
    sedating: bool
    affects: list[str]
    note: str


class QuestionOut(BaseModel):
    code: str
    prompt: str
    kind: str
    group: str
    group_label: str
    options: list[dict]
    unit: str | None
    minimum: float | None
    maximum: float | None
    help_text: str
    order: int


class QuestionContext(BaseModel):
    patient_id: uuid.UUID | None = None
    age: Annotated[int, Field(ge=0, le=130)] | None = None
    sex: Sex | None = None
    locations: list[str] = Field(default_factory=list)
    quality_codes: list[str] = Field(default_factory=list)
    symptom_codes: list[str] = Field(default_factory=list)
    condition_codes: list[str] = Field(default_factory=list)
    factor_codes: list[str] = Field(default_factory=list)
    confounder_codes: list[str] = Field(default_factory=list)
    onset: Onset | None = None
    pattern: Pattern | None = None
    course: Course | None = None
    duration_hours: Annotated[float, Field(ge=0, le=900_000)] | None = None
    radiates: bool | None = None
    recent_trauma: bool = False
    recent_surgery: bool = False
    medication_classes: list[str] = Field(default_factory=list)
    functional_impact: FunctionalImpactIn = Field(default_factory=FunctionalImpactIn)
    answers: dict[str, object] = Field(default_factory=dict)


class BandOut(BaseModel):
    code: str
    label: str
    upper_bound: float


class DocumentOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    assessment_id: uuid.UUID | None
    kind: DocumentKind
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    findings: str | None
    extracted_text: str | None
    uploaded_at: datetime
    uploaded_by: uuid.UUID


class DocumentFindings(BaseModel):
    findings: Text


class AnalyticsOut(BaseModel):
    patients_total: int
    assessments_total: int
    assessments_today: int
    assessments_awaiting_validation: int
    high_pain_count: int
    alerts_open: int
    mean_estimated_pain: float | None
    mean_self_report: float | None
    estimate_vs_self_report_mae: float | None
    band_distribution: dict[str, int]
    region_distribution: dict[str, int]
    daily_mean_pain: list[dict]
    recent_assessments: list[AssessmentSummary]


class IntegrityProblem(BaseModel):
    height: int
    kind: str
    detail: str


class IntegrityStatus(BaseModel):
    ledger_valid: bool
    blocks: int
    signature_scheme: str | None
    key_fingerprint: str | None
    audit_valid: bool
    audit_entries: int
    problems: list[IntegrityProblem]
    verified_at: datetime


class AlgorithmStatus(BaseModel):
    name: str
    purpose: str
    status: str
    detail: str


class KeyVersionOut(BaseModel):
    label: str
    purpose: str
    version: int
    algorithm: str
    fingerprint: str
    is_current: bool
    created_at: datetime
    rotated_at: datetime | None
    retired_at: datetime | None


class SecurityStatus(BaseModel):
    algorithms: list[AlgorithmStatus]
    keys: list[KeyVersionOut]
    pqc_kem_level: str
    pqc_sign_level: str
    integrity: IntegrityStatus
    recent_events: list[dict]
    session_count: int
    failed_logins_24h: int
    locked_accounts: int
    documents_encrypted: int
    patients_sealed: int
    master_key_versions_in_ring: int


class AuditEntryOut(Model):
    seq: int
    timestamp: datetime
    actor_label: str | None
    event_type: str
    resource: str | None
    resource_id: str | None
    client_ip: str | None
    meta: dict
    entry_hash: str


class AuditPage(BaseModel):
    items: list[AuditEntryOut]
    total: int
    limit: int
    offset: int


class DatasetOut(Model):
    version: str
    generated_at: datetime
    generator_version: str
    seed: int
    n_rows: int
    n_patients: int
    is_synthetic: bool
    storage_format: str
    parameters: dict
    scenario_versions: dict
    split: dict
    distribution: dict
    path: str


class DatasetRequest(BaseModel):
    patients: Annotated[int, Field(ge=20, le=100_000)] = 5_000
    assessments: Annotated[int, Field(ge=100, le=1_500_000)] = 100_000
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42
    hard_case_share: Annotated[float, Field(ge=0, le=0.5)] = 0.12


class DatasetExplorerOut(BaseModel):
    latest: DatasetOut | None
    versions: list[DatasetOut]
    anatomy: dict[str, int]
    pain_types: int
    pain_qualities: int
    symptoms: int
    diseases: int
    medication_classes: int
    confounders: int
    questions: int
    rules: int


class ModelOut(Model):
    version: str
    model_name: str
    algorithm: str
    trained_at: datetime
    dataset_version: str
    feature_schema_version: str
    n_train: int
    n_validation: int
    n_test: int
    mae: float
    rmse: float
    r2: float
    pearson: float
    f1_band: float | None
    inference_ms: float | None
    cv_folds: int
    cv_mae_mean: float
    cv_mae_sd: float
    residual_sd: float
    features: list[str]
    feature_importance: list[dict]
    comparison: list[dict]
    training_profile: dict
    is_active: bool
    notes: str


class TrainingRequest(BaseModel):
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    cv_folds: Annotated[int, Field(ge=2, le=10)] = 5


class ModelStatus(BaseModel):
    trained: bool
    active: ModelOut | None
    versions: list[ModelOut]
    feature_count: int
    feature_schema_version: str
    excluded_from_features: list[str]
    limitations: list[str]
    prediction_count: int


class DriftOut(BaseModel):
    level: str
    sample_size: int
    warnings: list[str]
    features: list[dict]
    prediction_shift: dict


class WhatIfRequest(BaseModel):
    measurement: MeasurementIn | None = None
    symptom_codes: list[str] | None = None
    quality_codes: list[str] | None = None
    confounder_codes: list[str] | None = None
    anatomical_sites: Annotated[list[AnatomicalSiteIn], Field(max_length=30)] | None = None
    functional_impact: FunctionalImpactIn | None = None
    medications: Annotated[list[MedicationUseIn], Field(max_length=20)] | None = None
    onset: Onset | None = None
    pattern: Pattern | None = None
    course: Course | None = None
    duration_hours: Annotated[float, Field(ge=0, le=900_000)] | None = None
    radiates: bool | None = None


class WhatIfOut(BaseModel):
    assessment_id: uuid.UUID
    original: PredictionOut | None
    simulated: PredictionOut
    changed_features: list[dict]
    notice: str


class JobOut(Model):
    id: uuid.UUID
    kind: str
    status: JobStatus
    parameters: dict
    result: dict
    error: str | None
    progress: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class HealthOut(BaseModel):
    status: str
    checks: dict[str, dict]
    version: str
    request_id: str | None = None


# --- external dataset synchronisation ------------------------------------------------


class SyncSourceOut(Model):
    code: str
    label: str
    organisation: str
    homepage: str
    enabled: bool
    poll_interval_minutes: int
    config: dict
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    next_run_at: datetime | None
    consecutive_failures: int
    #: Whether this deployment holds the credentials the publisher needs for the parts of
    #: its API that require them. The credentials themselves are never returned.
    credentials_present: bool = False
    uses_credentials: bool = False


class SyncSourceUpdate(BaseModel):
    enabled: bool | None = None
    poll_interval_minutes: Annotated[int, Field(ge=5, le=20_160)] | None = None
    config: dict | None = None


class ExternalVersionOut(Model):
    id: uuid.UUID
    version: str
    acquired_at: datetime
    source_url: str
    licence: str | None
    storage_backend: str
    bytes: int
    sha256: str
    file_format: str
    file_count: int
    manifest: list
    records: int | None
    columns: list
    missing_value_pct: float | None
    quality_status: QualityStatus
    quality_findings: list
    preprocessed_key: str | None
    suitability: dict
    trainable: bool
    training_job_id: uuid.UUID | None


class ExternalDatasetOut(Model):
    id: uuid.UUID
    source_code: str
    external_id: str
    name: str
    description: str
    source_url: str
    download_url: str | None
    download_mechanism: str
    disease_code: str | None
    disease_match: dict
    dataset_type: str
    granularity: Granularity
    modalities: list
    target_labels: list
    access_status: SourceAccess
    access_procedure: list
    licence: str | None
    licence_url: str | None
    licence_verdict: LicenceVerdict
    redistribution: str
    publisher_version: str | None
    publisher_updated_at: datetime | None
    records_claimed: int | None
    relevance: int
    availability: Availability
    first_seen_at: datetime
    last_checked_at: datetime
    changed_at: datetime | None
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    notes: str


class ExternalDatasetDetailOut(ExternalDatasetOut):
    versions: list[ExternalVersionOut] = []


class SyncEventOut(Model):
    id: uuid.UUID
    run_id: uuid.UUID | None
    dataset_id: uuid.UUID | None
    at: datetime
    source_code: str
    external_id: str
    stage: SyncStage
    outcome: SyncOutcome
    message: str
    detail: dict


class SyncRunOut(Model):
    id: uuid.UUID
    source_code: str
    trigger: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    counts: dict
    error: str | None
    job_id: uuid.UUID | None


class SyncRequest(BaseModel):
    """Ask for a synchronisation run now rather than waiting for the schedule."""

    source: Annotated[str, Field(max_length=32)] | None = None
    #: Overrides the deployment default for this run only. Useful for a dry discovery
    #: pass against a publisher whose licences have not been reviewed yet.
    acquire: bool | None = None
    limit: Annotated[int, Field(ge=0, le=50)] | None = None


class DiseaseDatasetSummary(BaseModel):
    """What the disease dashboard needs for one disease, without a second round trip."""

    code: str
    label: str
    category: str
    pain_relevant: bool
    curated: bool
    origin: str
    discovered_at: datetime | None
    datasets: int
    available: int
    metadata_only: int
    records_held: int
    sources: list[str]
    last_acquired_at: datetime | None


class SyncOverviewOut(BaseModel):
    sources: list[SyncSourceOut]
    diseases: list[DiseaseDatasetSummary]
    totals: dict
    recent_runs: list[SyncRunOut]
    recent_events: list[SyncEventOut]
    notice: str


# --- burn assessment -------------------------------------------------------------------


class BurnDepthOut(BaseModel):
    code: str
    label: str
    legacy_label: str
    counts_towards_tbsa: bool
    appearance: str
    sensation: str
    note: str


class BurnRegionRefOut(BaseModel):
    code: str
    label: str
    side: str
    high_risk: bool
    nines_group: str
    nines_group_label: str
    #: The region's share of body surface in each Lund-Browder age band, so an interface
    #: can show how it changes with age rather than only the patient's own figure.
    share_by_band: dict[str, float]
    note: str


class BurnReferenceOut(BaseModel):
    depths: list[BurnDepthOut]
    regions: list[BurnRegionRefOut]
    causes: list[dict]
    methods: list[dict]
    age_bands: list[dict]
    palm_percent: float
    notice: str


class ConsentIn(BaseModel):
    scope: Annotated[str, Field(max_length=48)]
    granted: bool
    note: Text | None = None


class ConsentOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    scope: str
    granted: bool
    granted_at: datetime | None
    withdrawn_at: datetime | None
    note: str | None
    active: bool


class BurnIncidentIn(BaseModel):
    patient_id: uuid.UUID
    occurred_at: datetime
    cause: Annotated[str, Field(max_length=24)]
    cause_detail: Text | None = None
    first_aid: Text | None = None
    enclosed_space: bool | None = None
    airway_symptoms: list[ShortText] = []
    symptoms: list[ShortText] = []
    notes: Text | None = None

    @field_validator("cause")
    @classmethod
    def _known_cause(cls, value: str) -> str:
        from knowledge.burns import CAUSE_CODES

        if value not in CAUSE_CODES:
            raise ValueError(f"unknown cause; expected one of {sorted(CAUSE_CODES)}")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _not_in_future(cls, value: datetime) -> datetime:
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if moment > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("an injury cannot have happened in the future")
        return moment


class BurnIncidentOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    occurred_at: datetime
    cause: str
    cause_detail: str | None
    first_aid: str | None
    enclosed_space: bool | None
    airway_symptoms: list
    symptoms: list
    notes: str | None
    created_at: datetime
    hours_since: float | None


class BurnRegionIn(BaseModel):
    region_code: Annotated[str, Field(max_length=32)]
    fraction: Annotated[float, Field(ge=0, le=1)] = 1.0
    depth: BurnDepth = BurnDepth.UNCERTAIN
    circumferential: bool = False
    marks: list = []
    note: Text | None = None


class BurnRegionOut(Model):
    id: uuid.UUID
    region_code: str
    fraction: float
    depth: BurnDepth
    depth_attribution: Attribution
    suggested_depth: BurnDepth | None
    suggested_confidence: float | None
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    circumferential: bool
    marks: list
    note: str | None


class TbsaOut(Model):
    id: uuid.UUID
    method: TbsaMethod
    total_percent: float
    excluded_superficial_percent: float
    age_years: float | None
    age_band: str
    palms: float | None
    provisional: bool
    breakdown: list
    assumptions: list
    warnings: list
    formula: str
    attribution: Attribution
    clinician_percent: float | None
    clinician_note: str | None
    effective_percent: float
    calculated_at: datetime


class TbsaRequest(BaseModel):
    method: TbsaMethod = TbsaMethod.LUND_BROWDER
    palms: Annotated[float, Field(ge=0, le=100)] | None = None


class TbsaOverrideIn(BaseModel):
    percent: Annotated[float, Field(ge=0, le=100)]
    note: Annotated[str, Field(min_length=1, max_length=4000)]


class BurnAlertOut(Model):
    id: uuid.UUID
    code: str
    severity: AlertSeverity
    message: str
    detail: dict
    raised_at: datetime
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None


class BurnAssessmentOut(Model):
    id: uuid.UUID
    incident_id: uuid.UUID
    patient_id: uuid.UUID
    assessed_at: datetime
    assessed_by: uuid.UUID | None
    age_years: float | None
    state: ReviewState
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    notes: str | None


class BurnAssessmentDetail(BurnAssessmentOut):
    regions: list[BurnRegionOut] = []
    alerts: list[BurnAlertOut] = []
    latest_tbsa: TbsaOut | None = None
    calculations: list[TbsaOut] = []


class DepthConfirmIn(BaseModel):
    depth: BurnDepth


class BurnReviewIn(BaseModel):
    note: Annotated[str, Field(max_length=4000)] | None = None


class BurnAmendIn(BaseModel):
    note: Annotated[str, Field(min_length=1, max_length=4000)]


class BurnPainIn(BaseModel):
    incident_id: uuid.UUID | None = None
    care_event_id: uuid.UUID | None = None
    scale_code: Annotated[str, Field(max_length=16)] = "NRS"
    observed: bool = False
    current_nrs: Nrs | None = None
    at_rest_nrs: Nrs | None = None
    on_movement_nrs: Nrs | None = None
    during_care_nrs: Nrs | None = None
    before_care_nrs: Nrs | None = None
    after_care_nrs: Nrs | None = None
    items: dict = {}
    raw_score: Annotated[float, Field(ge=0)] | None = None
    raw_max: Annotated[float, Field(gt=0)] | None = None
    qualities: list[ShortText] = []
    region_codes: list[Annotated[str, Field(max_length=32)]] = []
    duration_hours: Annotated[float, Field(ge=0, le=100_000)] | None = None
    disturbs_sleep: bool | None = None
    note: Text | None = None

    @model_validator(mode="after")
    def _at_least_one_score(self) -> "BurnPainIn":
        scores = (
            self.current_nrs,
            self.at_rest_nrs,
            self.on_movement_nrs,
            self.during_care_nrs,
            self.before_care_nrs,
            self.after_care_nrs,
        )
        if all(value is None for value in scores) and not self.items:
            raise ValueError("record at least one pain score, or the items of a scored scale")
        return self

    @model_validator(mode="after")
    def _observed_needs_an_observer_scale(self) -> "BurnPainIn":
        from knowledge import scales

        entry = next((s for s in scales.SCALES if s.code == self.scale_code), None)
        if entry is None:
            raise ValueError(f"unknown scale {self.scale_code!r}")
        if self.observed and entry.kind == scales.SELF:
            raise ValueError(
                f"{self.scale_code} is a self-report scale and cannot be recorded as an "
                "observation; use an observational scale where the patient cannot be asked"
            )
        return self


class BurnPainOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    incident_id: uuid.UUID | None
    care_event_id: uuid.UUID | None
    reported_at: datetime
    scale_code: str
    observed: bool
    attribution: Attribution
    current_nrs: float | None
    at_rest_nrs: float | None
    on_movement_nrs: float | None
    during_care_nrs: float | None
    before_care_nrs: float | None
    after_care_nrs: float | None
    items: dict
    raw_score: float | None
    raw_max: float | None
    qualities: list
    region_codes: list
    duration_hours: float | None
    disturbs_sleep: bool | None
    note: str | None


class WoundCareIn(BaseModel):
    incident_id: uuid.UUID
    performed_at: datetime | None = None
    region_codes: list[Annotated[str, Field(max_length=32)]] = []
    assessment_before: Text | None = None
    cleaning: Text | None = None
    solution: ShortText | None = None
    dressing: ShortText | None = None
    tolerance: Annotated[str, Field(max_length=32)] | None = None
    analgesia_given: ShortText | None = None
    notes: Text | None = None
    next_review_on: date | None = None


class WoundCareOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    incident_id: uuid.UUID
    performed_at: datetime
    performed_by: uuid.UUID | None
    region_codes: list
    assessment_before: str | None
    cleaning: str | None
    solution: str | None
    dressing: str | None
    tolerance: str | None
    analgesia_given: str | None
    notes: str | None
    next_review_on: date | None


class FollowUpIn(BaseModel):
    incident_id: uuid.UUID
    scheduled_for: date | None = None
    occurred_at: datetime | None = None
    assessment_id: uuid.UUID | None = None
    healing_state: Annotated[str, Field(max_length=32)] | None = None
    clinician_note: Text | None = None


class FollowUpOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    incident_id: uuid.UUID
    scheduled_for: date | None
    occurred_at: datetime | None
    assessment_id: uuid.UUID | None
    healing_state: str | None
    clinician_note: str | None
    created_at: datetime


class BurnTimelineOut(BaseModel):
    """The incident with everything recorded against it, in time order."""

    incident: BurnIncidentOut
    assessments: list[BurnAssessmentDetail]
    pain_reports: list[BurnPainOut]
    care_events: list[WoundCareOut]
    follow_ups: list[FollowUpOut]
    images: list[dict]
    notice: str


# --- EEG and EMG analysis --------------------------------------------------------------


class SignalChannelOut(BaseModel):
    code: str
    label: str
    modality: str
    unit: str
    saturation: float
    minimum_rate_hz: float
    primary: bool
    note: str


class SignalReferenceOut(BaseModel):
    channels: list[SignalChannelOut]
    eeg_bands: list[dict]
    emg_band: list[float]
    default_sample_rate_hz: float
    minimum_duration_seconds: float
    feature_schema_version: str
    simulation_faults: list[str]
    #: Whether a model exists that could estimate pain from these features. False here, and
    #: the interface uses it to decide what to promise before a recording is even started.
    model_available: bool
    model_message: str
    notice: str


class DeviceOut(BaseModel):
    adapter: str
    identifier: str
    label: str
    native_channels: list[str]
    sample_rate_hz: float
    unit: str
    #: True only where the device answered. A USB descriptor that looks like an amplifier is
    #: a candidate, not a confirmation.
    confirmed: bool
    detail: dict


class AdapterOut(BaseModel):
    code: str
    label: str
    protocol: str
    transport: str


class DeviceScanOut(BaseModel):
    adapters: list[AdapterOut]
    devices: list[DeviceOut]
    #: Empty where nothing is attached. The interface shows "Device not connected" on this
    #: rather than inferring it from a failed recording.
    connected: bool
    notice: str


class RecordingStart(BaseModel):
    patient_id: uuid.UUID
    channels: list[Annotated[str, Field(max_length=32)]]
    sample_rate_hz: Annotated[float, Field(gt=0, le=20_000)] = 512.0
    #: Per-channel rates, for the common case of EEG and EMG on different clocks. Channels
    #: absent here fall back to `sample_rate_hz`.
    channel_rates: dict[str, Annotated[float, Field(gt=0, le=20_000)]] = {}
    #: Set both to have the server open the device and acquire from it. Leave unset when the
    #: client owns the device and relays blocks instead.
    adapter: Annotated[str, Field(max_length=32)] | None = None
    device_identifier: Annotated[str, Field(max_length=255)] | None = None
    device_options: dict = {}
    source: SignalSource = SignalSource.HARDWARE
    device_label: ShortText | None = None
    sensor_status: dict = {}
    #: Simulation only. Seeds the generator and injects per-channel faults so the degraded
    #: states can be exercised deliberately.
    simulate_seconds: Annotated[float, Field(ge=1, le=600)] | None = None
    simulate_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    simulate_faults: dict = {}

    @model_validator(mode="after")
    def _simulation_only_for_simulation(self) -> "RecordingStart":
        if self.source is not SignalSource.SIMULATION and (
            self.simulate_seconds is not None or self.simulate_faults
        ):
            raise ValueError(
                "simulate_seconds and simulate_faults apply only to a SIMULATION recording"
            )
        if self.source is SignalSource.SIMULATION and self.adapter:
            raise ValueError(
                "a SIMULATION recording does not open a device; leave adapter unset"
            )
        if bool(self.adapter) != bool(self.device_identifier):
            raise ValueError(
                "adapter and device_identifier are set together or not at all"
            )
        return self

    @model_validator(mode="after")
    def _rates_name_opened_channels(self) -> "RecordingStart":
        unknown = sorted(set(self.channel_rates) - set(self.channels))
        if unknown:
            raise ValueError(
                "channel_rates names channels not being recorded: " + ", ".join(unknown)
            )
        return self


class SampleBlock(BaseModel):
    """One block of samples, channel code to values.

    Capped per request rather than per recording: a block is what arrived since the last
    post, and a client sending megabytes in one body is not streaming.
    """

    samples: dict[str, list[float]]

    @field_validator("samples")
    @classmethod
    def _not_empty_or_huge(cls, value: dict[str, list[float]]) -> dict[str, list[float]]:
        if not value:
            raise ValueError("a sample block needs at least one channel")
        total = sum(len(values) for values in value.values())
        if total == 0:
            raise ValueError("a sample block needs at least one sample")
        if total > 500_000:
            raise ValueError(
                f"{total} samples in one block; post smaller blocks as they arrive"
            )
        return value


class AnalyseRequest(BaseModel):
    #: The patient's own score at the time of recording, stored beside the estimate and
    #: never used as an input to it.
    reported_nrs: Nrs | None = None


class LiveViewOut(BaseModel):
    recording_id: uuid.UUID
    source: SignalSource
    state: RecordingState
    #: Null where this process is not acquiring — a client-relayed recording has no live
    #: window on the server, because the client holds the samples until it posts them.
    channels: dict[str, list[float | None]] | None
    decimation: int | None
    rates: dict[str, float]
    device: dict
    progress: dict
    notice: str


class SignalAnalysisOut(Model):
    id: uuid.UUID
    recording_id: uuid.UUID
    analysed_at: datetime
    feature_schema_version: str
    feature_count: int
    summary: dict
    derived_from: list
    skipped_channels: dict
    heart_rate_bpm: float | None
    hrv_rmssd_ms: float | None
    skin_conductance_us: float | None
    respiration_per_min: float | None
    estimate_available: bool
    unavailable_reason: str | None
    model_version: str | None
    pain_score: float | None
    pain_category: str | None
    #: What `pain_score` is a number on. The interface shows it beside the figure rather
    #: than assuming a 0-10 scale, which not every corpus a model can be trained on uses.
    scale: str | None
    uncertainty: float | None
    interval_low: float | None
    interval_high: float | None
    reported_nrs: float | None
    notes: list


class SignalRecordingOut(Model):
    id: uuid.UUID
    patient_id: uuid.UUID
    source: SignalSource
    state: RecordingState
    device_label: str | None
    adapter: str | None
    device_identifier: str | None
    sample_rate_hz: float
    channel_rates: dict
    channels: list
    sensor_status: dict
    participant_ref: str | None
    dropped_samples: int
    invalid_packets: int
    reconnects: int
    validated_at: datetime | None
    started_at: datetime
    stopped_at: datetime | None
    duration_seconds: float | None
    samples: int
    bytes: int
    sha256: str | None
    quality_verdict: str | None
    note: str | None
    error: str | None


class SignalRecordingDetail(SignalRecordingOut):
    quality: dict = {}
    validation: dict = {}
    files: list = []
    analyses: list[SignalAnalysisOut] = []


class SignalWaveformOut(BaseModel):
    """Downsampled traces for display. Not the stored samples."""

    recording_id: uuid.UUID
    source: SignalSource
    sample_rate_hz: float
    points_per_channel: int
    #: The decimation factor applied, so a reader knows the trace is not sample-accurate.
    decimation: int
    #: Null where a sample was missing, so a dropped-out lead is a gap in the trace rather
    #: than a flat line that reads as a measurement.
    channels: dict[str, list[float | None]]
    notice: str


# --- behavioural observation ------------------------------------------------------------


class BehaviourConsentIn(BaseModel):
    """A consent to record this patient's camera and microphone.

    No scope field. The scope is the module's, so that a client cannot grant consent to
    something other than what it is asking for.
    """

    granted: bool
    note: str | None = Field(default=None, max_length=2000)


class BehaviourMeasureOut(BaseModel):
    code: str
    label: str
    modality: str
    unit: str
    note: str
    plausible: list[float] | None = None
    #: True where this measure means nothing without a resting observation to subtract.
    baseline_relative: bool


class BehaviourReferenceOut(BaseModel):
    """What the interface needs to know before a camera is opened.

    `model_available` is here so the page can say what it will and will not be able to
    report before the patient is asked to sit in front of a lens, rather than after.
    """

    measures: list[BehaviourMeasureOut]
    modalities: list[str]
    feature_schema_version: str
    minimum_seconds: float
    minimum_frame_rate: float
    iris_diameter_mm: float
    accepted_media: list[str]
    max_clip_bytes: int
    consent_scope: str
    instruction: str
    notice: str
    voice_model_available: bool
    voice_model_message: str
    voice_levels: list[str]


class BehaviourModalityOut(BaseModel):
    modality: str
    verdict: str
    usable: bool
    findings: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)


class BehaviourVoiceEstimateOut(BaseModel):
    available: bool
    message: str
    model_version: str | None = None
    level: float | None = None
    label: str | None = None
    level_error: float | None = None
    scale: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class BehaviourObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    recorded_at: datetime
    at_rest: bool

    duration_seconds: float | None = None
    frame_rate: float | None = None
    frames_decoded: int
    frames_analysed: int
    frame_width: int | None = None
    frame_height: int | None = None
    has_video: bool
    has_audio: bool
    eyes_calibrated: bool

    quality_verdict: str | None = None
    usable_modalities: list[str] = Field(default_factory=list)
    modalities: list[BehaviourModalityOut] = Field(default_factory=list)

    feature_schema_version: str
    measures: dict = Field(default_factory=dict)
    deltas: dict = Field(default_factory=dict)
    reference: dict = Field(default_factory=dict)
    absent: dict = Field(default_factory=dict)
    support: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)

    media_retained: bool
    media_bytes: int
    media_sha256: str | None = None

    voice_estimate: BehaviourVoiceEstimateOut | None = None
    notes: list[str] = Field(default_factory=list)


class BehaviourObservationSummary(BaseModel):
    """The row a patient's history shows, without the measure tables."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    recorded_at: datetime
    at_rest: bool
    duration_seconds: float | None = None
    quality_verdict: str | None = None
    usable_modalities: list[str] = Field(default_factory=list)
    has_video: bool
    has_audio: bool
    media_retained: bool
    voice_pain_level: float | None = None
    voice_pain_label: str | None = None


class RestingBehaviourOut(BaseModel):
    """This patient's resting behaviour, which later observations are read against."""

    recorded_at: datetime | None = None
    measures: dict = Field(default_factory=dict)
