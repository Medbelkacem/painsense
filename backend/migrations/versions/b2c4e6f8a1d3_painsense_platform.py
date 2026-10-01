import sqlalchemy as sa
from alembic import op

revision = "b2c4e6f8a1d3"
down_revision = "7a4859de03ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "preferred_language", sa.String(length=8), nullable=False, server_default="en"
            )
        )
    op.execute("UPDATE users SET role = 'SUPER_ADMIN' WHERE role = 'ADMIN'")

    with op.batch_alter_table("session_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_ip", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("anatomical_structures", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subregion", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("parent_code", sa.String(length=48), nullable=True))
        batch_op.add_column(sa.Column("system", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("has_mesh", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("pain_selectable", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("description", sa.Text(), nullable=False, server_default="")
        )
        batch_op.create_index(
            batch_op.f("ix_anatomical_structures_subregion"), ["subregion"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_anatomical_structures_parent_code"), ["parent_code"], unique=False
        )

    op.create_table(
        "anatomical_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.String(length=48), nullable=False),
        sa.Column("target_code", sa.String(length=48), nullable=False),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(["source_code"], ["anatomical_structures.code"]),
        sa.ForeignKeyConstraint(["target_code"], ["anatomical_structures.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_code", "target_code", "relation"),
    )
    with op.batch_alter_table("anatomical_relationships", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_anatomical_relationships_source_code"), ["source_code"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_anatomical_relationships_target_code"), ["target_code"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_anatomical_relationships_relation"), ["relation"], unique=False
        )

    op.create_table(
        "medication_classes",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("analgesic", sa.Boolean(), nullable=False),
        sa.Column("sedating", sa.Boolean(), nullable=False),
        sa.Column("affects", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "onset_speed",
                sa.Enum(
                    "SECONDS",
                    "MINUTES",
                    "HOURS",
                    "DAYS",
                    "WEEKS_OR_MORE",
                    "UNKNOWN",
                    name="onsetspeed",
                    native_enum=False,
                ),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch_op.add_column(
            sa.Column("recurrent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        for column in ("afternoon_pain", "evening_pain", "variable_timing"):
            batch_op.add_column(
                sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        for column in (
            "impact_mobility",
            "impact_sleep",
            "impact_work",
            "impact_daily_activity",
            "impact_self_care",
        ):
            batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "review_agreement",
                sa.Enum(
                    "AGREE", "PARTLY", "DISAGREE", name="reviewagreement", native_enum=False
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("review_comment", sa.Text(), nullable=True))

    with op.batch_alter_table("assessment_anatomical_sites", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.Enum(
                    "PRIMARY",
                    "SECONDARY",
                    "RADIATING",
                    "REFERRED",
                    name="painsiterole",
                    native_enum=False,
                ),
                nullable=False,
                server_default="SECONDARY",
            )
        )
        batch_op.add_column(
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("radiation_from_code", sa.String(length=48), nullable=True)
        )
        batch_op.add_column(
            sa.Column("radiation_from_side", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("quality_codes", sa.JSON(), nullable=False, server_default="[]")
        )
        for column, name in (("onset", "onset"), ("pattern", "pattern"), ("course", "course")):
            values = {
                "onset": ("SUDDEN", "GRADUAL", "UNKNOWN"),
                "pattern": ("CONSTANT", "INTERMITTENT", "EPISODIC", "UNKNOWN"),
                "course": ("IMPROVING", "STABLE", "WORSENING", "PROGRESSIVE", "UNKNOWN"),
            }[column]
            batch_op.add_column(
                sa.Column(
                    column,
                    sa.Enum(*values, name=name, native_enum=False),
                    nullable=False,
                    server_default="UNKNOWN",
                )
            )
    op.execute(
        "UPDATE assessment_anatomical_sites SET role = 'PRIMARY' WHERE is_primary = 1"
        if op.get_bind().dialect.name == "sqlite"
        else "UPDATE assessment_anatomical_sites SET role = 'PRIMARY' WHERE is_primary"
    )

    op.create_table(
        "assessment_medications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("class_code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("dose_category", sa.String(length=16), nullable=False),
        sa.Column("frequency", sa.String(length=16), nullable=False),
        sa.Column("hours_since_last_dose", sa.Float(), nullable=True),
        sa.Column("pain_effect", sa.String(length=16), nullable=False),
        sa.Column("sedation_effect", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["pain_assessments.id"]),
        sa.ForeignKeyConstraint(["class_code"], ["medication_classes.code"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assessment_medications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_medications_assessment_id"),
            ["assessment_id"],
            unique=False,
        )

    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_name", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("feature_schema_version", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(sa.Column("inference_ms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("priority_level", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column(
                "trajectory", sa.String(length=16), nullable=False, server_default="UNKNOWN"
            )
        )
        batch_op.add_column(
            sa.Column("baseline", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(sa.Column("data_quality_score", sa.Float(), nullable=True))

    with op.batch_alter_table("dataset_versions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "generator_version", sa.String(length=16), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(
            sa.Column("n_patients", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "storage_format", sa.String(length=16), nullable=False, server_default="jsonl"
            )
        )
        batch_op.add_column(
            sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("scenario_versions", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(sa.Column("split", sa.JSON(), nullable=False, server_default="{}"))

    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "model_name", sa.String(length=64), nullable=False, server_default="pain-model"
            )
        )
        batch_op.add_column(
            sa.Column(
                "feature_schema_version",
                sa.String(length=16),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column("n_validation", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("f1_band", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("inference_ms", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("feature_importance", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("comparison", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("training_profile", sa.JSON(), nullable=False, server_default="{}")
        )

    with op.batch_alter_table("ledger_blocks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "key_id",
                sa.String(length=48),
                nullable=False,
                server_default="ledger-signing-v1",
            )
        )

    op.drop_table("key_metadata")
    op.create_table(
        "key_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=48), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label", "version"),
    )
    with op.batch_alter_table("key_metadata", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_key_metadata_label"), ["label"], unique=False)

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("QUEUED", "RUNNING", "DONE", "FAILED", name="jobstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_background_jobs_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_background_jobs_status"), ["status"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_background_jobs_created_at"), ["created_at"], unique=False
        )

    op.execute(
        "UPDATE audit_logs SET event_type = 'PREDICTION_GENERATED' "
        "WHERE event_type = 'PREDICTION_RUN'"
    )
    op.execute(
        "UPDATE ledger_blocks SET event_type = 'PREDICTION_GENERATED' "
        "WHERE event_type = 'PREDICTION_RUN'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE audit_logs SET event_type = 'PREDICTION_RUN' "
        "WHERE event_type = 'PREDICTION_GENERATED'"
    )
    op.execute(
        "UPDATE ledger_blocks SET event_type = 'PREDICTION_RUN' "
        "WHERE event_type = 'PREDICTION_GENERATED'"
    )
    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_background_jobs_created_at"))
        batch_op.drop_index(batch_op.f("ix_background_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_background_jobs_kind"))
    op.drop_table("background_jobs")

    op.drop_table("key_metadata")
    op.create_table(
        "key_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=48), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label"),
    )

    with op.batch_alter_table("ledger_blocks", schema=None) as batch_op:
        batch_op.drop_column("key_id")

    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        for column in (
            "training_profile",
            "comparison",
            "feature_importance",
            "inference_ms",
            "f1_band",
            "n_validation",
            "feature_schema_version",
            "model_name",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("dataset_versions", schema=None) as batch_op:
        for column in (
            "split",
            "scenario_versions",
            "parameters",
            "storage_format",
            "n_patients",
            "generator_version",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        for column in (
            "data_quality_score",
            "baseline",
            "trajectory",
            "priority_level",
            "inference_ms",
            "feature_schema_version",
            "model_name",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("assessment_medications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_medications_assessment_id"))
    op.drop_table("assessment_medications")

    with op.batch_alter_table("assessment_anatomical_sites", schema=None) as batch_op:
        for column in (
            "course",
            "pattern",
            "onset",
            "quality_codes",
            "radiation_from_side",
            "radiation_from_code",
            "sequence",
            "role",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        for column in (
            "review_comment",
            "review_agreement",
            "impact_self_care",
            "impact_daily_activity",
            "impact_work",
            "impact_sleep",
            "impact_mobility",
            "variable_timing",
            "evening_pain",
            "afternoon_pain",
            "recurrent",
            "onset_speed",
        ):
            batch_op.drop_column(column)

    op.drop_table("medication_classes")

    with op.batch_alter_table("anatomical_relationships", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_anatomical_relationships_relation"))
        batch_op.drop_index(batch_op.f("ix_anatomical_relationships_target_code"))
        batch_op.drop_index(batch_op.f("ix_anatomical_relationships_source_code"))
    op.drop_table("anatomical_relationships")

    with op.batch_alter_table("anatomical_structures", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_anatomical_structures_parent_code"))
        batch_op.drop_index(batch_op.f("ix_anatomical_structures_subregion"))
        for column in (
            "description",
            "pain_selectable",
            "has_mesh",
            "system",
            "parent_code",
            "subregion",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("session_tokens", schema=None) as batch_op:
        batch_op.drop_column("last_used_at")
        batch_op.drop_column("client_ip")

    op.execute("UPDATE users SET role = 'ADMIN' WHERE role = 'SUPER_ADMIN'")
    op.execute("UPDATE users SET role = 'DOCTOR' WHERE role = 'CLINIC_ADMIN'")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("preferred_language")
        batch_op.drop_column("sessions_revoked_at")
