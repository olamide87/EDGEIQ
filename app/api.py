from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.db_models import Projection, PropLine, Recommendation
from app.models import Market, Side
from app.odds_math import american_to_decimal
from app.odds_math import implied_probability
from app.schemas import (
    HealthResponse,
    ProjectionCreate,
    ProjectionResponse,
    ProjectionResult,
    PropResponse,
    RecommendationResponse,
    ConfidenceResponse,
    WRReceptionsProjectionCreate,
    WRReceptionsProjectionResponse,
)
from app.services.best_line import select_best_line
from app.services.bankroll import BankrollRules
from app.services.confidence import ConfidenceComponents, ConfidenceWeights, calculate_overall_confidence
from app.services.expected_value import ExpectedValueService, Rating
from app.services.recommendation_policy import RecommendationPolicy
from app.services.wr_receptions import project_wr_receptions

router = APIRouter()


def _load_prop_lines(_: Session) -> Select[tuple[PropLine]]:
    return select(PropLine).options(
        joinedload(PropLine.event),
        joinedload(PropLine.player),
        joinedload(PropLine.sportsbook),
    )


def _prop_response(prop: PropLine, selection_reason: str | None = None) -> PropResponse:
    return PropResponse(
        id=prop.id,
        event_id=prop.event_id,
        event_name=prop.event.name,
        player_id=prop.player_id,
        player_name=prop.player.name,
        sportsbook_id=prop.sportsbook_id,
        sportsbook_name=prop.sportsbook.name,
        market=prop.market,
        side=prop.side,
        line=float(prop.line) if prop.line is not None else None,
        american_odds=prop.american_odds,
        raw_implied_probability=implied_probability(prop.american_odds),
        fair_market_probability=(
            float(prop.fair_market_probability) if prop.fair_market_probability is not None else None
        ),
        vig_removed=prop.fair_market_probability is not None,
        selection_reason=selection_reason,
        captured_at=prop.captured_at,
    )


def _projection_response(projection: Projection) -> ProjectionResponse:
    return ProjectionResponse(
        id=projection.id,
        prop_line_id=projection.prop_line_id,
        model_probability=float(projection.model_probability),
        projected_value=(float(projection.projected_value) if projection.projected_value is not None else None),
        model_name=projection.model_name,
        model_input_captured_at=projection.model_input_captured_at,
        confidence=ConfidenceResponse(
            data_quality=float(projection.confidence_data_quality),
            sample_size=float(projection.confidence_sample_size),
            role_stability=float(projection.confidence_role_stability),
            injury_certainty=float(projection.confidence_injury_certainty),
            matchup_certainty=float(projection.confidence_matchup_certainty),
            market_stability=float(projection.confidence_market_stability),
            overall_confidence=float(projection.overall_confidence),
        ),
        created_at=projection.created_at,
    )


def _recommendation_response(recommendation: Recommendation) -> RecommendationResponse:
    projection = recommendation.projection
    prop = projection.prop_line
    return RecommendationResponse(
        id=recommendation.id,
        projection_id=projection.id,
        prop_line_id=prop.id,
        player_name=prop.player.name,
        sportsbook_name=prop.sportsbook.name,
        market=prop.market,
        side=prop.side,
        line=float(prop.line) if prop.line is not None else None,
        american_odds=prop.american_odds,
        rating=recommendation.rating,
        model_probability=float(projection.model_probability),
        implied_probability=float(recommendation.implied_probability),
        fair_market_probability=(
            float(recommendation.fair_market_probability)
            if recommendation.fair_market_probability is not None else None
        ),
        expected_return=float(recommendation.expected_return),
        data_age_seconds=recommendation.data_age_seconds,
        rejection_reasons=json.loads(recommendation.rejection_reasons),
        recommended_stake=float(recommendation.recommended_stake),
        rationale=recommendation.rationale,
        created_at=recommendation.created_at,
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.3.0")


@router.get("/props", response_model=list[PropResponse])
def list_props(
    player: str | None = None,
    market: Market | None = None,
    side: Side | None = None,
    sportsbook: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[PropResponse]:
    statement = _load_prop_lines(db)
    if player:
        statement = statement.where(PropLine.player.has(name=player))
    if market:
        statement = statement.where(PropLine.market == market.value)
    if side:
        statement = statement.where(PropLine.side == side.value)
    if sportsbook:
        statement = statement.where(PropLine.sportsbook.has(name=sportsbook))
    statement = statement.order_by(PropLine.captured_at.desc(), PropLine.id.desc()).limit(limit)
    return [_prop_response(prop) for prop in db.scalars(statement).all()]


@router.get("/props/best", response_model=list[PropResponse])
def best_props(
    player: str | None = None,
    market: Market | None = None,
    side: Side | None = None,
    db: Session = Depends(get_db),
) -> list[PropResponse]:
    statement = _load_prop_lines(db)
    if player:
        statement = statement.where(PropLine.player.has(name=player))
    if market:
        statement = statement.where(PropLine.market == market.value)
    if side:
        statement = statement.where(PropLine.side == side.value)

    groups: dict[tuple[int, int, str, str], list[PropLine]] = {}
    for prop in db.scalars(statement).all():
        key = (prop.event_id, prop.player_id, prop.market, prop.side)
        groups.setdefault(key, []).append(prop)
    selected = [select_best_line(group) for group in groups.values()]
    return [
        _prop_response(prop, reason)
        for prop, reason in sorted(selected, key=lambda item: item[0].id)
    ]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.post(
    "/projections",
    response_model=ProjectionResult,
    status_code=status.HTTP_201_CREATED,
)
def create_projection(payload: ProjectionCreate, db: Session = Depends(get_db)) -> ProjectionResult:
    requested_prop = db.scalar(_load_prop_lines(db).where(PropLine.id == payload.prop_line_id))
    if requested_prop is None:
        raise HTTPException(status_code=404, detail="Prop line not found.")
    candidates = db.scalars(
        _load_prop_lines(db).where(
            PropLine.event_id == requested_prop.event_id,
            PropLine.player_id == requested_prop.player_id,
            PropLine.market == requested_prop.market,
            PropLine.side == requested_prop.side,
        )
    ).all()
    prop, _ = select_best_line(list(candidates))

    evaluator = ExpectedValueService(
        watch_threshold=settings.watch_ev_threshold,
        bet_threshold=settings.bet_ev_threshold,
    )
    result = evaluator.evaluate(payload.model_probability, prop.american_odds)
    confidence_components = ConfidenceComponents(**payload.confidence.model_dump())
    confidence_weights = ConfidenceWeights(
        data_quality=settings.confidence_data_quality_weight,
        sample_size=settings.confidence_sample_size_weight,
        role_stability=settings.confidence_role_stability_weight,
        injury_certainty=settings.confidence_injury_certainty_weight,
        matchup_certainty=settings.confidence_matchup_certainty_weight,
        market_stability=settings.confidence_market_stability_weight,
    )
    overall_confidence = calculate_overall_confidence(confidence_components, confidence_weights)
    now = datetime.now(timezone.utc)
    data_age_seconds = max(
        0,
        int((now - min(_as_utc(prop.captured_at), _as_utc(payload.captured_at))).total_seconds()),
    )
    decision = RecommendationPolicy(
        min_watch_ev=settings.watch_ev_threshold,
        min_bet_ev=settings.bet_ev_threshold,
        min_watch_confidence=settings.min_watch_confidence,
        min_bet_confidence=settings.min_bet_confidence,
        fresh_data_seconds=settings.fresh_data_seconds,
        stale_data_seconds=settings.stale_data_seconds,
    ).decide(
        expected_return=result.expected_return,
        confidence=overall_confidence,
        data_age_seconds=data_age_seconds,
    )

    week_start = datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    exposure = db.scalar(
        select(func.coalesce(func.sum(Recommendation.recommended_stake), 0)).where(
            Recommendation.created_at >= week_start
        )
    )
    rules = BankrollRules(
        paper_bankroll=settings.paper_bankroll,
        default_unit=settings.default_unit,
        max_single_recommendation=settings.max_single_recommendation,
        max_weekly_exposure=settings.max_weekly_exposure,
    )
    stake = rules.stake_for(decision.rating, current_weekly_exposure=float(exposure or 0))

    projection = Projection(
        prop_line_id=prop.id,
        model_probability=Decimal(str(payload.model_probability)),
        projected_value=(Decimal(str(payload.projected_value)) if payload.projected_value is not None else None),
        model_name=payload.model_name,
        model_input_captured_at=payload.captured_at,
        confidence_data_quality=Decimal(str(confidence_components.data_quality)),
        confidence_sample_size=Decimal(str(confidence_components.sample_size)),
        confidence_role_stability=Decimal(str(confidence_components.role_stability)),
        confidence_injury_certainty=Decimal(str(confidence_components.injury_certainty)),
        confidence_matchup_certainty=Decimal(str(confidence_components.matchup_certainty)),
        confidence_market_stability=Decimal(str(confidence_components.market_stability)),
        overall_confidence=Decimal(str(overall_confidence)),
    )
    db.add(projection)
    db.flush()
    recommendation = Recommendation(
        projection_id=projection.id,
        rating=decision.rating.value,
        implied_probability=Decimal(str(result.implied_probability)),
        fair_market_probability=prop.fair_market_probability,
        expected_return=Decimal(str(result.expected_return)),
        data_age_seconds=data_age_seconds,
        rejection_reasons=json.dumps(decision.rejection_reasons),
        recommended_stake=Decimal(str(stake)),
        rationale=(
            f"{decision.rating.value}: model probability {result.model_probability:.1%}, "
            f"market implied probability {result.implied_probability:.1%}, "
            f"expected return {result.expected_return:.2%} per dollar. Paper recommendation only."
        ),
    )
    db.add(recommendation)
    db.commit()
    db.refresh(projection)
    db.refresh(recommendation)
    return ProjectionResult(
        projection=_projection_response(projection),
        recommendation=_recommendation_response(recommendation),
    )


@router.post("/projections/wr-receptions", response_model=WRReceptionsProjectionResponse)
def create_wr_receptions_projection(
    payload: WRReceptionsProjectionCreate,
) -> WRReceptionsProjectionResponse:
    result = project_wr_receptions(
        projected_team_pass_attempts=payload.projected_team_pass_attempts,
        route_participation=payload.route_participation,
        targets_per_route_run=payload.targets_per_route_run,
        catch_probability=payload.catch_probability,
        line=payload.line,
        contextual_multipliers=payload.contextual_multipliers,
    )
    return WRReceptionsProjectionResponse(**result.__dict__, captured_at=payload.captured_at)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def list_recommendations(
    rating: Rating | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[RecommendationResponse]:
    statement = select(Recommendation).options(
        joinedload(Recommendation.projection)
        .joinedload(Projection.prop_line)
        .joinedload(PropLine.player),
        joinedload(Recommendation.projection)
        .joinedload(Projection.prop_line)
        .joinedload(PropLine.sportsbook),
    )
    if rating:
        statement = statement.where(Recommendation.rating == rating.value)
    statement = statement.order_by(Recommendation.created_at.desc()).limit(limit)
    return [_recommendation_response(item) for item in db.scalars(statement).all()]
