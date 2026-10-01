import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base, UtcDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _enum(python_enum: type[enum.Enum], **kwargs):
    return mapped_column(Enum(python_enum, native_enum=False), **kwargs)


class Role(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    CLINIC_ADMIN = "CLINIC_ADMIN"
    DOCTOR = "DOCTOR"
    NURSE = "NURSE"
    PATIENT = "PATIENT"
    RESEARCHER = "RESEARCHER"
    AUDITOR = "AUDITOR"


ADMIN_ROLES = frozenset({Role.SUPER_ADMIN, Role.CLINIC_ADMIN})
CLINICAL_ROLES = frozenset({Role.SUPER_ADMIN, Role.CLINIC_ADMIN, Role.DOCTOR, Role.NURSE})
# A patient account reads its own record and nothing else.
VIEWER_ROLES = CLINICAL_ROLES | {Role.PATIENT}


class PainSiteRole(str, enum.Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    RADIATING = "RADIATING"
    REFERRED = "REFERRED"


class OnsetSpeed(str, enum.Enum):
    SECONDS = "SECONDS"
    MINUTES = "MINUTES"
    HOURS = "HOURS"
    DAYS = "DAYS"
    WEEKS_OR_MORE = "WEEKS_OR_MORE"
    UNKNOWN = "UNKNOWN"


class ReviewAgreement(str, enum.Enum):
    AGREE = "AGREE"
    PARTLY = "PARTLY"
    DISAGREE = "DISAGREE"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class Profession(str, enum.Enum):
    DOCTOR = "DOCTOR"
    NURSE = "NURSE"
    RESIDENT = "RESIDENT"
    OTHER = "OTHER"


class Sex(str, enum.Enum):
    F = "F"
    M = "M"
    OTHER = "OTHER"
    UNDISCLOSED = "UNDISCLOSED"


class SmokingStatus(str, enum.Enum):
    NEVER = "NEVER"
    FORMER = "FORMER"
    CURRENT = "CURRENT"
    UNKNOWN = "UNKNOWN"


class AssessmentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    VALIDATED = "VALIDATED"


class Onset(str, enum.Enum):
    SUDDEN = "SUDDEN"
    GRADUAL = "GRADUAL"
    UNKNOWN = "UNKNOWN"


class Pattern(str, enum.Enum):
    CONSTANT = "CONSTANT"
    INTERMITTENT = "INTERMITTENT"
    EPISODIC = "EPISODIC"
    UNKNOWN = "UNKNOWN"


class Course(str, enum.Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    WORSENING = "WORSENING"
    PROGRESSIVE = "PROGRESSIVE"
    UNKNOWN = "UNKNOWN"


class DocumentKind(str, enum.Enum):
    XRAY = "XRAY"
    WOUND_PHOTO = "WOUND_PHOTO"
    CT = "CT"
    MRI = "MRI"
    ULTRASOUND = "ULTRASOUND"
    ECG = "ECG"
    LABORATORY = "LABORATORY"
    REPORT = "REPORT"
    PRESCRIPTION = "PRESCRIPTION"
    OTHER = "OTHER"


class DataQuality(str, enum.Enum):
    GOOD = "GOOD"
    ADEQUATE = "ADEQUATE"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class PainLocation(Base):
    __tablename__ = "pain_locations"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(32), index=True)
    parent_code: Mapped[str | None] = mapped_column(String(48))


class AnatomicalRegion(Base):
    __tablename__ = "anatomical_regions"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    display_order: Mapped[int] = mapped_column(Integer, default=50)


class AnatomicalStructureType(Base):
    __tablename__ = "anatomical_structure_types"

    code: Mapped[str] = mapped_column(String(24), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=50)


class AnatomicalStructure(Base):
    __tablename__ = "anatomical_structures"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(160))
    latin: Mapped[str] = mapped_column(String(160), default="")
    structure_type: Mapped[str] = mapped_column(
        ForeignKey("anatomical_structure_types.code"), index=True
    )
    region: Mapped[str] = mapped_column(ForeignKey("anatomical_regions.code"), index=True)

    subregion: Mapped[str | None] = mapped_column(String(64), index=True)

    parent_code: Mapped[str | None] = mapped_column(String(48), index=True)
    location_code: Mapped[str] = mapped_column(ForeignKey("pain_locations.code"))
    location_left: Mapped[str | None] = mapped_column(String(48))
    location_right: Mapped[str | None] = mapped_column(String(48))
    laterality: Mapped[str] = mapped_column(String(16))
    system: Mapped[str | None] = mapped_column(String(32))
    synonyms: Mapped[list] = mapped_column(JSON, default=list)

    sex: Mapped[str | None] = mapped_column(String(8))

    has_mesh: Mapped[bool] = mapped_column(Boolean, default=True)
    pain_selectable: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")


class AnatomicalRelationship(Base):
    __tablename__ = "anatomical_relationships"
    __table_args__ = (UniqueConstraint("source_code", "target_code", "relation"),)

    id: Mapped[uuid.UUID] = _pk()
    source_code: Mapped[str] = mapped_column(
        ForeignKey("anatomical_structures.code"), index=True
    )
    target_code: Mapped[str] = mapped_column(
        ForeignKey("anatomical_structures.code"), index=True
    )
    relation: Mapped[str] = mapped_column(String(24), index=True)


class PainQuality(Base):
    __tablename__ = "pain_qualities"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    neuropathic_hint: Mapped[bool] = mapped_column(Boolean, default=False)


class PainType(Base):
    __tablename__ = "pain_types"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(24), index=True)
    parent_code: Mapped[str | None] = mapped_column(String(48))
    description: Mapped[str] = mapped_column(Text, default="")


class Symptom(Base):
    __tablename__ = "symptoms"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(24), index=True)
    systemic: Mapped[bool] = mapped_column(Boolean, default=False)
    alarm: Mapped[bool] = mapped_column(Boolean, default=False)


class Disease(Base):
    """A disease the platform knows about.

    The table serves two readers with different needs. The clinical forms offer it as the
    comorbidity list when recording a patient's history, and those forms must only ever
    show entries a clinician curated — see `curated`. The dataset dashboard shows every
    row, including the ones `app.sync` created when an external publisher turned out to
    hold data for a disease the platform had not heard of.

    Keeping both in one table is what lets an imported disease later be promoted to the
    clinical list by setting one flag, rather than being retyped somewhere else.
    """

    __tablename__ = "diseases"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32), index=True)
    pain_relevant: Mapped[bool] = mapped_column(Boolean, default=False)

    #: True for the entries seeded from `app.knowledge.diseases`, which a clinician may be
    #: offered when recording a patient's comorbidities. False for anything discovered
    #: automatically: present, visible, queryable, but not put in front of a clinician as
    #: a vetted option.
    curated: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="knowledge_base")
    source_ref: Mapped[str | None] = mapped_column(String(255))
    discovered_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class PainFactor(Base):
    __tablename__ = "pain_factors"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), index=True)


class Confounder(Base):
    __tablename__ = "confounders"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    affects: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")


class ClinicalQuestion(Base):
    __tablename__ = "clinical_questions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    group: Mapped[str] = mapped_column(String(24), index=True)
    options: Mapped[list] = mapped_column(JSON, default=list)
    unit: Mapped[str | None] = mapped_column(String(24))
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    help_text: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=50)


class ClinicalRule(Base):
    __tablename__ = "clinical_rules"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    points: Mapped[float] = mapped_column(Float)
    advice: Mapped[str] = mapped_column(Text)


class PainCause(Base):
    __tablename__ = "pain_causes"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    group: Mapped[str] = mapped_column(String(24), index=True)
    pain_types: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")


class MedicationClass(Base):
    __tablename__ = "medication_classes"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    analgesic: Mapped[bool] = mapped_column(Boolean, default=False)
    sedating: Mapped[bool] = mapped_column(Boolean, default=False)

    affects: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(190), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    clinic_name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(48))
    profession: Mapped[Profession] = _enum(Profession, default=Profession.DOCTOR)
    registration_number: Mapped[str | None] = mapped_column(String(48))
    speciality: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[Role] = _enum(Role, default=Role.DOCTOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    sessions_revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    #: Set on a PATIENT account only: the record that account is allowed to read.
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    patient: Mapped["Patient | None"] = relationship(foreign_keys=[patient_id])

    @property
    def patient_code(self) -> str | None:
        return self.patient.code if self.patient is not None else None


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sex: Mapped[Sex] = _enum(Sex, default=Sex.UNDISCLOSED)
    #: Age as entered at registration. The date of birth, when it is known, wins over it.
    age_years: Mapped[int | None] = mapped_column(Integer)
    birth_date: Mapped[date | None] = mapped_column(Date)
    ward: Mapped[str | None] = mapped_column(String(80))
    smoking_status: Mapped[SmokingStatus] = _enum(SmokingStatus, default=SmokingStatus.UNKNOWN)

    medical_history: Mapped[str | None] = mapped_column(Text)
    previous_surgeries: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[str | None] = mapped_column(Text)
    family_history: Mapped[str | None] = mapped_column(Text)
    lifestyle_notes: Mapped[str | None] = mapped_column(Text)

    identity_blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    identity_key: Mapped[bytes | None] = mapped_column(LargeBinary)

    # The population this patient is normally read as. An assessment records its own,
    # because a state such as pregnancy or critical care changes between visits.
    profile_code: Mapped[str | None] = mapped_column(String(48), index=True)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, onupdate=_now)

    conditions: Mapped[list["PatientCondition"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    medications: Mapped[list["PatientMedication"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["PainAssessment"]] = relationship(back_populates="patient")
    baseline: Mapped["PatientBaseline | None"] = relationship(
        back_populates="patient", cascade="all, delete-orphan", uselist=False
    )

    def age_on(self, moment: date) -> int | None:
        if self.birth_date is None:
            return self.age_years
        years = moment.year - self.birth_date.year
        if (moment.month, moment.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    def age_months_on(self, moment: date) -> int | None:
        """Whole months. Age in years cannot tell a newborn from a two-year-old, and the
        profiles that matter most are inside that first year."""
        if self.birth_date is None:
            return None
        months = (
            (moment.year - self.birth_date.year) * 12 + moment.month - self.birth_date.month
        )
        if moment.day < self.birth_date.day:
            months -= 1
        return max(months, 0)


class PatientCondition(Base):
    __tablename__ = "patient_conditions"
    __table_args__ = (UniqueConstraint("patient_id", "disease_code"),)

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    diagnosed_year: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    patient: Mapped[Patient] = relationship(back_populates="conditions")


class PatientMedication(Base):
    __tablename__ = "patient_medications"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    dose: Mapped[str | None] = mapped_column(String(80))
    frequency: Mapped[str | None] = mapped_column(String(80))
    started_on: Mapped[date | None] = mapped_column(Date)
    is_analgesic: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)

    patient: Mapped[Patient] = relationship(back_populates="medications")


class PainAssessment(Base):
    __tablename__ = "pain_assessments"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[AssessmentStatus] = _enum(AssessmentStatus, default=AssessmentStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, onupdate=_now)

    patient_age_years: Mapped[int | None] = mapped_column(Integer)
    patient_age_months: Mapped[int | None] = mapped_column(Integer)

    profile_code: Mapped[str | None] = mapped_column(String(48), index=True)
    profile_modifiers: Mapped[list] = mapped_column(JSON, default=list)
    pregnancy_trimester: Mapped[int | None] = mapped_column(Integer)
    # Pain the clinician expects for the situation, such as contractions in labour.
    expected_pain: Mapped[bool] = mapped_column(Boolean, default=False)

    onset: Mapped[Onset] = _enum(Onset, default=Onset.UNKNOWN)
    onset_speed: Mapped[OnsetSpeed] = _enum(OnsetSpeed, default=OnsetSpeed.UNKNOWN)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    #: The duration as the clinician typed it, and the same span in hours for the model.
    duration_value: Mapped[float | None] = mapped_column(Float)
    duration_unit: Mapped[str | None] = mapped_column(String(8))
    duration_hours: Mapped[float | None] = mapped_column(Float)
    pattern: Mapped[Pattern] = _enum(Pattern, default=Pattern.UNKNOWN)
    course: Mapped[Course] = _enum(Course, default=Course.UNKNOWN)
    episodes_per_day: Mapped[float | None] = mapped_column(Float)
    episode_minutes: Mapped[float | None] = mapped_column(Float)
    recurrent: Mapped[bool] = mapped_column(Boolean, default=False)

    night_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    morning_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    afternoon_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    evening_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    variable_timing: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_after_activity: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_at_rest: Mapped[bool] = mapped_column(Boolean, default=False)

    impact_mobility: Mapped[int | None] = mapped_column(Integer)
    impact_sleep: Mapped[int | None] = mapped_column(Integer)
    impact_work: Mapped[int | None] = mapped_column(Integer)
    impact_daily_activity: Mapped[int | None] = mapped_column(Integer)
    impact_self_care: Mapped[int | None] = mapped_column(Integer)

    review_agreement: Mapped[ReviewAgreement | None] = _enum(ReviewAgreement, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text)

    radiates: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_description: Mapped[str | None] = mapped_column(Text)
    radiation_numbness: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_tingling: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_weakness: Mapped[bool] = mapped_column(Boolean, default=False)

    recent_trauma: Mapped[bool] = mapped_column(Boolean, default=False)
    recent_surgery: Mapped[bool] = mapped_column(Boolean, default=False)

    # Free text beside the coded pickers, for whatever the vocabulary does not cover.
    symptoms_note: Mapped[str | None] = mapped_column(Text)
    aggravating_note: Mapped[str | None] = mapped_column(Text)
    relieving_note: Mapped[str | None] = mapped_column(Text)

    validated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    validated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    patient: Mapped[Patient] = relationship(back_populates="assessments")
    locations: Mapped[list["AssessmentLocation"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    anatomical_sites: Mapped[list["AssessmentAnatomicalSite"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    qualities: Mapped[list["AssessmentQuality"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    symptoms: Mapped[list["AssessmentSymptom"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    factors: Mapped[list["AssessmentFactor"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    confounders: Mapped[list["AssessmentConfounder"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    medications: Mapped[list["AssessmentMedication"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    measurement: Mapped["PhysiologicalMeasurement | None"] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    self_report: Mapped["SelfReport | None"] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    prediction: Mapped["PainPrediction | None"] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    observations: Mapped[list["BehaviourObservation"]] = relationship(
        back_populates="assessment", order_by="BehaviourObservation.recorded_at.desc()"
    )
    documents: Mapped[list["MedicalDocument"]] = relationship(back_populates="assessment")
    notes: Mapped[list["ClinicalNote"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentLocation(Base):
    __tablename__ = "assessment_locations"
    __table_args__ = (UniqueConstraint("assessment_id", "location_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    location_code: Mapped[str] = mapped_column(ForeignKey("pain_locations.code"))
    side: Mapped[str] = mapped_column(String(16), default="NOT_APPLICABLE")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    assessment: Mapped[PainAssessment] = relationship(back_populates="locations")


class AssessmentAnatomicalSite(Base):
    __tablename__ = "assessment_anatomical_sites"
    __table_args__ = (UniqueConstraint("assessment_id", "structure_code", "side"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    structure_code: Mapped[str] = mapped_column(ForeignKey("anatomical_structures.code"))
    side: Mapped[str] = mapped_column(String(16), default="MIDLINE")
    role: Mapped[PainSiteRole] = _enum(PainSiteRole, default=PainSiteRole.SECONDARY)

    sequence: Mapped[int] = mapped_column(Integer, default=0)
    radiation_from_code: Mapped[str | None] = mapped_column(String(48))
    radiation_from_side: Mapped[str | None] = mapped_column(String(16))
    quality_codes: Mapped[list] = mapped_column(JSON, default=list)
    onset: Mapped[Onset] = _enum(Onset, default=Onset.UNKNOWN)
    pattern: Mapped[Pattern] = _enum(Pattern, default=Pattern.UNKNOWN)
    course: Mapped[Course] = _enum(Course, default=Course.UNKNOWN)
    intensity: Mapped[float | None] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[PainAssessment] = relationship(back_populates="anatomical_sites")


class AssessmentQuality(Base):
    __tablename__ = "assessment_qualities"
    __table_args__ = (UniqueConstraint("assessment_id", "quality_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    quality_code: Mapped[str] = mapped_column(ForeignKey("pain_qualities.code"))

    assessment: Mapped[PainAssessment] = relationship(back_populates="qualities")


class AssessmentSymptom(Base):
    __tablename__ = "assessment_symptoms"
    __table_args__ = (UniqueConstraint("assessment_id", "symptom_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    symptom_code: Mapped[str] = mapped_column(ForeignKey("symptoms.code"))

    assessment: Mapped[PainAssessment] = relationship(back_populates="symptoms")


class AssessmentFactor(Base):
    __tablename__ = "assessment_factors"
    __table_args__ = (UniqueConstraint("assessment_id", "factor_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    factor_code: Mapped[str] = mapped_column(ForeignKey("pain_factors.code"))

    assessment: Mapped[PainAssessment] = relationship(back_populates="factors")


class AssessmentConfounder(Base):
    __tablename__ = "assessment_confounders"
    __table_args__ = (UniqueConstraint("assessment_id", "confounder_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    confounder_code: Mapped[str] = mapped_column(ForeignKey("confounders.code"))
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[PainAssessment] = relationship(back_populates="confounders")


class AssessmentMedication(Base):
    __tablename__ = "assessment_medications"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    class_code: Mapped[str] = mapped_column(ForeignKey("medication_classes.code"))
    name: Mapped[str | None] = mapped_column(String(160))
    dose_category: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    frequency: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    hours_since_last_dose: Mapped[float | None] = mapped_column(Float)
    pain_effect: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    sedation_effect: Mapped[str] = mapped_column(String(16), default="UNKNOWN")

    assessment: Mapped[PainAssessment] = relationship(back_populates="medications")


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"
    __table_args__ = (UniqueConstraint("assessment_id", "question_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    question_code: Mapped[str] = mapped_column(ForeignKey("clinical_questions.code"))

    value: Mapped[object] = mapped_column(JSON)

    assessment: Mapped[PainAssessment] = relationship(back_populates="answers")


class PhysiologicalMeasurement(Base):
    __tablename__ = "physiological_measurements"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True, unique=True
    )
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    hr: Mapped[float | None] = mapped_column(Float)
    resp_rate: Mapped[float | None] = mapped_column(Float)
    sbp: Mapped[float | None] = mapped_column(Float)
    dbp: Mapped[float | None] = mapped_column(Float)
    spo2: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    glucose_mmol: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)

    assessment: Mapped[PainAssessment] = relationship(back_populates="measurement")

    @property
    def bmi(self) -> float | None:
        if not self.weight_kg or not self.height_cm:
            return None
        return round(self.weight_kg / (self.height_cm / 100) ** 2, 1)


class SelfReport(Base):
    __tablename__ = "self_reports"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True, unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    # The score projected onto the 0-10 axis, whatever instrument produced it. This is the
    # reference the estimate is compared against and the regression target.
    nrs: Mapped[float] = mapped_column(Float)
    # Which instrument it came from, and the score as that instrument records it. Kept so
    # the projection onto 0-10 is never the only thing left.
    scale_code: Mapped[str] = mapped_column(String(16), default="NRS", index=True)
    raw_score: Mapped[float | None] = mapped_column(Float)
    raw_max: Mapped[float | None] = mapped_column(Float)
    # Per-item scores, for an observational scale totalled from items.
    items: Mapped[dict] = mapped_column(JSON, default=dict)
    # True where a clinician scored an observational scale because the patient could not
    # be asked. The reference is then an observation, not a self-report.
    observed: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[PainAssessment] = relationship(back_populates="self_report")


class PatientBaseline(Base):
    """A short calibration taken with the patient at rest, which later readings are
    compared against. One per patient; recording a new one replaces it."""

    __tablename__ = "patient_baselines"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id"), index=True, unique=True
    )
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # How many readings at rest the values below are the median of.
    readings: Mapped[int] = mapped_column(Integer, default=1)
    minutes_at_rest: Mapped[float | None] = mapped_column(Float)
    hr: Mapped[float | None] = mapped_column(Float)
    resp_rate: Mapped[float | None] = mapped_column(Float)
    sbp: Mapped[float | None] = mapped_column(Float)
    dbp: Mapped[float | None] = mapped_column(Float)
    spo2: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)

    #: This patient's resting behaviour, from an observation recorded at rest. Separate
    #: from the vitals above because it is recorded by a different act — a short clip
    #: rather than a cuff and a thermometer — and is often absent when they are present.
    #: Orbital tightening and brow lowering are meaningless without these, so a platform
    #: that never records them can only ever compare a patient against an average.
    behaviour_recorded_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    resting_eye_aperture: Mapped[float | None] = mapped_column(Float)
    resting_pupil_mm: Mapped[float | None] = mapped_column(Float)
    resting_blink_rate: Mapped[float | None] = mapped_column(Float)
    resting_brow_gap: Mapped[float | None] = mapped_column(Float)
    resting_f0_hz: Mapped[float | None] = mapped_column(Float)
    resting_intensity_db: Mapped[float | None] = mapped_column(Float)
    resting_speech_rate: Mapped[float | None] = mapped_column(Float)

    patient: Mapped[Patient] = relationship(back_populates="baseline")

    @property
    def behaviour(self) -> dict[str, float]:
        """The resting behaviour, under the measure codes the extractor uses."""
        pairs = (
            ("eye_aperture_ratio", self.resting_eye_aperture),
            ("pupil_diameter_mm", self.resting_pupil_mm),
            ("blink_rate_per_min", self.resting_blink_rate),
            ("brow_gap_ratio", self.resting_brow_gap),
            ("f0_mean_hz", self.resting_f0_hz),
            ("intensity_db", self.resting_intensity_db),
            ("speech_rate_per_s", self.resting_speech_rate),
        )
        return {name: float(value) for name, value in pairs if value is not None}

    @property
    def vitals(self) -> dict[str, float]:
        out = {}
        for name in ("hr", "resp_rate", "sbp", "dbp", "spo2", "temperature_c"):
            value = getattr(self, name)
            if value is not None:
                out[name] = float(value)
        return out


class MedicalDocument(Base):
    __tablename__ = "medical_documents"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    kind: Mapped[DocumentKind] = _enum(DocumentKind, default=DocumentKind.OTHER)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    findings: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    assessment: Mapped["PainAssessment | None"] = relationship(back_populates="documents")


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)

    assessment: Mapped[PainAssessment] = relationship(back_populates="notes")


class PainPrediction(Base):
    __tablename__ = "pain_predictions"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True, unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)

    model_name: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    dataset_version: Mapped[str | None] = mapped_column(String(64))
    feature_schema_version: Mapped[str | None] = mapped_column(String(16))
    inference_ms: Mapped[float | None] = mapped_column(Float)

    estimated_pain: Mapped[float | None] = mapped_column(Float)
    interval_low: Mapped[float | None] = mapped_column(Float)
    interval_high: Mapped[float | None] = mapped_column(Float)
    band: Mapped[str | None] = mapped_column(String(16))

    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_level: Mapped[str | None] = mapped_column(String(16))
    priority_factors: Mapped[list] = mapped_column(JSON, default=list)

    trajectory: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)

    profile_code: Mapped[str | None] = mapped_column(String(48), index=True)
    profile_modifiers: Mapped[list] = mapped_column(JSON, default=list)
    # The scale this estimate is to be compared against, and whether the patient could be
    # asked at all.
    reference_scale: Mapped[str | None] = mapped_column(String(16))
    can_self_report: Mapped[bool] = mapped_column(Boolean, default=True)
    # How much of the interval width was handed back for the profile alone.
    profile_penalty: Mapped[float] = mapped_column(Float, default=0.0)

    data_quality: Mapped[DataQuality] = _enum(DataQuality, default=DataQuality.ADEQUATE)
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    quality_issues: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)

    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    refusal_reason: Mapped[str | None] = mapped_column(Text)

    features: Mapped[dict] = mapped_column(JSON, default=dict)
    confounder_notes: Mapped[list] = mapped_column(JSON, default=list)

    assessment: Mapped[PainAssessment] = relationship(back_populates="prediction")
    contributions: Mapped[list["PredictionContribution"]] = relationship(
        back_populates="prediction", cascade="all, delete-orphan"
    )
    categories: Mapped[list["PredictionCategory"]] = relationship(
        back_populates="prediction", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["PredictionAlert"]] = relationship(
        back_populates="prediction", cascade="all, delete-orphan"
    )


class PredictionContribution(Base):
    __tablename__ = "prediction_contributions"

    id: Mapped[uuid.UUID] = _pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_predictions.id"), index=True
    )
    feature: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(160))
    contribution: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)

    prediction: Mapped[PainPrediction] = relationship(back_populates="contributions")


class PredictionCategory(Base):
    __tablename__ = "prediction_categories"

    id: Mapped[uuid.UUID] = _pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_predictions.id"), index=True
    )
    cause_code: Mapped[str] = mapped_column(ForeignKey("pain_causes.code"))
    score: Mapped[float] = mapped_column(Float)
    matched: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)

    prediction: Mapped[PainPrediction] = relationship(back_populates="categories")


class PredictionAlert(Base):
    __tablename__ = "prediction_alerts"

    id: Mapped[uuid.UUID] = _pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_predictions.id"), index=True
    )
    rule_code: Mapped[str] = mapped_column(ForeignKey("clinical_rules.code"))
    severity: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(Text)
    advice: Mapped[str] = mapped_column(Text)
    context_notes: Mapped[list] = mapped_column(JSON, default=list)

    prediction: Mapped[PainPrediction] = relationship(back_populates="alerts")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = _pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    generator_version: Mapped[str] = mapped_column(String(16), default="1")
    seed: Mapped[int] = mapped_column(Integer)
    n_rows: Mapped[int] = mapped_column(Integer)
    n_patients: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    storage_format: Mapped[str] = mapped_column(String(16), default="jsonl")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    scenario_versions: Mapped[dict] = mapped_column(JSON, default=dict)

    split: Mapped[dict] = mapped_column(JSON, default=dict)
    distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    path: Mapped[str] = mapped_column(String(255))


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = _pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model_name: Mapped[str] = mapped_column(String(64), default="pain-model")
    algorithm: Mapped[str] = mapped_column(String(80))
    trained_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    dataset_version: Mapped[str] = mapped_column(String(64))
    feature_schema_version: Mapped[str] = mapped_column(String(16), default="1")
    n_train: Mapped[int] = mapped_column(Integer)
    n_validation: Mapped[int] = mapped_column(Integer, default=0)
    n_test: Mapped[int] = mapped_column(Integer)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    r2: Mapped[float] = mapped_column(Float)
    pearson: Mapped[float] = mapped_column(Float)

    f1_band: Mapped[float | None] = mapped_column(Float)
    inference_ms: Mapped[float | None] = mapped_column(Float)
    cv_folds: Mapped[int] = mapped_column(Integer)
    cv_mae_mean: Mapped[float] = mapped_column(Float)
    cv_mae_sd: Mapped[float] = mapped_column(Float)
    residual_sd: Mapped[float] = mapped_column(Float)
    features: Mapped[list] = mapped_column(JSON, default=list)
    feature_importance: Mapped[list] = mapped_column(JSON, default=list)

    comparison: Mapped[list] = mapped_column(JSON, default=list)

    training_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    # Band confusion matrix, precision and recall per band, the under-estimation analysis,
    # and the same figures per patient profile and per reference scale.
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[JobStatus] = _enum(JobStatus, default=JobStatus.QUEUED, index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _pk()

    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str | None] = mapped_column(String(190))
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    resource: Mapped[str | None] = mapped_column(String(48))
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    entry_hash: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str] = mapped_column(String(64))


class LedgerBlock(Base):
    __tablename__ = "ledger_blocks"

    id: Mapped[uuid.UUID] = _pk()
    height: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    event_type: Mapped[str] = mapped_column(String(48))
    resource: Mapped[str] = mapped_column(String(48))
    record_id: Mapped[str] = mapped_column(String(64), index=True)
    record_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    previous_hash: Mapped[str] = mapped_column(String(64))
    block_hash: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[bytes] = mapped_column(LargeBinary)
    signature_scheme: Mapped[str] = mapped_column(String(48))

    key_id: Mapped[str] = mapped_column(String(48), default="ledger-signing-v1")


class KeyMetadata(Base):
    __tablename__ = "key_metadata"
    __table_args__ = (UniqueConstraint("label", "version"),)

    id: Mapped[uuid.UUID] = _pk()
    label: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    purpose: Mapped[str] = mapped_column(String(48))
    algorithm: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    rotated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    retired_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SourceAccess(str, enum.Enum):
    """What the publisher permits, in the publisher's own terms."""

    OPEN = "OPEN"
    REGISTRATION_REQUIRED = "REGISTRATION_REQUIRED"
    CREDENTIALED = "CREDENTIALED"
    AGREEMENT_REQUIRED = "AGREEMENT_REQUIRED"
    DOCUMENT_ONLY = "DOCUMENT_ONLY"
    UNKNOWN = "UNKNOWN"


#: The statuses under which this platform is willing to retrieve files. Everything else is
#: recorded with its access procedure and left on the publisher's server.
DOWNLOADABLE_ACCESS = frozenset({SourceAccess.OPEN})


class Availability(str, enum.Enum):
    """What this platform actually holds, which is a different question from access."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    METADATA_ONLY = "METADATA_ONLY"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"


class LicenceVerdict(str, enum.Enum):
    """What the publisher's licence permits this platform to do with a copy.

    `RESEARCH_ONLY` is its own verdict rather than a flavour of either neighbour because
    it is the common case and the two halves of it differ: a CC BY-NC-SA dataset may be
    retrieved and analysed here, and may not be redistributed or used commercially. Folding
    it into `PERMISSIVE` would lose the second half; folding it into `RESTRICTED` would
    wrongly exclude most of what WHO publishes.
    """

    PERMISSIVE = "PERMISSIVE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


#: Verdicts under which an unattended worker may retrieve a copy. Everything else waits
#: for a person to read the licence and record a decision.
RETRIEVABLE_LICENCES = frozenset({LicenceVerdict.PERMISSIVE, LicenceVerdict.RESEARCH_ONLY})


class Granularity(str, enum.Enum):
    """Whether rows describe individuals or populations.

    The distinction decides whether a dataset can carry a supervised per-subject target at
    all, so it is recorded explicitly rather than guessed at training time.
    """

    SUBJECT_LEVEL = "SUBJECT_LEVEL"
    AGGREGATE = "AGGREGATE"
    UNKNOWN = "UNKNOWN"


class QualityStatus(str, enum.Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    FAILED = "FAILED"


class SyncStage(str, enum.Enum):
    DISCOVER = "DISCOVER"
    IDENTIFY_DISEASE = "IDENTIFY_DISEASE"
    ACQUIRE = "ACQUIRE"
    VALIDATE = "VALIDATE"
    PREPROCESS = "PREPROCESS"
    SUITABILITY = "SUITABILITY"
    TRAIN = "TRAIN"


class SyncOutcome(str, enum.Enum):
    OK = "OK"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class RunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class ExternalSource(Base):
    """A publisher this platform polls.

    The row holds the schedule and the search configuration; the adapter that knows how to
    talk to the publisher lives in `app.sync.sources` and is looked up by `code`. A source
    whose adapter has been removed therefore stays visible as a disabled row rather than
    vanishing with its history.
    """

    __tablename__ = "external_sources"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    organisation: Mapped[str] = mapped_column(String(160))
    homepage: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class ExternalDataset(Base):
    """One dataset the platform knows about, obtained or not.

    An entry exists from the moment the dataset is discovered. A dataset behind a signed
    agreement is therefore present with its real access status and the procedure a person
    would follow, instead of being silently absent.

    `metadata_fingerprint` is a digest of the publisher's description of the dataset. It is
    what makes "has this changed?" answerable without downloading anything, and it is
    deliberately separate from the content digest on each version row.
    """

    __tablename__ = "external_datasets"
    __table_args__ = (UniqueConstraint("source_code", "external_id"),)

    id: Mapped[uuid.UUID] = _pk()
    source_code: Mapped[str] = mapped_column(
        ForeignKey("external_sources.code"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(400))
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(500))
    download_url: Mapped[str | None] = mapped_column(String(1000))
    download_mechanism: Mapped[str] = mapped_column(String(80), default="")

    disease_code: Mapped[str | None] = mapped_column(ForeignKey("diseases.code"), index=True)
    disease_match: Mapped[dict] = mapped_column(JSON, default=dict)

    dataset_type: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    granularity: Mapped[Granularity] = _enum(Granularity, default=Granularity.UNKNOWN)
    modalities: Mapped[list] = mapped_column(JSON, default=list)
    target_labels: Mapped[list] = mapped_column(JSON, default=list)

    access_status: Mapped[SourceAccess] = _enum(
        SourceAccess, default=SourceAccess.UNKNOWN, index=True
    )
    access_procedure: Mapped[list] = mapped_column(JSON, default=list)
    licence: Mapped[str | None] = mapped_column(String(255))
    licence_url: Mapped[str | None] = mapped_column(String(500))
    licence_verdict: Mapped[LicenceVerdict] = _enum(
        LicenceVerdict, default=LicenceVerdict.UNKNOWN
    )
    redistribution: Mapped[str] = mapped_column(
        String(255), default="not redistributed by this platform"
    )

    publisher_version: Mapped[str | None] = mapped_column(String(64))
    publisher_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    records_claimed: Mapped[int | None] = mapped_column(Integer)
    relevance: Mapped[int] = mapped_column(Integer, default=0, index=True)

    availability: Mapped[Availability] = _enum(
        Availability, default=Availability.NOT_ATTEMPTED, index=True
    )
    metadata_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    last_checked_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    changed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")

    versions: Mapped[list["ExternalDatasetVersion"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="ExternalDatasetVersion.acquired_at.desc()",
    )


class ExternalDatasetVersion(Base):
    """One acquired copy of a dataset, with the provenance of that copy.

    `sha256` is over the bytes as they arrived. Together with the unique constraint it is
    the duplicate check: re-fetching an unchanged dataset finds the digest already present
    and records a skip instead of a second copy.

    `records` is measured from the stored file. `ExternalDataset.records_claimed` is what
    the publisher said. The two never overwrite each other.
    """

    __tablename__ = "external_dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "sha256"),
        UniqueConstraint("dataset_id", "version"),
    )

    id: Mapped[uuid.UUID] = _pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("external_datasets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(64))
    acquired_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    source_url: Mapped[str] = mapped_column(String(1000))
    licence: Mapped[str | None] = mapped_column(String(255))

    storage_backend: Mapped[str] = mapped_column(String(16), default="filesystem")
    storage_key: Mapped[str] = mapped_column(String(500))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_format: Mapped[str] = mapped_column(String(16), default="")
    file_count: Mapped[int] = mapped_column(Integer, default=1)
    manifest: Mapped[list] = mapped_column(JSON, default=list)

    records: Mapped[int | None] = mapped_column(Integer)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    missing_value_pct: Mapped[float | None] = mapped_column(Float)
    quality_status: Mapped[QualityStatus] = _enum(
        QualityStatus, default=QualityStatus.NOT_ASSESSED, index=True
    )
    quality_findings: Mapped[list] = mapped_column(JSON, default=list)
    preprocessed_key: Mapped[str | None] = mapped_column(String(500))

    suitability: Mapped[dict] = mapped_column(JSON, default=dict)
    trainable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    training_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("background_jobs.id"))

    dataset: Mapped[ExternalDataset] = relationship(back_populates="versions")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = _pk()
    source_code: Mapped[str] = mapped_column(String(32), index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")
    status: Mapped[RunStatus] = _enum(RunStatus, default=RunStatus.RUNNING, index=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("background_jobs.id"))


class SyncEvent(Base):
    """The synchronisation log: one row per stage outcome, successful or not.

    A dataset that was not downloaded has a reason on file here rather than simply not
    being there, which is what makes the pipeline auditable after the fact.
    """

    __tablename__ = "sync_events"

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("external_datasets.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    source_code: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(255), default="")
    stage: Mapped[SyncStage] = _enum(SyncStage, index=True)
    outcome: Mapped[SyncOutcome] = _enum(SyncOutcome, index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# --- burn assessment -------------------------------------------------------------------


class BurnDepth(str, enum.Enum):
    SUPERFICIAL_EPIDERMAL = "SUPERFICIAL_EPIDERMAL"
    SUPERFICIAL_PARTIAL = "SUPERFICIAL_PARTIAL"
    DEEP_PARTIAL = "DEEP_PARTIAL"
    FULL_THICKNESS = "FULL_THICKNESS"
    UNCERTAIN = "UNCERTAIN"


class TbsaMethod(str, enum.Enum):
    LUND_BROWDER = "LUND_BROWDER"
    RULE_OF_NINES = "RULE_OF_NINES"
    PALM = "PALM"


class Attribution(str, enum.Enum):
    """Who or what established a finding.

    Carried on every clinical value the burn module stores, because the whole module
    depends on never letting one of these quietly become another. A model's suggestion
    and a clinician's confirmation are different kinds of statement and the report prints
    them in separate columns.
    """

    PATIENT = "PATIENT"
    CLINICIAN = "CLINICIAN"
    MODEL = "MODEL"


class ReviewState(str, enum.Enum):
    DRAFT = "DRAFT"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    CONFIRMED = "CONFIRMED"
    AMENDED = "AMENDED"


class AlertSeverity(str, enum.Enum):
    #: Deliberately not "critical" or "emergency". These flags ask a clinician to look;
    #: they do not triage, and nothing here should read as a decision already taken.
    REVIEW = "REVIEW"
    URGENT_REVIEW = "URGENT_REVIEW"


class PatientConsent(Base):
    """A recorded consent, with what it covers and when it was withdrawn.

    Withdrawal does not delete the row. A record that consent existed, and when it ended,
    is what makes it possible to say afterwards whether an image held at a given moment
    was held lawfully.
    """

    __tablename__ = "patient_consents"
    __table_args__ = (UniqueConstraint("patient_id", "scope"),)

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    scope: Mapped[str] = mapped_column(String(48), index=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)

    @property
    def active(self) -> bool:
        return self.granted and self.withdrawn_at is None


class BurnIncident(Base):
    __tablename__ = "burn_incidents"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    cause: Mapped[str] = mapped_column(String(24), index=True)
    cause_detail: Mapped[str | None] = mapped_column(Text)
    #: What was done before the patient was seen, as reported. Recorded as free text
    #: because first aid at the scene rarely fits a vocabulary.
    first_aid: Mapped[str | None] = mapped_column(Text)
    enclosed_space: Mapped[bool | None] = mapped_column(Boolean)
    #: Reported symptoms that bear on airway involvement. Stored as the patient or
    #: clinician reported them; nothing here infers an inhalation injury.
    airway_symptoms: Mapped[list] = mapped_column(JSON, default=list)
    symptoms: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)

    assessments: Mapped[list["BurnAssessment"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="BurnAssessment.assessed_at",
    )

    @property
    def hours_since(self) -> float | None:
        if self.occurred_at is None:
            return None
        return round((_now() - self.occurred_at).total_seconds() / 3600, 2)


class BurnAssessment(Base):
    """One assessment of an incident at a point in time.

    An incident has several: the first in the emergency department, then one at each
    review. Each carries its own regions, its own surface area estimate and its own
    review state, so progression is a sequence of assessments rather than a row that gets
    overwritten.
    """

    __tablename__ = "burn_assessments"

    id: Mapped[uuid.UUID] = _pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    assessed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    assessed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    #: The patient's age at assessment, which decides the Lund-Browder column. Stored
    #: rather than recomputed so a historical estimate stays reproducible.
    age_years: Mapped[float | None] = mapped_column(Float)
    state: Mapped[ReviewState] = _enum(ReviewState, default=ReviewState.DRAFT, index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[BurnIncident] = relationship(back_populates="assessments")
    regions: Mapped[list["BurnRegion"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )
    calculations: Mapped[list["TbsaCalculation"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="TbsaCalculation.calculated_at.desc()",
    )
    alerts: Mapped[list["BurnAlert"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class BurnRegion(Base):
    """One burned body region within an assessment.

    Depth is recorded twice on purpose. `depth` is what the assessment currently holds and
    what the surface area is costed from; `suggested_depth` is what a model proposed, kept
    alongside with its confidence and never promoted automatically. `depth_attribution`
    says which of the two the current value came from.
    """

    __tablename__ = "burn_regions"
    __table_args__ = (UniqueConstraint("assessment_id", "region_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_assessments.id", ondelete="CASCADE"), index=True
    )
    region_code: Mapped[str] = mapped_column(String(32), index=True)
    #: How much of the region is involved, 0 to 1.
    fraction: Mapped[float] = mapped_column(Float, default=1.0)
    depth: Mapped[BurnDepth] = _enum(BurnDepth, default=BurnDepth.UNCERTAIN)
    depth_attribution: Mapped[Attribution] = _enum(Attribution, default=Attribution.CLINICIAN)
    suggested_depth: Mapped[BurnDepth | None] = _enum(BurnDepth, nullable=True)
    suggested_confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    circumferential: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Free-hand marks from the body chart, as normalised coordinates. Kept opaque here:
    #: the surface area is costed from `fraction`, never from the drawing.
    marks: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[BurnAssessment] = relationship(back_populates="regions")


class TbsaCalculation(Base):
    """A surface area estimate, with everything needed to reproduce it.

    The breakdown is stored rather than recomputed on read. A chart is reference data that
    could be corrected later, and a resuscitation decision taken on Tuesday has to remain
    inspectable as the number it actually was.
    """

    __tablename__ = "tbsa_calculations"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_assessments.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[TbsaMethod] = _enum(TbsaMethod, index=True)
    total_percent: Mapped[float] = mapped_column(Float)
    excluded_superficial_percent: Mapped[float] = mapped_column(Float, default=0.0)
    age_years: Mapped[float | None] = mapped_column(Float)
    age_band: Mapped[str] = mapped_column(String(16))
    palms: Mapped[float | None] = mapped_column(Float)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    breakdown: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    formula: Mapped[str] = mapped_column(Text, default="")
    attribution: Mapped[Attribution] = _enum(Attribution, default=Attribution.CLINICIAN)
    #: A clinician's own figure, where they overrode the calculation. The computed total
    #: is kept beside it rather than replaced.
    clinician_percent: Mapped[float | None] = mapped_column(Float)
    clinician_note: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    calculated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    assessment: Mapped[BurnAssessment] = relationship(back_populates="calculations")

    @property
    def effective_percent(self) -> float:
        return self.clinician_percent if self.clinician_percent is not None else self.total_percent


class BurnPainReport(Base):
    """Pain around a burn, recorded on the scales the platform already carries.

    A burn is painful in several distinct situations and one number does not describe it:
    the brief asks for rest, movement, wound care and dressing changes separately, and
    they routinely differ by several points. Each is optional, because a patient asked
    four questions at a dressing change will answer the one that matters to them.

    `scale_code` names the instrument from `app.knowledge.scales`, so an observational
    score for a patient who cannot self-report is stored the same way with `observed` set.
    """

    __tablename__ = "burn_pain_reports"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    care_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wound_care_events.id", ondelete="SET NULL"), index=True
    )
    reported_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    scale_code: Mapped[str] = mapped_column(String(16), default="NRS", index=True)
    observed: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution: Mapped[Attribution] = _enum(Attribution, default=Attribution.PATIENT)

    current_nrs: Mapped[float | None] = mapped_column(Float)
    at_rest_nrs: Mapped[float | None] = mapped_column(Float)
    on_movement_nrs: Mapped[float | None] = mapped_column(Float)
    during_care_nrs: Mapped[float | None] = mapped_column(Float)
    before_care_nrs: Mapped[float | None] = mapped_column(Float)
    after_care_nrs: Mapped[float | None] = mapped_column(Float)

    #: Per-item scores where the instrument is totalled from items, as FLACC and NIPS are.
    items: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_score: Mapped[float | None] = mapped_column(Float)
    raw_max: Mapped[float | None] = mapped_column(Float)

    qualities: Mapped[list] = mapped_column(JSON, default=list)
    region_codes: Mapped[list] = mapped_column(JSON, default=list)
    duration_hours: Mapped[float | None] = mapped_column(Float)
    disturbs_sleep: Mapped[bool | None] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class WoundImage(Base):
    """A wound photograph.

    The bytes live in the existing encrypted document store — `MedicalDocument` already
    wraps a per-file key and records the digest — and this row carries what makes the
    image a wound photograph: which region, which assessment, whether consent covered it
    and what the capture quality was.
    """

    __tablename__ = "wound_images"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medical_documents.id", ondelete="CASCADE"), unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("burn_assessments.id", ondelete="SET NULL"), index=True
    )
    care_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("wound_care_events.id", ondelete="SET NULL"), index=True
    )
    region_code: Mapped[str | None] = mapped_column(String(32), index=True)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    #: The consent row that covered this capture, resolved at upload time. An image with
    #: no covering consent is refused rather than stored.
    consent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient_consents.id"))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text)

    analyses: Mapped[list["ImageAnalysis"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )


class ImageAnalysis(Base):
    """What a model said about one image.

    Never written into `BurnRegion.depth`. A suggestion reaches the assessment only when a
    clinician confirms it, and `accepted_by` records who did.
    """

    __tablename__ = "image_analyses"

    id: Mapped[uuid.UUID] = _pk()
    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wound_images.id", ondelete="CASCADE"), index=True
    )
    model_version: Mapped[str] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(32), index=True)
    analysed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    #: Share of the image the model marked as burned. An image fraction, not a body
    #: surface fraction: the two are only related if the photograph framed the region.
    burn_area_fraction: Mapped[float | None] = mapped_column(Float)
    suggested_depth: Mapped[BurnDepth | None] = _enum(BurnDepth, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    mask_storage_name: Mapped[str | None] = mapped_column(String(80))
    quality_warnings: Mapped[list] = mapped_column(JSON, default=list)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    image: Mapped[WoundImage] = relationship(back_populates="analyses")


class WoundCareEvent(Base):
    """One episode of wound care, as the clinician who did it recorded it.

    Every clinical field is free text or a clinician-chosen value. Nothing here proposes a
    cleaning solution, a dressing or a debridement: the module documents what was done,
    and the care plan it documents against is written by a clinician.
    """

    __tablename__ = "wound_care_events"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    performed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    performed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    region_codes: Mapped[list] = mapped_column(JSON, default=list)
    assessment_before: Mapped[str | None] = mapped_column(Text)
    cleaning: Mapped[str | None] = mapped_column(Text)
    solution: Mapped[str | None] = mapped_column(String(255))
    dressing: Mapped[str | None] = mapped_column(String(255))
    tolerance: Mapped[str | None] = mapped_column(String(32))
    analgesia_given: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    next_review_on: Mapped[date | None] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class FollowUpVisit(Base):
    __tablename__ = "follow_up_visits"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[date | None] = mapped_column(Date, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("burn_assessments.id", ondelete="SET NULL")
    )
    #: A clinician's judgement, never inferred from image similarity. Healing is a
    #: clinical finding and two photographs looking alike is not evidence of it.
    healing_state: Mapped[str | None] = mapped_column(String(32))
    clinician_note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class BurnAlert(Base):
    """A flag asking a clinician to look at something.

    Not a triage decision and not an emergency call. The wording of every rule says what
    was observed and why it warrants review, and the interface shows the local emergency
    contact alongside rather than implying the platform has handled it.
    """

    __tablename__ = "burn_alerts"
    __table_args__ = (UniqueConstraint("assessment_id", "code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_assessments.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[AlertSeverity] = _enum(AlertSeverity, index=True)
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    raised_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    assessment: Mapped[BurnAssessment] = relationship(back_populates="alerts")


class ClinicalReport(Base):
    """A generated report, with the content it was generated from.

    `content` is the assembled report as rendered, so re-reading a report shows what was
    approved rather than what the current data would produce now.
    """

    __tablename__ = "clinical_reports"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("burn_incidents.id", ondelete="CASCADE"), index=True
    )
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    language: Mapped[str] = mapped_column(String(8), default="en")
    state: Mapped[ReviewState] = _enum(ReviewState, default=ReviewState.DRAFT, index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    includes_images: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    sha256: Mapped[str | None] = mapped_column(String(64))


# --- EEG and EMG analysis ---------------------------------------------------------------


class SignalSource(str, enum.Enum):
    """Where a recording's samples came from.

    Not nullable and not defaulted anywhere. The brief's rule is that simulated and real
    measurements must never sit together without a visible source, and the way to guarantee
    that is to make it a required column rather than a flag someone can forget.
    """

    HARDWARE = "HARDWARE"
    SIMULATION = "SIMULATION"


class RecordingState(str, enum.Enum):
    RECORDING = "RECORDING"
    PROCESSING = "PROCESSING"
    #: Written and validated, waiting for the operator to ask for an analysis. Analysis is a
    #: separate step so a session can be saved at the bedside and analysed later, and so a
    #: failed analysis does not put the recording itself in doubt.
    SAVED = "SAVED"
    ANALYSED = "ANALYSED"
    #: Stopped without usable samples, or abandoned. The row stays so a reader can see the
    #: attempt happened rather than finding a gap.
    DISCARDED = "DISCARDED"
    FAILED = "FAILED"


class SignalRecording(Base):
    """One EEG and EMG acquisition session."""

    __tablename__ = "signal_recordings"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    source: Mapped[SignalSource] = _enum(SignalSource, index=True)
    state: Mapped[RecordingState] = _enum(
        RecordingState, default=RecordingState.RECORDING, index=True
    )
    device_label: Mapped[str | None] = mapped_column(String(120))
    #: Which acquisition adapter produced this, and the port or address it used. Null for a
    #: simulated recording and for samples relayed by a client that owns the device itself.
    adapter: Mapped[str | None] = mapped_column(String(32), index=True)
    device_identifier: Mapped[str | None] = mapped_column(String(255))

    #: The nominal rate of the primary (EEG) channels, kept for display and for the many
    #: readers that want one number.
    sample_rate_hz: Mapped[float] = mapped_column(Float)
    #: The rate each channel was actually recorded at. EEG at 250 Hz beside surface EMG at
    #: 1 kHz is the normal case, not an exception, so a single rate for the session would be
    #: wrong for one of them. This is the authoritative record and `sample_rate_hz` is a
    #: convenience derived from it.
    channel_rates: Mapped[dict] = mapped_column(JSON, default=dict)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    #: Per-channel presence as the acquisition reported it, before any quality assessment.
    sensor_status: Mapped[dict] = mapped_column(JSON, default=dict)

    #: The pseudonymous directory the session is written under. Derived from the patient id,
    #: carrying no name, so the layout on disk identifies nobody.
    participant_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    #: The consent that covered this recording, resolved when it started.
    consent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient_consents.id"))

    #: Counted during acquisition, from the device's own sample index and frame validity.
    dropped_samples: Mapped[int] = mapped_column(Integer, default=0)
    invalid_packets: Mapped[int] = mapped_column(Integer, default=0)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)

    #: What `validate` found, and when. Separate from quality: validation is about whether
    #: the files are intact and complete, quality is about whether the signal is readable.
    validated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Per-file name, size and digest, measured from disk after the write.
    files: Mapped[list] = mapped_column(JSON, default=list)

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    samples: Mapped[int] = mapped_column(Integer, default=0)

    storage_key: Mapped[str | None] = mapped_column(String(500))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)

    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_verdict: Mapped[str | None] = mapped_column(String(16), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    analyses: Mapped[list["SignalAnalysis"]] = relationship(
        back_populates="recording",
        cascade="all, delete-orphan",
        order_by="SignalAnalysis.analysed_at.desc()",
    )


class SignalAnalysis(Base):
    """What was derived from a recording, and whether a model could estimate from it.

    `estimate_available` is false whenever no model was found, and `unavailable_reason`
    then carries why. The two are separate from `pain_score` so that a null score cannot be
    read as a score of zero, and so a reader can tell "no model" apart from "model declined".

    `reported_nrs` is the patient's own score where one was taken at the time. It is stored
    on the analysis beside the estimate and is never an input to it.
    """

    __tablename__ = "signal_analyses"

    id: Mapped[uuid.UUID] = _pk()
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signal_recordings.id", ondelete="CASCADE"), index=True
    )
    analysed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    analysed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    feature_schema_version: Mapped[str] = mapped_column(String(8), default="1")
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    #: The handful of figures the results panel shows, derived from `features`.
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    derived_from: Mapped[list] = mapped_column(JSON, default=list)
    skipped_channels: Mapped[dict] = mapped_column(JSON, default=dict)

    #: The supporting autonomic figures, each null where its channel was absent or unusable.
    heart_rate_bpm: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)
    skin_conductance_us: Mapped[float | None] = mapped_column(Float)
    respiration_per_min: Mapped[float | None] = mapped_column(Float)

    estimate_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    pain_score: Mapped[float | None] = mapped_column(Float)
    pain_category: Mapped[str | None] = mapped_column(String(32))
    #: What `pain_score` is a number on, in the words of whoever published the labels the
    #: model was trained against. Stored on the row rather than looked up from the model,
    #: because a score read back years later has to say what it meant at the time even if
    #: the model it came from has been retired. Null where no estimate was made, and only
    #: there. `pain_category` is null unless this is the platform's own 0-10 scale, whose
    #: bands are the only ones defined.
    scale: Mapped[str | None] = mapped_column(String(64))
    uncertainty: Mapped[float | None] = mapped_column(Float)
    interval_low: Mapped[float | None] = mapped_column(Float)
    interval_high: Mapped[float | None] = mapped_column(Float)

    #: The patient's own 0-10 score, recorded alongside and never used as an input.
    reported_nrs: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[list] = mapped_column(JSON, default=list)

    recording: Mapped[SignalRecording] = relationship(back_populates="analyses")


class BehaviourObservation(Base):
    """One camera-and-microphone observation of a patient, and what was measured from it.

    One row rather than a recording row and an analysis row, because a clip is measured
    once: there is no streaming to resume and no reason to re-derive the same numbers from
    the same seconds of video twice.

    `media_retained` is the field to read first. The clip itself is discarded once the
    measures are out of it unless the clinician asked for it to be kept, so the usual state
    of this row is a set of numbers with no video behind them. `media_sha256` is kept
    either way: it is what ties these measures to a particular clip if a copy of that clip
    turns up elsewhere, and it identifies nobody on its own.

    `estimate_available` is false whenever no voice model was found, and
    `unavailable_reason` then carries why. It is kept apart from `voice_pain_level` so a
    null level cannot be read as a level of zero.
    """

    __tablename__ = "behaviour_observations"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    #: The assessment this was recorded during, where it was recorded during one. An
    #: observation taken at rest to calibrate the patient's baseline belongs to no
    #: assessment.
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    #: The consent that covered pointing a camera at this patient, resolved when the clip
    #: was accepted.
    consent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient_consents.id"))
    #: True where the clip was recorded with the patient at rest, to be the reference the
    #: later ones are read against.
    at_rest: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    duration_seconds: Mapped[float | None] = mapped_column(Float)
    frame_rate: Mapped[float | None] = mapped_column(Float)
    frames_decoded: Mapped[int] = mapped_column(Integer, default=0)
    frames_analysed: Mapped[int] = mapped_column(Integer, default=0)
    frame_width: Mapped[int | None] = mapped_column(Integer)
    frame_height: Mapped[int | None] = mapped_column(Integer)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)

    #: True where the eye windows and the iris width were fitted to this patient rather
    #: than taken from the average proportions of a face.
    eyes_calibrated: Mapped[bool] = mapped_column(Boolean, default=False)

    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_verdict: Mapped[str | None] = mapped_column(String(16), index=True)
    usable_modalities: Mapped[list] = mapped_column(JSON, default=list)

    feature_schema_version: Mapped[str] = mapped_column(String(8), default="1")
    #: The measures a clinician reads, keyed by the codes in app.behaviour.schema.
    measures: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Mel-frequency coefficients, kept apart because no one of them means anything alone.
    cepstral: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Change from this patient's own resting observation, where there is one.
    deltas: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Which reference each change-from-rest measure was taken against.
    reference: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Measures not reported, each with the reason.
    absent: Mapped[dict] = mapped_column(JSON, default=dict)
    #: How many frames or periods each average rests on.
    support: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)

    media_retained: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    media_bytes: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str | None] = mapped_column(String(80))
    media_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary)

    estimate_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    #: The voice model's output. An ordinal level on the four-class scale its training
    #: corpus publishes, not a 0-10 score, because no mapping between the two is published
    #: and inventing one would fabricate precision.
    voice_pain_level: Mapped[float | None] = mapped_column(Float)
    voice_pain_label: Mapped[str | None] = mapped_column(String(32))
    voice_confidence: Mapped[float | None] = mapped_column(Float)

    notes: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped["PainAssessment | None"] = relationship(
        back_populates="observations"
    )
