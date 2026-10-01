import sqlalchemy as sa
from alembic import op

revision = "7a4859de03ad"
down_revision = "75411c6eb714"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anatomical_regions",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "anatomical_structure_types",
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "anatomical_structures",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("latin", sa.String(length=160), nullable=False),
        sa.Column("structure_type", sa.String(length=24), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("location_code", sa.String(length=48), nullable=False),
        sa.Column("location_left", sa.String(length=48), nullable=True),
        sa.Column("location_right", sa.String(length=48), nullable=True),
        sa.Column("laterality", sa.String(length=16), nullable=False),
        sa.Column("synonyms", sa.JSON(), nullable=False),
        sa.Column("sex", sa.String(length=8), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["location_code"],
            ["pain_locations.code"],
        ),
        sa.ForeignKeyConstraint(
            ["region"],
            ["anatomical_regions.code"],
        ),
        sa.ForeignKeyConstraint(
            ["structure_type"],
            ["anatomical_structure_types.code"],
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("anatomical_structures", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_anatomical_structures_region"), ["region"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_anatomical_structures_structure_type"),
            ["structure_type"],
            unique=False,
        )

    op.create_table(
        "assessment_anatomical_sites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("structure_code", sa.String(length=48), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["structure_code"],
            ["anatomical_structures.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "structure_code", "side"),
    )
    with op.batch_alter_table("assessment_anatomical_sites", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_anatomical_sites_assessment_id"),
            ["assessment_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("assessment_anatomical_sites", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_anatomical_sites_assessment_id"))

    op.drop_table("assessment_anatomical_sites")
    with op.batch_alter_table("anatomical_structures", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_anatomical_structures_structure_type"))
        batch_op.drop_index(batch_op.f("ix_anatomical_structures_region"))

    op.drop_table("anatomical_structures")
    op.drop_table("anatomical_structure_types")
    op.drop_table("anatomical_regions")
