"""Assessment form fields for the prototype

A patient carries the age typed at registration, so a record without a date of birth
still has one. An assessment keeps the duration as it was entered, value and unit, next
to the hours the model reads; the three free-text notes sit beside the coded symptom and
factor pickers. An account can be tied to one patient record, which is what a PATIENT
role reads.

Revision ID: e5b7a2c91d04
Revises: c7b3e81f4a26
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b7a2c91d04"
down_revision = "c7b3e81f4a26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("age_years", sa.Integer(), nullable=True))
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("patient_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_users_patient_id_patients", "patients", ["patient_id"], ["id"]
        )
    op.add_column("pain_assessments", sa.Column("duration_value", sa.Float(), nullable=True))
    op.add_column(
        "pain_assessments", sa.Column("duration_unit", sa.String(length=8), nullable=True)
    )
    op.add_column("pain_assessments", sa.Column("symptoms_note", sa.Text(), nullable=True))
    op.add_column("pain_assessments", sa.Column("aggravating_note", sa.Text(), nullable=True))
    op.add_column("pain_assessments", sa.Column("relieving_note", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in (
        "relieving_note",
        "aggravating_note",
        "symptoms_note",
        "duration_unit",
        "duration_value",
    ):
        op.drop_column("pain_assessments", column)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_patient_id_patients", type_="foreignkey")
        batch.drop_column("patient_id")
    op.drop_column("patients", "age_years")
