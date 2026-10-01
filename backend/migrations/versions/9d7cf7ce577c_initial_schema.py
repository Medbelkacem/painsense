import sqlalchemy as sa
from alembic import op

revision = "9d7cf7ce577c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_questions",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("group", sa.String(length=24), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=True),
        sa.Column("minimum", sa.Float(), nullable=True),
        sa.Column("maximum", sa.Float(), nullable=True),
        sa.Column("help_text", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("clinical_questions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clinical_questions_group"), ["group"], unique=False
        )

    op.create_table(
        "clinical_rules",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("clinical_rules", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clinical_rules_severity"), ["severity"], unique=False
        )

    op.create_table(
        "confounders",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("affects", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("n_rows", sa.Integer(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("distribution", sa.JSON(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("dataset_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_dataset_versions_version"), ["version"], unique=True
        )

    op.create_table(
        "diseases",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("pain_relevant", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("diseases", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_diseases_category"), ["category"], unique=False)

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
    op.create_table(
        "ledger_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("resource", sa.String(length=48), nullable=False),
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("block_hash", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("signature_scheme", sa.String(length=48), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ledger_blocks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ledger_blocks_block_hash"), ["block_hash"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_ledger_blocks_height"), ["height"], unique=True)
        batch_op.create_index(
            batch_op.f("ix_ledger_blocks_record_id"), ["record_id"], unique=False
        )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=80), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("n_train", sa.Integer(), nullable=False),
        sa.Column("n_test", sa.Integer(), nullable=False),
        sa.Column("mae", sa.Float(), nullable=False),
        sa.Column("rmse", sa.Float(), nullable=False),
        sa.Column("r2", sa.Float(), nullable=False),
        sa.Column("pearson", sa.Float(), nullable=False),
        sa.Column("cv_folds", sa.Integer(), nullable=False),
        sa.Column("cv_mae_mean", sa.Float(), nullable=False),
        sa.Column("cv_mae_sd", sa.Float(), nullable=False),
        sa.Column("residual_sd", sa.Float(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("artifact_name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_model_versions_is_active"), ["is_active"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_model_versions_version"), ["version"], unique=True)

    op.create_table(
        "pain_causes",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("group", sa.String(length=24), nullable=False),
        sa.Column("pain_types", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("pain_causes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pain_causes_group"), ["group"], unique=False)

    op.create_table(
        "pain_factors",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("pain_factors", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pain_factors_kind"), ["kind"], unique=False)

    op.create_table(
        "pain_locations",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("parent_code", sa.String(length=48), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("pain_locations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pain_locations_region"), ["region"], unique=False)

    op.create_table(
        "pain_qualities",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("neuropathic_hint", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "pain_types",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("group", sa.String(length=24), nullable=False),
        sa.Column("parent_code", sa.String(length=48), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("pain_types", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pain_types_group"), ["group"], unique=False)

    op.create_table(
        "symptoms",
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("group", sa.String(length=24), nullable=False),
        sa.Column("systemic", sa.Boolean(), nullable=False),
        sa.Column("alarm", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    with op.batch_alter_table("symptoms", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_symptoms_group"), ["group"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=190), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("registration_number", sa.String(length=48), nullable=True),
        sa.Column("speciality", sa.String(length=120), nullable=True),
        sa.Column(
            "role", sa.Enum("DOCTOR", "ADMIN", name="role", native_enum=False), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=190), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("resource", sa.String(length=48), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_logs_event_type"), ["event_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_audit_logs_resource_id"), ["resource_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_audit_logs_seq"), ["seq"], unique=True)
        batch_op.create_index(
            batch_op.f("ix_audit_logs_timestamp"), ["timestamp"], unique=False
        )

    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column(
            "sex",
            sa.Enum("F", "M", "OTHER", "UNDISCLOSED", name="sex", native_enum=False),
            nullable=False,
        ),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("ward", sa.String(length=80), nullable=True),
        sa.Column(
            "smoking_status",
            sa.Enum(
                "NEVER", "FORMER", "CURRENT", "UNKNOWN", name="smokingstatus", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("medical_history", sa.Text(), nullable=True),
        sa.Column("previous_surgeries", sa.Text(), nullable=True),
        sa.Column("allergies", sa.Text(), nullable=True),
        sa.Column("family_history", sa.Text(), nullable=True),
        sa.Column("lifestyle_notes", sa.Text(), nullable=True),
        sa.Column("identity_blob", sa.LargeBinary(), nullable=True),
        sa.Column("identity_key", sa.LargeBinary(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_patients_code"), ["code"], unique=True)
        batch_op.create_index(
            batch_op.f("ix_patients_is_synthetic"), ["is_synthetic"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_patients_source_ref"), ["source_ref"], unique=True)

    op.create_table(
        "session_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("session_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_session_tokens_token_hash"), ["token_hash"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_session_tokens_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "pain_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT", "ESTIMATED", "VALIDATED", name="assessmentstatus", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_age_years", sa.Integer(), nullable=True),
        sa.Column(
            "onset",
            sa.Enum("SUDDEN", "GRADUAL", "UNKNOWN", name="onset", native_enum=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_hours", sa.Float(), nullable=True),
        sa.Column(
            "pattern",
            sa.Enum(
                "CONSTANT",
                "INTERMITTENT",
                "EPISODIC",
                "UNKNOWN",
                name="pattern",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "course",
            sa.Enum(
                "IMPROVING",
                "STABLE",
                "WORSENING",
                "PROGRESSIVE",
                "UNKNOWN",
                name="course",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("episodes_per_day", sa.Float(), nullable=True),
        sa.Column("episode_minutes", sa.Float(), nullable=True),
        sa.Column("night_pain", sa.Boolean(), nullable=False),
        sa.Column("morning_pain", sa.Boolean(), nullable=False),
        sa.Column("pain_after_activity", sa.Boolean(), nullable=False),
        sa.Column("pain_at_rest", sa.Boolean(), nullable=False),
        sa.Column("radiates", sa.Boolean(), nullable=False),
        sa.Column("radiation_description", sa.Text(), nullable=True),
        sa.Column("radiation_numbness", sa.Boolean(), nullable=False),
        sa.Column("radiation_tingling", sa.Boolean(), nullable=False),
        sa.Column("radiation_weakness", sa.Boolean(), nullable=False),
        sa.Column("recent_trauma", sa.Boolean(), nullable=False),
        sa.Column("recent_surgery", sa.Boolean(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validated_by", sa.Uuid(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.ForeignKeyConstraint(
            ["validated_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pain_assessments_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_pain_assessments_doctor_id"), ["doctor_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_pain_assessments_is_synthetic"), ["is_synthetic"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_pain_assessments_patient_id"), ["patient_id"], unique=False
        )

    op.create_table(
        "patient_conditions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("disease_code", sa.String(length=48), nullable=False),
        sa.Column("diagnosed_year", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["disease_code"],
            ["diseases.code"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", "disease_code"),
    )
    with op.batch_alter_table("patient_conditions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_patient_conditions_patient_id"), ["patient_id"], unique=False
        )

    op.create_table(
        "patient_medications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("dose", sa.String(length=80), nullable=True),
        sa.Column("frequency", sa.String(length=80), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("is_analgesic", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("patient_medications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_patient_medications_patient_id"), ["patient_id"], unique=False
        )

    op.create_table(
        "assessment_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("question_code", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["question_code"],
            ["clinical_questions.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "question_code"),
    )
    with op.batch_alter_table("assessment_answers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_answers_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "assessment_confounders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("confounder_code", sa.String(length=48), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["confounder_code"],
            ["confounders.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "confounder_code"),
    )
    with op.batch_alter_table("assessment_confounders", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_confounders_assessment_id"),
            ["assessment_id"],
            unique=False,
        )

    op.create_table(
        "assessment_factors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("factor_code", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["factor_code"],
            ["pain_factors.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "factor_code"),
    )
    with op.batch_alter_table("assessment_factors", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_factors_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "assessment_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("location_code", sa.String(length=48), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["location_code"],
            ["pain_locations.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "location_code"),
    )
    with op.batch_alter_table("assessment_locations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_locations_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "assessment_qualities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("quality_code", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["quality_code"],
            ["pain_qualities.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "quality_code"),
    )
    with op.batch_alter_table("assessment_qualities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_qualities_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "assessment_symptoms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("symptom_code", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["symptom_code"],
            ["symptoms.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "symptom_code"),
    )
    with op.batch_alter_table("assessment_symptoms", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_symptoms_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "clinical_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("clinical_notes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clinical_notes_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "medical_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "XRAY",
                "CT",
                "MRI",
                "ULTRASOUND",
                "ECG",
                "LABORATORY",
                "REPORT",
                "PRESCRIPTION",
                "OTHER",
                name="documentkind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_name", sa.String(length=80), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_name"),
    )
    with op.batch_alter_table("medical_documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_medical_documents_assessment_id"), ["assessment_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_medical_documents_patient_id"), ["patient_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_medical_documents_sha256"), ["sha256"], unique=False
        )

    op.create_table(
        "pain_predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("dataset_version", sa.String(length=64), nullable=True),
        sa.Column("estimated_pain", sa.Float(), nullable=True),
        sa.Column("interval_low", sa.Float(), nullable=True),
        sa.Column("interval_high", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=16), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=True),
        sa.Column("priority_factors", sa.JSON(), nullable=False),
        sa.Column(
            "data_quality",
            sa.Enum(
                "GOOD",
                "ADEQUATE",
                "LIMITED",
                "INSUFFICIENT",
                name="dataquality",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("quality_issues", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("confounder_notes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pain_predictions_assessment_id"), ["assessment_id"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_pain_predictions_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_pain_predictions_patient_id"), ["patient_id"], unique=False
        )

    op.create_table(
        "physiological_measurements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hr", sa.Float(), nullable=True),
        sa.Column("resp_rate", sa.Float(), nullable=True),
        sa.Column("sbp", sa.Float(), nullable=True),
        sa.Column("dbp", sa.Float(), nullable=True),
        sa.Column("spo2", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("glucose_mmol", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("physiological_measurements", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_physiological_measurements_assessment_id"),
            ["assessment_id"],
            unique=True,
        )

    op.create_table(
        "self_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("nrs", sa.Float(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["pain_assessments.id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("self_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_self_reports_assessment_id"), ["assessment_id"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_self_reports_patient_id"), ["patient_id"], unique=False
        )

    op.create_table(
        "prediction_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=False),
        sa.Column("context_notes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["pain_predictions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["rule_code"],
            ["clinical_rules.code"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prediction_alerts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_prediction_alerts_prediction_id"), ["prediction_id"], unique=False
        )

    op.create_table(
        "prediction_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("cause_code", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("matched", sa.JSON(), nullable=False),
        sa.Column("missing", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cause_code"],
            ["pain_causes.code"],
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["pain_predictions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prediction_categories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_prediction_categories_prediction_id"),
            ["prediction_id"],
            unique=False,
        )

    op.create_table(
        "prediction_contributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("contribution", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["pain_predictions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prediction_contributions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_prediction_contributions_prediction_id"),
            ["prediction_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("prediction_contributions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prediction_contributions_prediction_id"))

    op.drop_table("prediction_contributions")
    with op.batch_alter_table("prediction_categories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prediction_categories_prediction_id"))

    op.drop_table("prediction_categories")
    with op.batch_alter_table("prediction_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prediction_alerts_prediction_id"))

    op.drop_table("prediction_alerts")
    with op.batch_alter_table("self_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_self_reports_patient_id"))
        batch_op.drop_index(batch_op.f("ix_self_reports_assessment_id"))

    op.drop_table("self_reports")
    with op.batch_alter_table("physiological_measurements", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_physiological_measurements_assessment_id"))

    op.drop_table("physiological_measurements")
    with op.batch_alter_table("pain_predictions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_predictions_patient_id"))
        batch_op.drop_index(batch_op.f("ix_pain_predictions_created_at"))
        batch_op.drop_index(batch_op.f("ix_pain_predictions_assessment_id"))

    op.drop_table("pain_predictions")
    with op.batch_alter_table("medical_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_medical_documents_sha256"))
        batch_op.drop_index(batch_op.f("ix_medical_documents_patient_id"))
        batch_op.drop_index(batch_op.f("ix_medical_documents_assessment_id"))

    op.drop_table("medical_documents")
    with op.batch_alter_table("clinical_notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clinical_notes_assessment_id"))

    op.drop_table("clinical_notes")
    with op.batch_alter_table("assessment_symptoms", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_symptoms_assessment_id"))

    op.drop_table("assessment_symptoms")
    with op.batch_alter_table("assessment_qualities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_qualities_assessment_id"))

    op.drop_table("assessment_qualities")
    with op.batch_alter_table("assessment_locations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_locations_assessment_id"))

    op.drop_table("assessment_locations")
    with op.batch_alter_table("assessment_factors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_factors_assessment_id"))

    op.drop_table("assessment_factors")
    with op.batch_alter_table("assessment_confounders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_confounders_assessment_id"))

    op.drop_table("assessment_confounders")
    with op.batch_alter_table("assessment_answers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_answers_assessment_id"))

    op.drop_table("assessment_answers")
    with op.batch_alter_table("patient_medications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patient_medications_patient_id"))

    op.drop_table("patient_medications")
    with op.batch_alter_table("patient_conditions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patient_conditions_patient_id"))

    op.drop_table("patient_conditions")
    with op.batch_alter_table("pain_assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_assessments_patient_id"))
        batch_op.drop_index(batch_op.f("ix_pain_assessments_is_synthetic"))
        batch_op.drop_index(batch_op.f("ix_pain_assessments_doctor_id"))
        batch_op.drop_index(batch_op.f("ix_pain_assessments_created_at"))

    op.drop_table("pain_assessments")
    with op.batch_alter_table("session_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_session_tokens_user_id"))
        batch_op.drop_index(batch_op.f("ix_session_tokens_token_hash"))

    op.drop_table("session_tokens")
    with op.batch_alter_table("patients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_patients_source_ref"))
        batch_op.drop_index(batch_op.f("ix_patients_is_synthetic"))
        batch_op.drop_index(batch_op.f("ix_patients_code"))

    op.drop_table("patients")
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_logs_timestamp"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_seq"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_resource_id"))
        batch_op.drop_index(batch_op.f("ix_audit_logs_event_type"))

    op.drop_table("audit_logs")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
    with op.batch_alter_table("symptoms", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_symptoms_group"))

    op.drop_table("symptoms")
    with op.batch_alter_table("pain_types", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_types_group"))

    op.drop_table("pain_types")
    op.drop_table("pain_qualities")
    with op.batch_alter_table("pain_locations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_locations_region"))

    op.drop_table("pain_locations")
    with op.batch_alter_table("pain_factors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_factors_kind"))

    op.drop_table("pain_factors")
    with op.batch_alter_table("pain_causes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pain_causes_group"))

    op.drop_table("pain_causes")
    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_versions_version"))
        batch_op.drop_index(batch_op.f("ix_model_versions_is_active"))

    op.drop_table("model_versions")
    with op.batch_alter_table("ledger_blocks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ledger_blocks_record_id"))
        batch_op.drop_index(batch_op.f("ix_ledger_blocks_height"))
        batch_op.drop_index(batch_op.f("ix_ledger_blocks_block_hash"))

    op.drop_table("ledger_blocks")
    op.drop_table("key_metadata")
    with op.batch_alter_table("diseases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_diseases_category"))

    op.drop_table("diseases")
    with op.batch_alter_table("dataset_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dataset_versions_version"))

    op.drop_table("dataset_versions")
    op.drop_table("confounders")
    with op.batch_alter_table("clinical_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clinical_rules_severity"))

    op.drop_table("clinical_rules")
    with op.batch_alter_table("clinical_questions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clinical_questions_group"))

    op.drop_table("clinical_questions")
