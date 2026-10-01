"""Signal acquisition: hardware provenance, per-channel rates, separate validation

Extends `signal_recordings` for real hardware acquisition. Nothing is dropped and nothing
existing changes meaning, with one exception worth stating: `storage_key` now names the
session *directory* rather than a single parquet file, because a recording is now one file
per modality. Recordings made before this migration keep their old key and are readable
through the previous path.

`channel_rates` is the authoritative per-channel rate. `sample_rate_hz` stays as the primary
rate because many readers want one number.

`RecordingState` gains `SAVED`, which needs no DDL: the column is a non-native enum, so
SQLAlchemy stores it as VARCHAR with no check constraint, and `SAVED` is shorter than the
longest member already there.

Revision ID: f4a7d2c81e65
Revises: e8c1f3a5d920
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a7d2c81e65"
down_revision = "e8c1f3a5d920"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("signal_recordings") as batch:
        batch.add_column(sa.Column("adapter", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("device_identifier", sa.String(length=255), nullable=True))
        batch.add_column(
            sa.Column("channel_rates", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(sa.Column("participant_ref", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column(
                "consent_id",
                sa.Uuid(),
                sa.ForeignKey("patient_consents.id", name="fk_signal_recordings_consent"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("dropped_samples", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("invalid_packets", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("reconnects", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("validation", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(sa.Column("files", sa.JSON(), nullable=False, server_default="[]"))

    op.create_index("ix_signal_recordings_adapter", "signal_recordings", ["adapter"])
    op.create_index(
        "ix_signal_recordings_participant_ref", "signal_recordings", ["participant_ref"]
    )

    # Existing rows have one rate for the whole session; carry it onto every channel so
    # `channel_rates` is authoritative from here on rather than empty for older recordings.
    op.execute(
        sa.text(
            "UPDATE signal_recordings "
            "SET participant_ref = COALESCE(participant_ref, CAST(patient_id AS VARCHAR)) "
            "WHERE participant_ref IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_signal_recordings_participant_ref", table_name="signal_recordings")
    op.drop_index("ix_signal_recordings_adapter", table_name="signal_recordings")
    with op.batch_alter_table("signal_recordings") as batch:
        for column in (
            "files",
            "validation",
            "validated_at",
            "reconnects",
            "invalid_packets",
            "dropped_samples",
            "consent_id",
            "participant_ref",
            "channel_rates",
            "device_identifier",
            "adapter",
        ):
            batch.drop_column(column)
