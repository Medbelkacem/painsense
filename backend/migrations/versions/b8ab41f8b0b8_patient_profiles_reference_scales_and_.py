"""patient profiles, reference scales and baseline calibration

Also widens users.role. The initial schema created it from a two-value enum, so the column
is VARCHAR(6); the roles have since grown to CLINIC_ADMIN, which is twelve characters, and
no migration ever widened it. SQLite does not enforce the length so this went unnoticed,
but on PostgreSQL creating the first administrator fails.

Revision ID: b8ab41f8b0b8
Revises: b2c4e6f8a1d3
"""

import sqlalchemy as sa
from alembic import op

revision = "b8ab41f8b0b8"
down_revision = "b2c4e6f8a1d3"
branch_labels = None
depends_on = None

ROLE = sa.Enum(
    "SUPER_ADMIN",
    "CLINIC_ADMIN",
    "DOCTOR",
    "RESEARCHER",
    "AUDITOR",
    name="role",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "patient_baselines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("readings", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("minutes_at_rest", sa.Float(), nullable=True),
        sa.Column("hr", sa.Float(), nullable=True),
        sa.Column("resp_rate", sa.Float(), nullable=True),
        sa.Column("sbp", sa.Float(), nullable=True),
        sa.Column("dbp", sa.Float(), nullable=True),
        sa.Column("spo2", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("patient_baselines", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_patient_baselines_patient_id"), ["patient_id"], unique=True
        )

    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_code", sa.String(length=48), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_patients_profile_code"), ["profile_code"], unique=False
        )

    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("patient_age_months", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("profile_code", sa.String(length=48), nullable=True))
        batch_op.add_column(
            sa.Column("profile_modifiers", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("pregnancy_trimester", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("expected_pain", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(
            batch_op.f("ix_pain_assessments_profile_code"), ["profile_code"], unique=False
        )

    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_code", sa.String(length=48), nullable=True))
        batch_op.add_column(
            sa.Column("profile_modifiers", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("reference_scale", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column("can_self_report", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("profile_penalty", sa.Float(), nullable=False, server_default="0")
        )
        batch_op.create_index(
            batch_op.f("ix_pain_predictions_profile_code"), ["profile_code"], unique=False
        )

    with op.batch_alter_table("self_reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("scale_code", sa.String(length=16), nullable=False, server_default="NRS")
        )
        batch_op.add_column(sa.Column("raw_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("raw_max", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("items", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.add_column(
            sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(
            batch_op.f("ix_self_reports_scale_code"), ["scale_code"], unique=False
        )

    # Existing reports were all numerical ratings, so their own score is the stored one.
    op.execute("UPDATE self_reports SET raw_score = nrs, raw_max = 10 WHERE raw_score IS NULL")

    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("classification", sa.JSON(), nullable=False, server_default="{}")
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.VARCHAR(length=6),
            type_=ROLE,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=ROLE,
            type_=sa.VARCHAR(length=6),
            existing_nullable=False,
        )

    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.drop_column("classification")

    with op.batch_alter_table("self_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_self_reports_scale_code"))
        for column in ("observed", "items", "raw_max", "raw_score", "scale_code"):
            batch_op.drop_column(column)

    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_predictions_profile_code"))
        for column in (
            "profile_penalty",
            "can_self_report",
            "reference_scale",
            "profile_modifiers",
            "profile_code",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_assessments_profile_code"))
        for column in (
            "expected_pain",
            "pregnancy_trimester",
            "profile_modifiers",
            "profile_code",
            "patient_age_months",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patients_profile_code"))
        batch_op.drop_column("profile_code")

    with op.batch_alter_table("patient_baselines", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patient_baselines_patient_id"))

    op.drop_table("patient_baselines")
