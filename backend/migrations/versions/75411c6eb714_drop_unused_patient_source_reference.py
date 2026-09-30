"""Drop patients.source_ref: it existed only for the demonstration loader.

Revision ID: 75411c6eb714
Revises: df6454d1cba5
"""

import sqlalchemy as sa
from alembic import op

revision = '75411c6eb714'
down_revision = 'df6454d1cba5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('patients') as batch:
        batch.drop_index('ix_patients_source_ref')
        batch.drop_column('source_ref')


def downgrade() -> None:
    with op.batch_alter_table('patients') as batch:
        batch.add_column(sa.Column('source_ref', sa.VARCHAR(length=64), nullable=True))
        batch.create_index('ix_patients_source_ref', ['source_ref'], unique=True)

