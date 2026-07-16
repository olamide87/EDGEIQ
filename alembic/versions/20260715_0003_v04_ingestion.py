"""Add EDGE IQ v0.4 automated ingestion infrastructure.

Revision ID: 20260715_0003
Revises: 20260715_0002
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260715_0003"
down_revision: str | None = "20260715_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("raw_alias", sa.String(200), nullable=False),
        sa.Column("normalized_alias", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "normalized_alias", name="uq_player_alias_provider_name"),
    )
    op.create_index("ix_player_aliases_player_id", "player_aliases", ["player_id"])
    op.create_index("ix_player_aliases_provider", "player_aliases", ["provider"])
    op.create_index("ix_player_aliases_normalized_alias", "player_aliases", ["normalized_alias"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_ingestion_jobs_correlation_id", "ingestion_jobs", ["correlation_id"], unique=True)
    op.create_index("ix_ingestion_jobs_provider", "ingestion_jobs", ["provider"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_started_at", "ingestion_jobs", ["started_at"])

    op.create_table(
        "provider_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_successful_fetch", sa.DateTime(timezone=True)),
        sa.Column("last_failed_fetch", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("average_latency_ms", sa.Numeric(12, 3), nullable=False),
        sa.Column("successful_fetches", sa.Integer(), nullable=False),
        sa.Column("records_returned", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_health_provider", "provider_health", ["provider"], unique=True)
    op.create_index("ix_provider_health_status", "provider_health", ["status"])

    op.create_table(
        "odds_snapshot_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ingestion_job_id", sa.Integer(), sa.ForeignKey("ingestion_jobs.id"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_suppressed", sa.Boolean(), nullable=False),
        sa.Column("quality_flags", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_odds_snapshot_batches_ingestion_job_id",
        "odds_snapshot_batches", ["ingestion_job_id"], unique=True,
    )
    op.create_index("ix_odds_snapshot_batches_provider", "odds_snapshot_batches", ["provider"])
    op.create_index("ix_odds_snapshot_batches_payload_hash", "odds_snapshot_batches", ["payload_hash"])
    op.create_index("ix_odds_snapshot_batches_captured_at", "odds_snapshot_batches", ["captured_at"])
    op.create_index(
        "ix_snapshot_batches_provider_captured",
        "odds_snapshot_batches", ["provider", "captured_at"],
    )

    with op.batch_alter_table("prop_lines") as batch_op:
        batch_op.add_column(sa.Column("provider_key", sa.String(80)))
        batch_op.add_column(sa.Column("raw_player_name", sa.String(200)))
        batch_op.add_column(sa.Column("snapshot_batch_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_prop_lines_snapshot_batch",
            "odds_snapshot_batches",
            ["snapshot_batch_id"],
            ["id"],
        )
    op.create_index("ix_prop_lines_provider_key", "prop_lines", ["provider_key"])
    op.create_index("ix_prop_lines_snapshot_batch_id", "prop_lines", ["snapshot_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_prop_lines_snapshot_batch_id", table_name="prop_lines")
    op.drop_index("ix_prop_lines_provider_key", table_name="prop_lines")
    with op.batch_alter_table("prop_lines") as batch_op:
        batch_op.drop_column("snapshot_batch_id")
        batch_op.drop_column("raw_player_name")
        batch_op.drop_column("provider_key")
    op.drop_table("odds_snapshot_batches")
    op.drop_table("provider_health")
    op.drop_table("ingestion_jobs")
    op.drop_table("player_aliases")
