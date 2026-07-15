"""Create EDGE IQ v0.2 persistence schema."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260715_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sport", sa.String(80), nullable=False),
        sa.Column("commence_time", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_external_id", "events", ["external_id"], unique=True)
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("team", sa.String(100)),
        sa.Column("position", sa.String(30)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_players_name", "players", ["name"], unique=True)
    op.create_table(
        "sportsbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sportsbooks_name", "sportsbooks", ["name"], unique=True)
    op.create_table(
        "prop_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("sportsbook_id", sa.Integer(), sa.ForeignKey("sportsbooks.id"), nullable=False),
        sa.Column("market", sa.String(80), nullable=False),
        sa.Column("side", sa.String(20), nullable=False),
        sa.Column("line", sa.Numeric(10, 3)),
        sa.Column("american_odds", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id", "player_id", "sportsbook_id", "market", "side", "line",
            "american_odds", "captured_at", name="uq_prop_line_snapshot",
        ),
    )
    for column in ("event_id", "player_id", "sportsbook_id", "market", "side", "captured_at"):
        op.create_index(f"ix_prop_lines_{column}", "prop_lines", [column])
    op.create_index("ix_prop_lines_lookup", "prop_lines", ["player_id", "market", "side"])
    op.create_table(
        "projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prop_line_id", sa.Integer(), sa.ForeignKey("prop_lines.id"), nullable=False),
        sa.Column("model_probability", sa.Numeric(7, 6), nullable=False),
        sa.Column("projected_value", sa.Numeric(12, 4)),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projections_prop_line_id", "projections", ["prop_line_id"])
    op.create_index("ix_projections_created_at", "projections", ["created_at"])
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("projection_id", sa.Integer(), sa.ForeignKey("projections.id"), nullable=False),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column("implied_probability", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_return", sa.Numeric(9, 6), nullable=False),
        sa.Column("recommended_stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("rationale", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recommendations_projection_id", "recommendations", ["projection_id"], unique=True)
    op.create_index("ix_recommendations_rating", "recommendations", ["rating"])
    op.create_index("ix_recommendations_created_at", "recommendations", ["created_at"])


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("projections")
    op.drop_table("prop_lines")
    op.drop_table("sportsbooks")
    op.drop_table("players")
    op.drop_table("events")
