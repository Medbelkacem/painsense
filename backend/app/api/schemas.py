"""Request and response shapes.

Validation policy for measurements, which is the part that matters clinically: a value
outside what a person can physiologically have is rejected with a message, because it is a
recording error. A value that is possible but abnormal is accepted exactly as entered and
flagged downstream. The platform never rewrites what the clinician typed.

The bounds come from app.ai.quality so that the API and the estimator agree on what counts
as impossible.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.ai.quality import IMPLAUSIBLE
from app.database.models import (
    AssessmentStatus,
    Course,
    DataQuality,
    DocumentKind,
    Onset,
    Pattern,
    Profession,
    Role,
    Sex,
    SmokingStatus,
)

Text = Annotated[str, Field(max_length=4000)]
ShortText = Annotated[str, Field(max_length=255)]
Nrs = Annotated[float, Field(ge=0, le=10)]

_hr = IMPLAUSIBLE["hr"]
_rr = IMPLAUSIBLE["resp_rate"]
_sbp = IMPLAUSIBLE["sbp"]
_dbp = IMPLAUSIBLE["dbp"]
_spo2 = IMPLAUSIBLE["spo2"]
_temp = IMPLAUSIBLE["temperature_c"]
_glucose = IMPLAUSIBLE["glucose_mmol"]


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- authentication ----------------------------------------------------------------


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


class RegistrationRequest(BaseModel):
    """What a clinician gives when they create their own account.

    It sets no role: self-registration always produces a clinician account. Only an
    administrator can grant administrator rights, so the form cannot be used to obtain
    them.
    """

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


class DoctorUpdate(BaseModel):
    display_name: ShortText | None = None
    clinic_name: ShortText | None = None
    phone: ShortText | None = None
    profession: Profession | None = None
    role: Role | None = None
    speciality: ShortText | None = None
    registration_number: ShortText | None = None
    is_active: bool | None = None


# --- patients ----------------------------------------------------------------------


class PatientIdentity(BaseModel):
    """Direct identifiers. Sealed before storage, never placed in a queryable column.

    No identity card number is collected: the internal patient code is the identifier the
    platform uses everywhere else.
    """

    given_name: Annotated[str, Field(min_length=1, max_length=120)]
    family_name: Annotated[str, Field(min_length=1, max_length=120)]
    phone: ShortText | None = None
    emergency_contact_name: ShortText | None = None
    emergency_contact_phone: ShortText | None = None


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


class PatientBase(BaseModel):
    sex: Sex = Sex.UNDISCLOSED
    birth_date: date | None = None
    ward: ShortText | None = None
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


class PatientCreate(PatientBase):
    identity: PatientIdentity
    condition_codes: list[str] = Field(default_factory=list)
    medications: list[MedicationIn] = Field(default_factory=list)
    is_synthetic: bool = False


class PatientUpdate(BaseModel):
    identity: PatientIdentity | None = None
    sex: Sex | None = None
    birth_date: date | None = None
    ward: ShortText | None = None
    smoking_status: SmokingStatus | None = None
    medical_history: Text | None = None
    previous_surgeries: Text | None = None
    allergies: Text | None = None
    family_history: Text | None = None
    lifestyle_notes: Text | None = None
    condition_codes: list[str] | None = None
    medications: list[MedicationIn] | None = None


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
    birth_date: date | None
    smoking_status: SmokingStatus
    medical_history: str | None
    previous_surgeries: str | None
    allergies: str | None
    family_history: str | None
    lifestyle_notes: str | None
    conditions: list[ConditionOut]
    medications: list[MedicationOut]
    created_at: datetime


class PatientPage(BaseModel):
    items: list[PatientSummary]
    total: int
    limit: int
    offset: int


# --- assessments -------------------------------------------------------------------


Side = Literal["LEFT", "RIGHT", "BILATERAL", "MIDLINE", "NOT_APPLICABLE"]


class LocationIn(BaseModel):
    code: Annotated[str, Field(max_length=48)]
    side: Side = "NOT_APPLICABLE"
    is_primary: bool = False


class AnatomicalSiteIn(BaseModel):
    """A structure localised on the 3D model.

    `intensity` is recorded per site and is never assembled into a feature vector, for the
    same reason the self-reported score is not: it rates the thing the estimate is for.
    """

    structure_code: Annotated[str, Field(max_length=48)]
    # Required rather than defaulted: most structures are paired, and a record that does
    # not say which side was painful is not a record of where the pain is.
    side: Side
    intensity: Nrs | None = None
    is_primary: bool = False
    note: ShortText | None = None


class AnatomicalSiteOut(AnatomicalSiteIn):
    label: str
    latin: str
    structure_type: str
    region: str
    location_code: str


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
    """The patient's own score. Stored apart and never used as a model input."""

    nrs: Nrs
    reported_at: datetime | None = None
    note: Text | None = None


class SelfReportOut(Model):
    nrs: float
    reported_at: datetime
    note: str | None


class AssessmentBase(BaseModel):
    onset: Onset = Onset.UNKNOWN
    started_at: datetime | None = None
    duration_hours: Annotated[float, Field(ge=0, le=900_000)] | None = None
    pattern: Pattern = Pattern.UNKNOWN
    course: Course = Course.UNKNOWN
    episodes_per_day: Annotated[float, Field(ge=0, le=100)] | None = None
    episode_minutes: Annotated[float, Field(ge=0, le=10_000)] | None = None
    night_pain: bool = False
    morning_pain: bool = False
    pain_after_activity: bool = False
    pain_at_rest: bool = False
    radiates: bool = False
    radiation_description: Text | None = None
    radiation_numbness: bool = False
    radiation_tingling: bool = False
    radiation_weakness: bool = False
    recent_trauma: bool = False
    recent_surgery: bool = False

    @field_validator("started_at")
    @classmethod
    def not_in_the_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        # A client may send a local time without an offset; read it as UTC rather than
        # rejecting it, and allow an hour of clock skew.
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
    answers: dict[str, object] = Field(default_factory=dict)
    measurement: MeasurementIn | None = None
    self_report: SelfReportIn | None = None


class AssessmentUpdate(BaseModel):
    onset: Onset | None = None
    started_at: datetime | None = None
    duration_hours: Annotated[float, Field(ge=0, le=900_000)] | None = None
    pattern: Pattern | None = None
    course: Course | None = None
    episodes_per_day: Annotated[float, Field(ge=0, le=100)] | None = None
    episode_minutes: Annotated[float, Field(ge=0, le=10_000)] | None = None
    night_pain: bool | None = None
    morning_pain: bool | None = None
    pain_after_activity: bool | None = None
    pain_at_rest: bool | None = None
    radiates: bool | None = None
    radiation_description: Text | None = None
    radiation_numbness: bool | None = None
    radiation_tingling: bool | None = None
    radiation_weakness: bool | None = None
    recent_trauma: bool | None = None
    recent_surgery: bool | None = None
    locations: list[LocationIn] | None = None
    anatomical_sites: Annotated[list[AnatomicalSiteIn], Field(max_length=30)] | None = None
    quality_codes: list[str] | None = None
    symptom_codes: list[str] | None = None
    factor_codes: list[str] | None = None
    confounder_codes: list[str] | None = None
    answers: dict[str, object] | None = None
    measurement: MeasurementIn | None = None
    self_report: SelfReportIn | None = None


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
    model_version: str | None
    dataset_version: str | None
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
    priority_factors: list[dict]
    data_quality: DataQuality
    quality_issues: list[str]
    missing_fields: list[str]
    confounder_notes: list[dict]
    # What the model actually read. Published so the claim that the self-reported
    # score is not an input can be checked rather than taken on trust.
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
    self_report: float | None
    alert_count: int
    is_synthetic: bool


class AssessmentDetail(AssessmentSummary):
    doctor_id: uuid.UUID
    updated_at: datetime
    validated_at: datetime | None
    onset: Onset
    started_at: datetime | None
    duration_hours: float | None
    pattern: Pattern
    course: Course
    episodes_per_day: float | None
    episode_minutes: float | None
    night_pain: bool
    morning_pain: bool
    pain_after_activity: bool
    pain_at_rest: bool
    radiates: bool
    radiation_description: str | None
    radiation_numbness: bool
    radiation_tingling: bool
    radiation_weakness: bool
    recent_trauma: bool
    recent_surgery: bool
    locations: list[LocationIn]
    anatomical_sites: list[AnatomicalSiteOut]
    quality_codes: list[str]
    symptom_codes: list[str]
    factor_codes: list[str]
    confounder_codes: list[str]
    answers: dict[str, object]
    measurement: MeasurementOut | None
    self_report_detail: SelfReportOut | None
    prediction: PredictionOut | None
    notes: list[NoteOut]
    document_count: int


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


# --- catalogue ---------------------------------------------------------------------


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
    note: str


class AnatomicalTypeGroup(BaseModel):
    type: str
    label: str
    structures: list[str]


class AnatomicalRegionGroup(BaseModel):
    region: str
    label: str
    types: list[AnatomicalTypeGroup]


class AnatomyOntology(BaseModel):
    """Regions, then structure types, then structures, plus the same set nested as a tree."""

    notice: str
    regions: list[AnatomicalRegionOut]
    structure_types: list[AnatomicalStructureTypeOut]
    structures: list[AnatomicalStructureOut]
    tree: list[AnatomicalRegionGroup]


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
    """The draft assessment the question engine should evaluate."""

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
    answers: dict[str, object] = Field(default_factory=dict)


class BandOut(BaseModel):
    code: str
    label: str
    upper_bound: float


# --- documents ---------------------------------------------------------------------


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


# --- platform ----------------------------------------------------------------------


class AnalyticsOut(BaseModel):
    patients_total: int
    patients_synthetic: int
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


class SecurityStatus(BaseModel):
    algorithms: list[AlgorithmStatus]
    keys: list[dict]
    keystore_path: str
    integrity: IntegrityStatus
    recent_events: list[dict]
    session_count: int


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
    seed: int
    n_rows: int
    is_synthetic: bool
    distribution: dict
    path: str


class DatasetRequest(BaseModel):
    rows: Annotated[int, Field(ge=100, le=200_000)] = 10_000
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 42


class ModelOut(Model):
    version: str
    algorithm: str
    trained_at: datetime
    dataset_version: str
    n_train: int
    n_test: int
    mae: float
    rmse: float
    r2: float
    pearson: float
    cv_folds: int
    cv_mae_mean: float
    cv_mae_sd: float
    residual_sd: float
    features: list[str]
    is_active: bool
    notes: str


class TrainingRequest(BaseModel):
    test_size: Annotated[float, Field(ge=0.1, le=0.5)] = 0.2
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    cv_folds: Annotated[int, Field(ge=2, le=10)] = 5


class ModelStatus(BaseModel):
    trained: bool
    active: ModelOut | None
    versions: list[ModelOut]
    feature_count: int
    excluded_from_features: list[str]
    limitations: list[str]
