"""Signal analyses record the scale their estimate is on

Adds `signal_analyses.scale`. The signal pain model is fitted on whatever corpus is
available, and a corpus publishes its labels on its own scale: the PainMonit database the
shipped model is trained on rates pain on a continuous visual analogue scale from 0 to 100,
not on the 0-10 numeric rating scale the rest of the platform uses. A stored score of 62
means nothing without that, and reading it as 62 out of 10 would be worse than not having
it.

Nullable, and null is also what an analysis carries when no model was available to estimate
from. Rows written before this migration all came from a platform with no signal model
registered at all — `estimate_available` is false on every one of them — so there is no
historical score whose scale has to be back-filled.

Revision ID: c7b3e81f4a26
Revises: a1d5c93b7e42
"""

import sqlalchemy as sa
from alembic import op

revision = "c7b3e81f4a26"
down_revision = "a1d5c93b7e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal_analyses", sa.Column("scale", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("signal_analyses", "scale")
