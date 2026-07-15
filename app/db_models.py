from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    team: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    prop_lines: Mapped[list["PropLine"]] = relationship(back_populates="player")


class Sportsbook(Base):
    __tablename__ = "sportsbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    prop_lines: Mapped[list["PropLine"]] = relationship(back_populates="sportsbook")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    sport: Mapped[str] = mapped_column(String(80), default="americanfootball_nfl")
    commence_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    prop_lines: Mapped[list["PropLine"]] = relationship(back_populates="event")


class PropLine(Base):
    __tablename__ = "prop_lines"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "player_id", "sportsbook_id", "market", "side", "line",
            "american_odds", "captured_at", name="uq_prop_line_snapshot",
        ),
        Index("ix_prop_lines_lookup", "player_id", "market", "side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    sportsbook_id: Mapped[int] = mapped_column(ForeignKey("sportsbooks.id"), index=True)
    market: Mapped[str] = mapped_column(String(80), index=True)
    side: Mapped[str] = mapped_column(String(20), index=True)
    line: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    american_odds: Mapped[int]
    fair_market_probability: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    event: Mapped[Event] = relationship(back_populates="prop_lines")
    player: Mapped[Player] = relationship(back_populates="prop_lines")
    sportsbook: Mapped[Sportsbook] = relationship(back_populates="prop_lines")
    projections: Mapped[list["Projection"]] = relationship(back_populates="prop_line")


class Projection(Base):
    __tablename__ = "projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    prop_line_id: Mapped[int] = mapped_column(ForeignKey("prop_lines.id"), index=True)
    model_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    projected_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    model_name: Mapped[str] = mapped_column(String(120), default="default")
    model_input_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confidence_data_quality: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    confidence_sample_size: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    confidence_role_stability: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    confidence_injury_certainty: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    confidence_matchup_certainty: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    confidence_market_stability: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    overall_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    prop_line: Mapped[PropLine] = relationship(back_populates="projections")
    recommendation: Mapped["Recommendation | None"] = relationship(
        back_populates="projection", uselist=False, cascade="all, delete-orphan"
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    projection_id: Mapped[int] = mapped_column(
        ForeignKey("projections.id"), unique=True, index=True
    )
    rating: Mapped[str] = mapped_column(String(20), index=True)
    implied_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    expected_return: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    fair_market_probability: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    data_age_seconds: Mapped[int] = mapped_column(default=0)
    rejection_reasons: Mapped[str] = mapped_column(Text, default="[]")
    recommended_stake: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    rationale: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    projection: Mapped[Projection] = relationship(back_populates="recommendation")
    paper_bets: Mapped[list["PaperBet"]] = relationship(back_populates="recommendation")


class PaperBet(Base):
    __tablename__ = "paper_bets"
    __table_args__ = (
        Index("ix_paper_bets_exposure", "status", "player_id", "event_id", "placed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    prop_line_id: Mapped[int] = mapped_column(ForeignKey("prop_lines.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    sportsbook_id: Mapped[int] = mapped_column(ForeignKey("sportsbooks.id"), index=True)
    market: Mapped[str] = mapped_column(String(80), index=True)
    side: Mapped[str] = mapped_column(String(20))
    opening_line: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    opening_odds: Mapped[int]
    bet_line: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    bet_odds: Mapped[int]
    stake: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expected_value: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    recommendation_rating: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    correlation_flags: Mapped[str] = mapped_column(Text, default="[]")
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    recommendation: Mapped[Recommendation] = relationship(back_populates="paper_bets")
    prop_line: Mapped[PropLine] = relationship()
    player: Mapped[Player] = relationship()
    event: Mapped[Event] = relationship()
    sportsbook: Mapped[Sportsbook] = relationship()
    closing_snapshot: Mapped["ClosingLineSnapshot | None"] = relationship(
        back_populates="paper_bet", uselist=False, cascade="all, delete-orphan"
    )
    settlement: Mapped["Settlement | None"] = relationship(
        back_populates="paper_bet", uselist=False, cascade="all, delete-orphan"
    )


class ClosingLineSnapshot(Base):
    __tablename__ = "closing_line_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_bet_id: Mapped[int] = mapped_column(ForeignKey("paper_bets.id"), unique=True, index=True)
    closing_line: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    closing_odds: Mapped[int]
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    line_movement: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    price_movement: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    beat_closing_line: Mapped[bool] = mapped_column(Boolean)
    clv_percentage: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    paper_bet: Mapped[PaperBet] = relationship(back_populates="closing_snapshot")


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_bet_id: Mapped[int] = mapped_column(ForeignKey("paper_bets.id"), unique=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    result_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    net_profit: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    paper_bet: Mapped[PaperBet] = relationship(back_populates="settlement")
