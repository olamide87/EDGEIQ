from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class Market(str, Enum):
    QB_PASSING_YARDS = "player_pass_yds"
    QB_PASSING_TDS = "player_pass_tds"
    QB_INTERCEPTIONS = "player_pass_interceptions"
    PLAYER_RECEPTIONS = "player_receptions"
    ANYTIME_TD = "player_anytime_td"


class Side(str, Enum):
    OVER = "over"
    UNDER = "under"
    YES = "yes"
    NO = "no"


class Offer(BaseModel):
    event_id: str
    event_name: str
    commence_time: datetime | None = None
    bookmaker: str
    market: Market
    player: str
    side: Side
    line: float | None = None
    american_odds: int
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RankedOffer(BaseModel):
    offer: Offer
    decimal_odds: float
    implied_probability: float
    rank: int


class MarketBoard(BaseModel):
    player: str
    market: Market
    side: Side
    offers: list[RankedOffer]
