"""Schema for the clinical pain-assessment platform.

Two kinds of table live here. Reference tables mirror the taxonomies in app.knowledge so
that stored assessments can be joined and reported on; they are rebuilt from the Python
definitions by app.database.seed and are never edited in place. Everything else is
clinical data, keyed by UUID because the identifiers appear in URLs and a sequential
integer would leak how many records exist.

Two separations are deliberate and load-bearing:

- The patient's self-reported score lives in its own table, never on the assessment. It
  is reference data for training and evaluation, not an input to inference.
- Direct identifiers are sealed in `Patient.identity_blob` rather than kept in queryable
  columns, so a read of the patients table does not disclose who anyone is.
"""

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

from app.database.database import Base, UtcDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _enum(python_enum: type[enum.Enum], **kwargs):
    return mapped_column(Enum(python_enum, native_enum=False), **kwargs)


class Role(str, enum.Enum):
    """What an account is allowed to do. Self-registration never grants ADMIN."""

    DOCTOR = "DOCTOR"
    ADMIN = "ADMIN"


class Profession(str, enum.Enum):
    """What the clinician does, as they declared it.

    Kept apart from Role on purpose: Role is authorisation and only an administrator can
    change it, while this is a description of the person and is theirs to state.
    """

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


# --- reference tables, rebuilt from app.knowledge ----------------------------------


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
    """One entry of the anatomy ontology: region, then structure type, then structure.

    `location_code` is the pain-location code the structure projects onto. It is what
    connects a structure selected on the 3D model to the question engine, the rule engine
    and the feature vector, none of which know anything about anatomy.
    """

    __tablename__ = "anatomical_structures"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(160))
    latin: Mapped[str] = mapped_column(String(160), default="")
    structure_type: Mapped[str] = mapped_column(
        ForeignKey("anatomical_structure_types.code"), index=True
    )
    region: Mapped[str] = mapped_column(ForeignKey("anatomical_regions.code"), index=True)
    location_code: Mapped[str] = mapped_column(ForeignKey("pain_locations.code"))
    location_left: Mapped[str | None] = mapped_column(String(48))
    location_right: Mapped[str | None] = mapped_column(String(48))
    laterality: Mapped[str] = mapped_column(String(16))
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    # Restricts the structure to patients of that sex. Null means it is offered to everyone.
    sex: Mapped[str | None] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(Text, default="")


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
    __tablename__ = "diseases"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32), index=True)
    pain_relevant: Mapped[bool] = mapped_column(Boolean, default=False)


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


# --- accounts ---------------------------------------------------------------------


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))


# --- patients ---------------------------------------------------------------------


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sex: Mapped[Sex] = _enum(Sex, default=Sex.UNDISCLOSED)
    birth_date: Mapped[date | None] = mapped_column(Date)
    ward: Mapped[str | None] = mapped_column(String(80))
    smoking_status: Mapped[SmokingStatus] = _enum(SmokingStatus, default=SmokingStatus.UNKNOWN)

    medical_history: Mapped[str | None] = mapped_column(Text)
    previous_surgeries: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[str | None] = mapped_column(Text)
    family_history: Mapped[str | None] = mapped_column(Text)
    lifestyle_notes: Mapped[str | None] = mapped_column(Text)

    # Name, phone and emergency contact, sealed with AES-256-GCM under a per-record data
    # key. No identity card number is asked for or stored.
    identity_blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    identity_key: Mapped[bytes | None] = mapped_column(LargeBinary)

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

    def age_on(self, moment: date) -> int | None:
        if self.birth_date is None:
            return None
        years = moment.year - self.birth_date.year
        if (moment.month, moment.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


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


# --- assessments ------------------------------------------------------------------


class PainAssessment(Base):
    __tablename__ = "pain_assessments"

    id: Mapped[uuid.UUID] = _pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[AssessmentStatus] = _enum(AssessmentStatus, default=AssessmentStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, onupdate=_now)

    # Age is copied in rather than derived at read time: a record reviewed next year must
    # still say how old the patient was when it was taken.
    patient_age_years: Mapped[int | None] = mapped_column(Integer)

    onset: Mapped[Onset] = _enum(Onset, default=Onset.UNKNOWN)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    duration_hours: Mapped[float | None] = mapped_column(Float)
    pattern: Mapped[Pattern] = _enum(Pattern, default=Pattern.UNKNOWN)
    course: Mapped[Course] = _enum(Course, default=Course.UNKNOWN)
    episodes_per_day: Mapped[float | None] = mapped_column(Float)
    episode_minutes: Mapped[float | None] = mapped_column(Float)

    night_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    morning_pain: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_after_activity: Mapped[bool] = mapped_column(Boolean, default=False)
    pain_at_rest: Mapped[bool] = mapped_column(Boolean, default=False)

    radiates: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_description: Mapped[str | None] = mapped_column(Text)
    radiation_numbness: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_tingling: Mapped[bool] = mapped_column(Boolean, default=False)
    radiation_weakness: Mapped[bool] = mapped_column(Boolean, default=False)

    recent_trauma: Mapped[bool] = mapped_column(Boolean, default=False)
    recent_surgery: Mapped[bool] = mapped_column(Boolean, default=False)

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
    """A structure localised on the 3D model, with its side and its own intensity.

    Each row refines, rather than replaces, `AssessmentLocation`: the pain location its
    structure projects onto is kept in step by the write path, so the rest of the platform
    reads the site through the taxonomy it already uses.

    `intensity` is not a model input. It is an intensity rating of the very thing the
    estimate is for, so feeding it back in would make the estimate a restatement of the
    answer; it is kept for the record, the report and the clinician's own reading, in the
    same spirit as `SelfReport`. ClinicalContext has no field for it, which is what stops
    it reaching inference.
    """

    __tablename__ = "assessment_anatomical_sites"
    __table_args__ = (UniqueConstraint("assessment_id", "structure_code", "side"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    structure_code: Mapped[str] = mapped_column(ForeignKey("anatomical_structures.code"))
    side: Mapped[str] = mapped_column(String(16), default="MIDLINE")
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


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"
    __table_args__ = (UniqueConstraint("assessment_id", "question_code"),)

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True
    )
    question_code: Mapped[str] = mapped_column(ForeignKey("clinical_questions.code"))
    # Booleans, numbers, single choices and multiple choices all land here, so the column
    # holds the JSON value the question declared rather than a stringified copy.
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
    """The patient's own 0-10 score.

    Kept apart from the assessment on purpose. It is the reference the model is trained
    and evaluated against, and it is never assembled into a feature vector.
    """

    __tablename__ = "self_reports"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True, unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    nrs: Mapped[float] = mapped_column(Float)
    reported_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    note: Mapped[str | None] = mapped_column(Text)

    assessment: Mapped[PainAssessment] = relationship(back_populates="self_report")


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


# --- model output -----------------------------------------------------------------


class PainPrediction(Base):
    __tablename__ = "pain_predictions"

    id: Mapped[uuid.UUID] = _pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_assessments.id"), index=True, unique=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)

    model_version: Mapped[str | None] = mapped_column(String(64))
    dataset_version: Mapped[str | None] = mapped_column(String(64))

    estimated_pain: Mapped[float | None] = mapped_column(Float)
    interval_low: Mapped[float | None] = mapped_column(Float)
    interval_high: Mapped[float | None] = mapped_column(Float)
    band: Mapped[str | None] = mapped_column(String(16))

    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_factors: Mapped[list] = mapped_column(JSON, default=list)

    data_quality: Mapped[DataQuality] = _enum(DataQuality, default=DataQuality.ADEQUATE)
    quality_issues: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)

    # A refusal is a result, not an error: the pipeline ran and declined to produce an
    # estimate, and the reason is shown to the clinician.
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


# --- model and dataset registry ---------------------------------------------------


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = _pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    seed: Mapped[int] = mapped_column(Integer)
    n_rows: Mapped[int] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    path: Mapped[str] = mapped_column(String(255))


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = _pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    algorithm: Mapped[str] = mapped_column(String(80))
    trained_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    dataset_version: Mapped[str] = mapped_column(String(64))
    n_train: Mapped[int] = mapped_column(Integer)
    n_test: Mapped[int] = mapped_column(Integer)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    r2: Mapped[float] = mapped_column(Float)
    pearson: Mapped[float] = mapped_column(Float)
    cv_folds: Mapped[int] = mapped_column(Integer)
    cv_mae_mean: Mapped[float] = mapped_column(Float)
    cv_mae_sd: Mapped[float] = mapped_column(Float)
    residual_sd: Mapped[float] = mapped_column(Float)
    features: Mapped[list] = mapped_column(JSON, default=list)
    artifact_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")


# --- audit and integrity ----------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _pk()
    # Assigned by the append path, not by the database: autoincrement only applies to
    # integer primary keys, and the chain needs the sequence to match the hash order.
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


class KeyMetadata(Base):
    __tablename__ = "key_metadata"

    id: Mapped[uuid.UUID] = _pk()
    label: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(48))
    algorithm: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    rotated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    fingerprint: Mapped[str] = mapped_column(String(64))
