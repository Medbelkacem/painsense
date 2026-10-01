"""External dataset synchronisation

Adds the catalogue of datasets published elsewhere, the acquired copies of them, and the
run and event log that records why each one is or is not held. Also gives `diseases` the
provenance columns that let an automatically discovered disease sit in the same table as
a curated comorbidity without being offered in a clinical form.

Revision ID: c3f1a9d47e52
Revises: b8ab41f8b0b8
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f1a9d47e52"
down_revision = "b8ab41f8b0b8"
branch_labels = None
depends_on = None


def _enum(*values: str, name: str) -> sa.Enum:
    # Mirrors `models._enum`: stored as VARCHAR with a check constraint rather than a
    # native database enum, so adding a member later is a check-constraint change and not
    # a type migration on every dialect.
    return sa.Enum(*values, name=name, native_enum=False)


ACCESS = _enum(
    "OPEN",
    "REGISTRATION_REQUIRED",
    "CREDENTIALED",
    "AGREEMENT_REQUIRED",
    "DOCUMENT_ONLY",
    "UNKNOWN",
    name="sourceaccess",
)
AVAILABILITY = _enum(
    "NOT_ATTEMPTED", "METADATA_ONLY", "AVAILABLE", "FAILED", name="availability"
)
VERDICT = _enum(
    "PERMISSIVE",
    "RESEARCH_ONLY",
    "REVIEW_REQUIRED",
    "RESTRICTED",
    "UNKNOWN",
    name="licenceverdict",
)
GRANULARITY = _enum("SUBJECT_LEVEL", "AGGREGATE", "UNKNOWN", name="granularity")
QUALITY = _enum(
    "NOT_ASSESSED", "PASSED", "PASSED_WITH_WARNINGS", "FAILED", name="qualitystatus"
)
STAGE = _enum(
    "DISCOVER",
    "IDENTIFY_DISEASE",
    "ACQUIRE",
    "VALIDATE",
    "PREPROCESS",
    "SUITABILITY",
    "TRAIN",
    name="syncstage",
)
OUTCOME = _enum("OK", "SKIPPED", "FAILED", name="syncoutcome")
RUN_STATUS = _enum("RUNNING", "DONE", "FAILED", name="runstatus")


def upgrade() -> None:
    with op.batch_alter_table("diseases") as batch:
        batch.add_column(
            sa.Column("curated", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column(
                "origin",
                sa.String(length=32),
                nullable=False,
                server_default="knowledge_base",
            )
        )
        batch.add_column(sa.Column("source_ref", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_diseases_curated", "diseases", ["curated"])

    op.create_table(
        "external_sources",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("organisation", sa.String(length=160), nullable=False),
        sa.Column("homepage", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_external_sources_enabled", "external_sources", ["enabled"])
    op.create_index("ix_external_sources_next_run_at", "external_sources", ["next_run_at"])

    op.create_table(
        "external_datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_code",
            sa.String(length=32),
            sa.ForeignKey("external_sources.code"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=400), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("download_url", sa.String(length=1000), nullable=True),
        sa.Column("download_mechanism", sa.String(length=80), nullable=False),
        sa.Column(
            "disease_code", sa.String(length=48), sa.ForeignKey("diseases.code"), nullable=True
        ),
        sa.Column("disease_match", sa.JSON(), nullable=False),
        sa.Column("dataset_type", sa.String(length=32), nullable=False),
        sa.Column("granularity", GRANULARITY, nullable=False),
        sa.Column("modalities", sa.JSON(), nullable=False),
        sa.Column("target_labels", sa.JSON(), nullable=False),
        sa.Column("access_status", ACCESS, nullable=False),
        sa.Column("access_procedure", sa.JSON(), nullable=False),
        sa.Column("licence", sa.String(length=255), nullable=True),
        sa.Column("licence_url", sa.String(length=500), nullable=True),
        sa.Column("licence_verdict", VERDICT, nullable=False),
        sa.Column("redistribution", sa.String(length=255), nullable=False),
        sa.Column("publisher_version", sa.String(length=64), nullable=True),
        sa.Column("publisher_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_claimed", sa.Integer(), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("availability", AVAILABILITY, nullable=False),
        sa.Column("metadata_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_code", "external_id", name="uq_external_datasets_source_id"),
    )
    for column in (
        "source_code",
        "external_id",
        "disease_code",
        "dataset_type",
        "access_status",
        "relevance",
        "availability",
        "metadata_fingerprint",
        "next_attempt_at",
    ):
        op.create_index(f"ix_external_datasets_{column}", "external_datasets", [column])

    op.create_table(
        "external_dataset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("external_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("licence", sa.String(length=255), nullable=True),
        sa.Column("storage_backend", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_format", sa.String(length=16), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("records", sa.Integer(), nullable=True),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("missing_value_pct", sa.Float(), nullable=True),
        sa.Column("quality_status", QUALITY, nullable=False),
        sa.Column("quality_findings", sa.JSON(), nullable=False),
        sa.Column("preprocessed_key", sa.String(length=500), nullable=True),
        sa.Column("suitability", sa.JSON(), nullable=False),
        sa.Column("trainable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "training_job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id"), nullable=True
        ),
        sa.UniqueConstraint("dataset_id", "sha256", name="uq_external_versions_content"),
        sa.UniqueConstraint("dataset_id", "version", name="uq_external_versions_label"),
    )
    for column in ("dataset_id", "acquired_at", "sha256", "quality_status", "trainable"):
        op.create_index(
            f"ix_external_dataset_versions_{column}", "external_dataset_versions", [column]
        )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_code", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", RUN_STATUS, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("background_jobs.id"), nullable=True),
    )
    for column in ("source_code", "status", "started_at"):
        op.create_index(f"ix_sync_runs_{column}", "sync_runs", [column])

    op.create_table(
        "sync_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("external_datasets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_code", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("stage", STAGE, nullable=False),
        sa.Column("outcome", OUTCOME, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    for column in ("run_id", "dataset_id", "at", "source_code", "stage", "outcome"):
        op.create_index(f"ix_sync_events_{column}", "sync_events", [column])


def downgrade() -> None:
    op.drop_table("sync_events")
    op.drop_table("sync_runs")
    op.drop_table("external_dataset_versions")
    op.drop_table("external_datasets")
    op.drop_table("external_sources")
    op.drop_index("ix_diseases_curated", table_name="diseases")
    with op.batch_alter_table("diseases") as batch:
        batch.drop_column("discovered_at")
        batch.drop_column("source_ref")
        batch.drop_column("origin")
        batch.drop_column("curated")
