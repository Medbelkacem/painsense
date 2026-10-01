"""EEG and EMG analysis

Adds the recording and analysis tables for the EEG & EMG Pain Analysis feature. Nothing
existing is altered.

`source` is NOT NULL with no server default, deliberately. Every recording has to declare
whether its samples came from hardware or from the simulator, and a default would let a row
exist without saying.

Revision ID: e8c1f3a5d920
Revises: d7e2b5a94c18
"""

import sqlalchemy as sa
from alembic import op

revision = "e8c1f3a5d920"
down_revision = "d7e2b5a94c18"
branch_labels = None
depends_on = None

SOURCE = sa.Enum("HARDWARE", "SIMULATION", name="signalsource", native_enum=False)
STATE = sa.Enum(
    "RECORDING",
    "PROCESSING",
    "ANALYSED",
    "DISCARDED",
    "FAILED",
    name="recordingstate",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "signal_recordings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("source", SOURCE, nullable=False),
        sa.Column("state", STATE, nullable=False),
        sa.Column("device_label", sa.String(length=120), nullable=True),
        sa.Column("sample_rate_hz", sa.Float(), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("sensor_status", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("quality_verdict", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    for column in ("patient_id", "source", "state", "started_at", "sha256", "quality_verdict"):
        op.create_index(f"ix_signal_recordings_{column}", "signal_recordings", [column])

    op.create_table(
        "signal_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "recording_id",
            sa.Uuid(),
            sa.ForeignKey("signal_recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("feature_schema_version", sa.String(length=8), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("derived_from", sa.JSON(), nullable=False),
        sa.Column("skipped_channels", sa.JSON(), nullable=False),
        sa.Column("heart_rate_bpm", sa.Float(), nullable=True),
        sa.Column("hrv_rmssd_ms", sa.Float(), nullable=True),
        sa.Column("skin_conductance_us", sa.Float(), nullable=True),
        sa.Column("respiration_per_min", sa.Float(), nullable=True),
        sa.Column(
            "estimate_available", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("pain_score", sa.Float(), nullable=True),
        sa.Column("pain_category", sa.String(length=32), nullable=True),
        sa.Column("uncertainty", sa.Float(), nullable=True),
        sa.Column("interval_low", sa.Float(), nullable=True),
        sa.Column("interval_high", sa.Float(), nullable=True),
        sa.Column("reported_nrs", sa.Float(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
    )
    for column in ("recording_id", "analysed_at", "estimate_available", "model_version"):
        op.create_index(f"ix_signal_analyses_{column}", "signal_analyses", [column])


def downgrade() -> None:
    op.drop_table("signal_analyses")
    op.drop_table("signal_recordings")
