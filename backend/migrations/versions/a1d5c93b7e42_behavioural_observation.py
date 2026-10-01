"""Behavioural observation: camera and microphone measures

Adds `behaviour_observations`, one row per clip recorded of a patient, holding what was
measured from their eyes, face and voice. The clip itself is not in the row and usually not
on disk: it is discarded once the measures are out of it unless the clinician asked for it
to be kept, and `media_retained` says which happened.

Extends `patient_baselines` with the same patient's resting behaviour. Orbital tightening
and brow lowering are changes from a resting value and cannot be computed without one, so
these columns are what lets the platform compare a patient against themselves rather than
against an average face. They are all nullable: a baseline recorded before this migration
carries vitals and no behaviour, which is the ordinary case and not an error.

Revision ID: a1d5c93b7e42
Revises: f4a7d2c81e65
"""

import sqlalchemy as sa
from alembic import op

revision = "a1d5c93b7e42"
down_revision = "f4a7d2c81e65"
branch_labels = None
depends_on = None

_RESTING_COLUMNS = (
    "resting_eye_aperture",
    "resting_pupil_mm",
    "resting_blink_rate",
    "resting_brow_gap",
    "resting_f0_hz",
    "resting_intensity_db",
    "resting_speech_rate",
)


def upgrade() -> None:
    op.create_table(
        "behaviour_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(),
            sa.ForeignKey("patients.id", name="fk_behaviour_observations_patient"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("pain_assessments.id", name="fk_behaviour_observations_assessment"),
            nullable=True,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_behaviour_observations_user"),
            nullable=True,
        ),
        sa.Column(
            "consent_id",
            sa.Uuid(),
            sa.ForeignKey("patient_consents.id", name="fk_behaviour_observations_consent"),
            nullable=True,
        ),
        sa.Column("at_rest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("frame_rate", sa.Float(), nullable=True),
        sa.Column("frames_decoded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frames_analysed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("frame_width", sa.Integer(), nullable=True),
        sa.Column("frame_height", sa.Integer(), nullable=True),
        sa.Column("has_video", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eyes_calibrated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("quality_verdict", sa.String(length=16), nullable=True),
        sa.Column("usable_modalities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("feature_schema_version", sa.String(length=8), nullable=False, server_default="1"),
        sa.Column("measures", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("cepstral", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deltas", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("reference", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("absent", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("support", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("media_retained", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("media_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_type", sa.String(length=80), nullable=True),
        sa.Column("media_sha256", sa.String(length=64), nullable=True),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=True),
        sa.Column("estimate_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("voice_pain_level", sa.Float(), nullable=True),
        sa.Column("voice_pain_label", sa.String(length=32), nullable=True),
        sa.Column("voice_confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
    )
    for column in (
        "patient_id",
        "assessment_id",
        "recorded_at",
        "at_rest",
        "quality_verdict",
        "media_retained",
        "media_sha256",
        "estimate_available",
        "model_version",
    ):
        op.create_index(
            f"ix_behaviour_observations_{column}", "behaviour_observations", [column]
        )

    with op.batch_alter_table("patient_baselines") as batch:
        batch.add_column(
            sa.Column("behaviour_recorded_at", sa.DateTime(timezone=True), nullable=True)
        )
        for column in _RESTING_COLUMNS:
            batch.add_column(sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("patient_baselines") as batch:
        for column in reversed(_RESTING_COLUMNS):
            batch.drop_column(column)
        batch.drop_column("behaviour_recorded_at")
    op.drop_table("behaviour_observations")
