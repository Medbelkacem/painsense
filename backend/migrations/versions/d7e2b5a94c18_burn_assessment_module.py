"""Burn assessment and wound follow-up

Adds the BurnCare tables: consent, incidents, assessments with their regions and surface
area calculations, pain reports, wound images and their analyses, wound care, follow-up,
review flags and generated reports.

`WOUND_PHOTO` joins the document kinds so wound photographs reuse the existing encrypted
document store rather than getting a second, less careful one.

Revision ID: d7e2b5a94c18
Revises: c3f1a9d47e52
"""

import sqlalchemy as sa
from alembic import op

revision = "d7e2b5a94c18"
down_revision = "c3f1a9d47e52"
branch_labels = None
depends_on = None


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


DEPTH = _enum(
    "SUPERFICIAL_EPIDERMAL",
    "SUPERFICIAL_PARTIAL",
    "DEEP_PARTIAL",
    "FULL_THICKNESS",
    "UNCERTAIN",
    name="burndepth",
)
METHOD = _enum("LUND_BROWDER", "RULE_OF_NINES", "PALM", name="tbsamethod")
ATTRIBUTION = _enum("PATIENT", "CLINICIAN", "MODEL", name="attribution")
REVIEW = _enum("DRAFT", "AWAITING_REVIEW", "CONFIRMED", "AMENDED", name="reviewstate")
SEVERITY = _enum("REVIEW", "URGENT_REVIEW", name="alertseverity")

#: `DocumentKind` is a non-native enum, so adding a member is a check-constraint change.
#: Rebuilding the column under batch_alter_table is what works on SQLite and Postgres both.
DOCUMENT_KINDS = (
    "XRAY",
    "WOUND_PHOTO",
    "CT",
    "MRI",
    "ULTRASOUND",
    "ECG",
    "LABORATORY",
    "REPORT",
    "PRESCRIPTION",
    "OTHER",
)


def upgrade() -> None:
    with op.batch_alter_table("medical_documents") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            type_=_enum(*DOCUMENT_KINDS, name="documentkind"),
            existing_nullable=False,
        )

    op.create_table(
        "patient_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("scope", sa.String(length=48), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("patient_id", "scope", name="uq_patient_consent_scope"),
    )
    op.create_index("ix_patient_consents_patient_id", "patient_consents", ["patient_id"])
    op.create_index("ix_patient_consents_scope", "patient_consents", ["scope"])

    op.create_table(
        "burn_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cause", sa.String(length=24), nullable=False),
        sa.Column("cause_detail", sa.Text(), nullable=True),
        sa.Column("first_aid", sa.Text(), nullable=True),
        sa.Column("enclosed_space", sa.Boolean(), nullable=True),
        sa.Column("airway_symptoms", sa.JSON(), nullable=False),
        sa.Column("symptoms", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("patient_id", "occurred_at", "cause", "created_at"):
        op.create_index(f"ix_burn_incidents_{column}", "burn_incidents", [column])

    op.create_table(
        "burn_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("age_years", sa.Float(), nullable=True),
        sa.Column("state", REVIEW, nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    for column in ("incident_id", "patient_id", "assessed_at", "state"):
        op.create_index(f"ix_burn_assessments_{column}", "burn_assessments", [column])

    op.create_table(
        "burn_regions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("burn_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region_code", sa.String(length=32), nullable=False),
        sa.Column("fraction", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("depth", DEPTH, nullable=False),
        sa.Column("depth_attribution", ATTRIBUTION, nullable=False),
        sa.Column("suggested_depth", DEPTH, nullable=True),
        sa.Column("suggested_confidence", sa.Float(), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("circumferential", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marks", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("assessment_id", "region_code", name="uq_burn_region_once"),
    )
    op.create_index("ix_burn_regions_assessment_id", "burn_regions", ["assessment_id"])
    op.create_index("ix_burn_regions_region_code", "burn_regions", ["region_code"])

    op.create_table(
        "tbsa_calculations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("burn_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", METHOD, nullable=False),
        sa.Column("total_percent", sa.Float(), nullable=False),
        sa.Column(
            "excluded_superficial_percent", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("age_years", sa.Float(), nullable=True),
        sa.Column("age_band", sa.String(length=16), nullable=False),
        sa.Column("palms", sa.Float(), nullable=True),
        sa.Column("provisional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("attribution", ATTRIBUTION, nullable=False),
        sa.Column("clinician_percent", sa.Float(), nullable=True),
        sa.Column("clinician_note", sa.Text(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    for column in ("assessment_id", "method", "calculated_at"):
        op.create_index(f"ix_tbsa_calculations_{column}", "tbsa_calculations", [column])

    op.create_table(
        "wound_care_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("performed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("region_codes", sa.JSON(), nullable=False),
        sa.Column("assessment_before", sa.Text(), nullable=True),
        sa.Column("cleaning", sa.Text(), nullable=True),
        sa.Column("solution", sa.String(length=255), nullable=True),
        sa.Column("dressing", sa.String(length=255), nullable=True),
        sa.Column("tolerance", sa.String(length=32), nullable=True),
        sa.Column("analgesia_given", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_review_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("patient_id", "incident_id", "performed_at", "next_review_on"):
        op.create_index(f"ix_wound_care_events_{column}", "wound_care_events", [column])

    op.create_table(
        "burn_pain_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "care_event_id",
            sa.Uuid(),
            sa.ForeignKey("wound_care_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scale_code", sa.String(length=16), nullable=False),
        sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attribution", ATTRIBUTION, nullable=False),
        sa.Column("current_nrs", sa.Float(), nullable=True),
        sa.Column("at_rest_nrs", sa.Float(), nullable=True),
        sa.Column("on_movement_nrs", sa.Float(), nullable=True),
        sa.Column("during_care_nrs", sa.Float(), nullable=True),
        sa.Column("before_care_nrs", sa.Float(), nullable=True),
        sa.Column("after_care_nrs", sa.Float(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("raw_max", sa.Float(), nullable=True),
        sa.Column("qualities", sa.JSON(), nullable=False),
        sa.Column("region_codes", sa.JSON(), nullable=False),
        sa.Column("duration_hours", sa.Float(), nullable=True),
        sa.Column("disturbs_sleep", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    for column in ("patient_id", "incident_id", "care_event_id", "reported_at", "scale_code"):
        op.create_index(f"ix_burn_pain_reports_{column}", "burn_pain_reports", [column])

    op.create_table(
        "wound_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("medical_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("burn_assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "care_event_id",
            sa.Uuid(),
            sa.ForeignKey("wound_care_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "consent_id", sa.Uuid(), sa.ForeignKey("patient_consents.id"), nullable=True
        ),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    for column in (
        "patient_id",
        "incident_id",
        "assessment_id",
        "care_event_id",
        "region_code",
        "captured_at",
    ):
        op.create_index(f"ix_wound_images_{column}", "wound_images", [column])

    op.create_table(
        "image_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "image_id",
            sa.Uuid(),
            sa.ForeignKey("wound_images.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=32), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burn_area_fraction", sa.Float(), nullable=True),
        sa.Column("suggested_depth", DEPTH, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.Float(), nullable=True),
        sa.Column("mask_storage_name", sa.String(length=80), nullable=True),
        sa.Column("quality_warnings", sa.JSON(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("accepted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    for column in ("image_id", "model_version", "task"):
        op.create_index(f"ix_image_analyses_{column}", "image_analyses", [column])

    op.create_table(
        "follow_up_visits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.Date(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("burn_assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("healing_state", sa.String(length=32), nullable=True),
        sa.Column("clinician_note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("patient_id", "incident_id", "scheduled_for"):
        op.create_index(f"ix_follow_up_visits_{column}", "follow_up_visits", [column])

    op.create_table(
        "burn_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("burn_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("severity", SEVERITY, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assessment_id", "code", name="uq_burn_alert_once"),
    )
    for column in ("assessment_id", "code", "severity", "raised_at"):
        op.create_index(f"ix_burn_alerts_{column}", "burn_alerts", [column])

    op.create_table(
        "clinical_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("burn_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("state", REVIEW, nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("includes_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
    )
    for column in ("patient_id", "incident_id", "generated_at", "state"):
        op.create_index(f"ix_clinical_reports_{column}", "clinical_reports", [column])


def downgrade() -> None:
    for table in (
        "clinical_reports",
        "burn_alerts",
        "follow_up_visits",
        "image_analyses",
        "wound_images",
        "burn_pain_reports",
        "wound_care_events",
        "tbsa_calculations",
        "burn_regions",
        "burn_assessments",
        "burn_incidents",
        "patient_consents",
    ):
        op.drop_table(table)
    with op.batch_alter_table("medical_documents") as batch:
        batch.alter_column(
            "kind",
            existing_type=_enum(*DOCUMENT_KINDS, name="documentkind"),
            type_=_enum(*[k for k in DOCUMENT_KINDS if k != "WOUND_PHOTO"], name="documentkind"),
            existing_nullable=False,
        )
