"""account profile fields

Revision ID: df6454d1cba5
Revises: 9d7cf7ce577c
"""

import sqlalchemy as sa
from alembic import op

revision = 'df6454d1cba5'
down_revision = '9d7cf7ce577c'
branch_labels = None
depends_on = None


PROFESSION = sa.Enum("DOCTOR", "NURSE", "RESIDENT", "OTHER", name="profession", native_enum=False)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("clinic_name", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("phone", sa.String(length=48), nullable=True))
        # Accounts that already exist predate the field, so they take the common case.
        batch.add_column(
            sa.Column("profession", PROFESSION, nullable=False, server_default="DOCTOR")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("profession")
        batch.drop_column("phone")
        batch.drop_column("clinic_name")

