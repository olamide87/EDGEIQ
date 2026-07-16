from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models import Market, Side
from app.services.expected_value import Rating


class HealthResponse(BaseModel):
    status: str
    version: str


class PropResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    event_name: str
    player_id: int
    player_name: str
    sportsbook_id: int
    sportsbook_name: str
    market: Market
    side: Side
    line: float | None
    american_odds: int
    raw_implied_probability: float
    fair_market_probability: float | None = None
    vig_removed: bool = False
    selection_reason: str | None = None
    captured_at: datetime


class ConfidenceInput(BaseModel):
    data_quality: float = Field(default=1.0, ge=0, le=1)
    sample_size: float = Field(default=1.0, ge=0, le=1)
    role_stability: float = Field(default=1.0, ge=0, le=1)
    injury_certainty: float = Field(default=1.0, ge=0, le=1)
    matchup_certainty: float = Field(default=1.0, ge=0, le=1)
    market_stability: float = Field(default=1.0, ge=0, le=1)


class ConfidenceResponse(ConfidenceInput):
    overall_confidence: float


class ProjectionCreate(BaseModel):
    prop_line_id: int
    model_probability: float = Field(ge=0, le=1)
    projected_value: float | None = None
    model_name: str = Field(default="default", min_length=1, max_length=120)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: ConfidenceInput = Field(default_factory=ConfidenceInput)


class ProjectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prop_line_id: int
    model_probability: float
    projected_value: float | None
    model_name: str
    model_input_captured_at: datetime
    confidence: ConfidenceResponse
    created_at: datetime


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    projection_id: int
    prop_line_id: int
    player_name: str
    sportsbook_name: str
    market: Market
    side: Side
    line: float | None
    american_odds: int
    rating: Rating
    model_probability: float
    implied_probability: float
    fair_market_probability: float | None
    expected_return: float
    data_age_seconds: int
    rejection_reasons: list[str]
    recommended_stake: float
    rationale: str
    created_at: datetime


class ProjectionResult(BaseModel):
    projection: ProjectionResponse
    recommendation: RecommendationResponse


class PaperBetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class SettlementOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"


class PaperBetCreate(BaseModel):
    recommendation_id: int
    stake: Decimal | None = Field(default=None, gt=0)


class ClosingLineCreate(BaseModel):
    closing_line: float | None = None
    closing_odds: int
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SettlementCreate(BaseModel):
    outcome: SettlementOutcome
    result_value: float | None = None
    settled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClosingLineResponse(BaseModel):
    closing_line: float | None
    closing_odds: int
    captured_at: datetime
    line_movement: float | None
    price_movement: float
    beat_closing_line: bool
    clv_percentage: float | None


class SettlementResponse(BaseModel):
    outcome: SettlementOutcome
    result_value: float | None
    net_profit: Decimal
    settled_at: datetime


class PaperBetResponse(BaseModel):
    id: int
    recommendation_id: int
    prop_line_id: int
    player_name: str
    event_name: str
    sportsbook_name: str
    market: Market
    side: Side
    opening_line: float | None
    opening_odds: int
    bet_line: float | None
    bet_odds: int
    stake: Decimal
    expected_value: float
    recommendation_rating: Rating
    status: PaperBetStatus
    correlation_flags: list[str]
    placed_at: datetime
    closing: ClosingLineResponse | None = None
    settlement: SettlementResponse | None = None


class PerformanceSlice(BaseModel):
    bets: int
    amount_risked: Decimal
    net_profit: Decimal
    roi: float


class PerformanceResponse(BaseModel):
    total_bets: int
    wins: int
    losses: int
    pushes: int
    amount_risked: Decimal
    net_profit: Decimal
    roi: float
    average_expected_value_at_entry: float | None
    average_clv: float | None
    clv_hit_rate: float | None
    by_market: dict[str, PerformanceSlice]
    by_sportsbook: dict[str, PerformanceSlice]
    by_recommendation_rating: dict[str, PerformanceSlice]
    maximum_drawdown: Decimal


class WRReceptionsProjectionCreate(BaseModel):
    projected_team_pass_attempts: float = Field(ge=0)
    route_participation: float = Field(ge=0, le=1)
    targets_per_route_run: float = Field(ge=0, le=1)
    catch_probability: float = Field(ge=0, le=1)
    line: float = Field(ge=0)
    contextual_multipliers: dict[str, float] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WRReceptionsProjectionResponse(BaseModel):
    model_label: str
    projected_targets: float
    projected_receptions: float
    floor: int
    median: int
    ceiling: int
    over_probability: float
    under_probability: float
    push_probability: float
    assumptions_used: dict[str, float]
    captured_at: datetime


class QualityFlagResponse(BaseModel):
    category: str
    message: str
    record_index: int | None


class IngestionRunRequest(BaseModel):
    provider: str | None = None


class IngestionRunResponse(BaseModel):
    job_id: int
    correlation_id: str
    provider: str
    status: str
    row_count: int
    duplicate_suppressed: bool
    quality_flags: list[QualityFlagResponse]


class IngestionJobResponse(BaseModel):
    id: int
    correlation_id: str
    provider: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    row_count: int
    attempt_count: int
    error_category: str | None
    error_message: str | None


class ProviderHealthResponse(BaseModel):
    provider: str
    status: str
    last_successful_fetch: datetime | None
    last_failed_fetch: datetime | None
    consecutive_failures: int
    average_latency_ms: float
    successful_fetches: int
    records_returned: int
    updated_at: datetime


class OddsHistoryResponse(PropResponse):
    provider_key: str | None
    raw_player_name: str | None
    snapshot_batch_id: int | None


class MovementPointResponse(BaseModel):
    captured_at: datetime
    line: float | None
    american_odds: int
    direction: str


class ConsensusResponse(BaseModel):
    median_line: float
    median_implied_probability: float
    books_contributing: int


class OddsMovementResponse(BaseModel):
    event_id: int
    player_id: int
    player_name: str
    market: Market
    side: Side
    sportsbook_name: str
    first_observed_line: float | None
    first_observed_odds: int
    latest_line: float | None
    latest_odds: int
    minimum_line: float | None
    maximum_line: float | None
    minimum_price: int
    maximum_price: int
    movements: list[MovementPointResponse]
    sportsbook_moved_first: str | None
    consensus: ConsensusResponse | None
