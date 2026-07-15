"""Add EDGE IQ v0.3 market quality and paper analytics.

Revision ID: 20260715_0002
Revises: 20260715_0001
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260715_0002"
down_revision: str | None = "20260715_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("prop_lines", sa.Column("fair_market_probability", sa.Numeric(7, 6)))
    op.add_column(
        "projections",
        sa.Column("model_input_captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE projections SET model_input_captured_at = created_at "
                "WHERE model_input_captured_at IS NULL")
    )
    with op.batch_alter_table("projections") as batch_op:
        batch_op.alter_column(
            "model_input_captured_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    for name in (
        "confidence_data_quality", "confidence_sample_size", "confidence_role_stability",
        "confidence_injury_certainty", "confidence_matchup_certainty", "confidence_market_stability",
        "overall_confidence",
    ):
        op.add_column(
            "projections",
            sa.Column(name, sa.Numeric(5, 4), nullable=False, server_default="1"),
        )
    op.add_column("recommendations", sa.Column("fair_market_probability", sa.Numeric(7, 6)))
    op.add_column(
        "recommendations", sa.Column("data_age_seconds", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "recommendations", sa.Column("rejection_reasons", sa.Text(), nullable=False, server_default="[]")
    )

    op.create_table(
        "paper_bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), sa.ForeignKey("recommendations.id"), nullable=False),
        sa.Column("prop_line_id", sa.Integer(), sa.ForeignKey("prop_lines.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("sportsbook_id", sa.Integer(), sa.ForeignKey("sportsbooks.id"), nullable=False),
        sa.Column("market", sa.String(80), nullable=False),
        sa.Column("side", sa.String(20), nullable=False),
        sa.Column("opening_line", sa.Numeric(10, 3)),
        sa.Column("opening_odds", sa.Integer(), nullable=False),
        sa.Column("bet_line", sa.Numeric(10, 3)),
        sa.Column("bet_odds", sa.Integer(), nullable=False),
        sa.Column("stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("expected_value", sa.Numeric(9, 6), nullable=False),
        sa.Column("recommendation_rating", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("correlation_flags", sa.Text(), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "recommendation_id", "prop_line_id", "player_id", "event_id", "sportsbook_id",
        "market", "recommendation_rating", "status", "placed_at",
    ):
        op.create_index(f"ix_paper_bets_{column}", "paper_bets", [column])
    op.create_index(
        "ix_paper_bets_exposure", "paper_bets", ["status", "player_id", "event_id", "placed_at"]
    )
    op.create_table(
        "closing_line_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_bet_id", sa.Integer(), sa.ForeignKey("paper_bets.id"), nullable=False),
        sa.Column("closing_line", sa.Numeric(10, 3)),
        sa.Column("closing_odds", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("line_movement", sa.Numeric(10, 3)),
        sa.Column("price_movement", sa.Numeric(10, 6), nullable=False),
        sa.Column("beat_closing_line", sa.Boolean(), nullable=False),
        sa.Column("clv_percentage", sa.Numeric(10, 6)),
    )
    op.create_index(
        "ix_closing_line_snapshots_paper_bet_id", "closing_line_snapshots", ["paper_bet_id"], unique=True
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_bet_id", sa.Integer(), sa.ForeignKey("paper_bets.id"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("result_value", sa.Numeric(12, 4)),
        sa.Column("net_profit", sa.Numeric(12, 2), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settlements_paper_bet_id", "settlements", ["paper_bet_id"], unique=True)
    op.create_index("ix_settlements_outcome", "settlements", ["outcome"])
    op.create_index("ix_settlements_settled_at", "settlements", ["settled_at"])


def downgrade() -> None:
    op.drop_table("settlements")
    op.drop_table("closing_line_snapshots")
    op.drop_table("paper_bets")
    op.drop_column("recommendations", "rejection_reasons")
    op.drop_column("recommendations", "data_age_seconds")
    op.drop_column("recommendations", "fair_market_probability")
    for name in (
        "overall_confidence", "confidence_market_stability", "confidence_matchup_certainty",
        "confidence_injury_certainty", "confidence_role_stability", "confidence_sample_size",
        "confidence_data_quality", "model_input_captured_at",
    ):
        op.drop_column("projections", name)
    op.drop_column("prop_lines", "fair_market_probability")
