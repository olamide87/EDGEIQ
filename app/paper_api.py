from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.db_models import (
    ClosingLineSnapshot,
    PaperBet,
    Projection,
    PropLine,
    Recommendation,
    Settlement,
)
from app.schemas import (
    ClosingLineCreate,
    ClosingLineResponse,
    PaperBetCreate,
    PaperBetResponse,
    PaperBetStatus,
    PerformanceResponse,
    PerformanceSlice,
    SettlementCreate,
    SettlementResponse,
)
from app.services.clv import calculate_clv
from app.services.bankroll import BankrollRules

router = APIRouter()
UNSETTLED_STATUSES = (PaperBetStatus.ACTIVE.value, PaperBetStatus.CLOSED.value)


def _paper_bet_statement() -> Select[tuple[PaperBet]]:
    return select(PaperBet).options(
        joinedload(PaperBet.player),
        joinedload(PaperBet.event),
        joinedload(PaperBet.sportsbook),
        joinedload(PaperBet.closing_snapshot),
        joinedload(PaperBet.settlement),
    )


def _paper_bet_response(bet: PaperBet) -> PaperBetResponse:
    closing = bet.closing_snapshot
    settlement = bet.settlement
    return PaperBetResponse(
        id=bet.id,
        recommendation_id=bet.recommendation_id,
        prop_line_id=bet.prop_line_id,
        player_name=bet.player.name,
        event_name=bet.event.name,
        sportsbook_name=bet.sportsbook.name,
        market=bet.market,
        side=bet.side,
        opening_line=float(bet.opening_line) if bet.opening_line is not None else None,
        opening_odds=bet.opening_odds,
        bet_line=float(bet.bet_line) if bet.bet_line is not None else None,
        bet_odds=bet.bet_odds,
        stake=bet.stake,
        expected_value=float(bet.expected_value),
        recommendation_rating=bet.recommendation_rating,
        status=bet.status,
        correlation_flags=json.loads(bet.correlation_flags),
        placed_at=bet.placed_at,
        closing=(
            ClosingLineResponse(
                closing_line=(float(closing.closing_line) if closing.closing_line is not None else None),
                closing_odds=closing.closing_odds,
                captured_at=closing.captured_at,
                line_movement=(float(closing.line_movement) if closing.line_movement is not None else None),
                price_movement=float(closing.price_movement),
                beat_closing_line=closing.beat_closing_line,
                clv_percentage=(float(closing.clv_percentage) if closing.clv_percentage is not None else None),
            ) if closing else None
        ),
        settlement=(
            SettlementResponse(
                outcome=settlement.outcome,
                result_value=(float(settlement.result_value) if settlement.result_value is not None else None),
                net_profit=settlement.net_profit,
                settled_at=settlement.settled_at,
            ) if settlement else None
        ),
    )


def _decimal_odds(american_odds: int) -> Decimal:
    odds = Decimal(american_odds)
    return Decimal(1) + (odds / Decimal(100) if odds > 0 else Decimal(100) / abs(odds))


@router.post("/paper-bets", response_model=PaperBetResponse, status_code=status.HTTP_201_CREATED)
def create_paper_bet(payload: PaperBetCreate, db: Session = Depends(get_db)) -> PaperBetResponse:
    recommendation = db.scalar(
        select(Recommendation).options(
            joinedload(Recommendation.projection)
            .joinedload(Projection.prop_line)
            .joinedload(PropLine.player),
            joinedload(Recommendation.projection)
            .joinedload(Projection.prop_line)
            .joinedload(PropLine.event),
            joinedload(Recommendation.projection)
            .joinedload(Projection.prop_line)
            .joinedload(PropLine.sportsbook),
        ).where(Recommendation.id == payload.recommendation_id)
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    prop = recommendation.projection.prop_line
    duplicate = db.scalar(
        select(PaperBet.id).where(
            PaperBet.player_id == prop.player_id,
            PaperBet.event_id == prop.event_id,
            PaperBet.market == prop.market,
            PaperBet.side == prop.side,
            PaperBet.status.in_(UNSETTLED_STATUSES),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Duplicate active paper bet rejected.")

    stake = payload.stake if payload.stake is not None else Decimal(str(settings.default_unit))
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weekly = Decimal(str(db.scalar(select(func.coalesce(func.sum(PaperBet.stake), 0)).where(
        PaperBet.placed_at >= week_start
    )) or 0))
    player_exposure = Decimal(str(db.scalar(select(func.coalesce(func.sum(PaperBet.stake), 0)).where(
        PaperBet.player_id == prop.player_id, PaperBet.status.in_(UNSETTLED_STATUSES)
    )) or 0))
    event_exposure = Decimal(str(db.scalar(select(func.coalesce(func.sum(PaperBet.stake), 0)).where(
        PaperBet.event_id == prop.event_id, PaperBet.status.in_(UNSETTLED_STATUSES)
    )) or 0))
    exposure_rejections = BankrollRules(
        paper_bankroll=settings.paper_bankroll,
        default_unit=settings.default_unit,
        max_single_recommendation=settings.max_single_recommendation,
        max_weekly_exposure=settings.max_weekly_exposure,
        max_player_exposure=settings.max_player_exposure,
        max_event_exposure=settings.max_event_exposure,
    ).exposure_rejections(
        stake=float(stake), weekly_exposure=float(weekly),
        player_exposure=float(player_exposure), event_exposure=float(event_exposure),
    )
    if exposure_rejections:
        raise HTTPException(status_code=409, detail=exposure_rejections)

    active = db.scalars(select(PaperBet).where(PaperBet.status.in_(UNSETTLED_STATUSES))).all()
    flags: list[str] = []
    if any(item.player_id == prop.player_id for item in active):
        flags.append("CORRELATED_SAME_PLAYER")
    if any(item.event_id == prop.event_id for item in active):
        flags.append("CORRELATED_SAME_EVENT")

    opening = db.scalar(
        select(PropLine).where(
            PropLine.player_id == prop.player_id,
            PropLine.event_id == prop.event_id,
            PropLine.sportsbook_id == prop.sportsbook_id,
            PropLine.market == prop.market,
            PropLine.side == prop.side,
        ).order_by(PropLine.captured_at.asc(), PropLine.id.asc()).limit(1)
    ) or prop
    paper_bet = PaperBet(
        recommendation_id=recommendation.id,
        prop_line_id=prop.id,
        player_id=prop.player_id,
        event_id=prop.event_id,
        sportsbook_id=prop.sportsbook_id,
        market=prop.market,
        side=prop.side,
        opening_line=opening.line,
        opening_odds=opening.american_odds,
        bet_line=prop.line,
        bet_odds=prop.american_odds,
        stake=stake,
        expected_value=recommendation.expected_return,
        recommendation_rating=recommendation.rating,
        correlation_flags=json.dumps(flags),
    )
    db.add(paper_bet)
    db.commit()
    return _paper_bet_response(db.scalar(_paper_bet_statement().where(PaperBet.id == paper_bet.id)))


@router.get("/paper-bets", response_model=list[PaperBetResponse])
def list_paper_bets(
    bet_status: PaperBetStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[PaperBetResponse]:
    statement = _paper_bet_statement()
    if bet_status:
        statement = statement.where(PaperBet.status == bet_status.value)
    statement = statement.order_by(PaperBet.placed_at.desc()).limit(limit)
    return [_paper_bet_response(bet) for bet in db.scalars(statement).all()]


@router.post("/paper-bets/{paper_bet_id}/close", response_model=PaperBetResponse)
def close_paper_bet(
    paper_bet_id: int, payload: ClosingLineCreate, db: Session = Depends(get_db)
) -> PaperBetResponse:
    bet = db.scalar(_paper_bet_statement().where(PaperBet.id == paper_bet_id))
    if bet is None:
        raise HTTPException(status_code=404, detail="Paper bet not found.")
    if bet.closing_snapshot is not None:
        raise HTTPException(status_code=409, detail="Closing line already recorded.")
    result = calculate_clv(
        side=bet.side,
        bet_line=float(bet.bet_line) if bet.bet_line is not None else None,
        bet_odds=bet.bet_odds,
        closing_line=payload.closing_line,
        closing_odds=payload.closing_odds,
    )
    db.add(ClosingLineSnapshot(
        paper_bet_id=bet.id,
        closing_line=(Decimal(str(payload.closing_line)) if payload.closing_line is not None else None),
        closing_odds=payload.closing_odds,
        captured_at=payload.captured_at,
        line_movement=(Decimal(str(result.line_movement)) if result.line_movement is not None else None),
        price_movement=Decimal(str(result.price_movement)),
        beat_closing_line=result.beat_closing_line,
        clv_percentage=(Decimal(str(result.clv_percentage)) if result.clv_percentage is not None else None),
    ))
    bet.status = PaperBetStatus.CLOSED.value
    db.commit()
    db.expire_all()
    return _paper_bet_response(db.scalar(_paper_bet_statement().where(PaperBet.id == bet.id)))


@router.post("/paper-bets/{paper_bet_id}/settle", response_model=PaperBetResponse)
def settle_paper_bet(
    paper_bet_id: int, payload: SettlementCreate, db: Session = Depends(get_db)
) -> PaperBetResponse:
    bet = db.scalar(_paper_bet_statement().where(PaperBet.id == paper_bet_id))
    if bet is None:
        raise HTTPException(status_code=404, detail="Paper bet not found.")
    if bet.settlement is not None:
        raise HTTPException(status_code=409, detail="Paper bet already settled.")
    if payload.outcome.value == "WIN":
        profit = bet.stake * (_decimal_odds(bet.bet_odds) - Decimal(1))
    elif payload.outcome.value == "LOSS":
        profit = -bet.stake
    else:
        profit = Decimal(0)
    db.add(Settlement(
        paper_bet_id=bet.id,
        outcome=payload.outcome.value,
        result_value=(Decimal(str(payload.result_value)) if payload.result_value is not None else None),
        net_profit=profit.quantize(Decimal("0.01")),
        settled_at=payload.settled_at,
    ))
    bet.status = PaperBetStatus.SETTLED.value
    db.commit()
    db.expire_all()
    return _paper_bet_response(db.scalar(_paper_bet_statement().where(PaperBet.id == bet.id)))


def _performance_slice(bets: list[PaperBet]) -> PerformanceSlice:
    settled = [bet for bet in bets if bet.settlement is not None]
    risked = sum((bet.stake for bet in settled), Decimal(0))
    profit = sum((bet.settlement.net_profit for bet in settled), Decimal(0))
    return PerformanceSlice(
        bets=len(bets), amount_risked=risked, net_profit=profit,
        roi=float(profit / risked) if risked else 0.0,
    )


@router.get("/performance", response_model=PerformanceResponse)
def performance(db: Session = Depends(get_db)) -> PerformanceResponse:
    bets = list(db.scalars(_paper_bet_statement().order_by(PaperBet.placed_at)).all())
    settled = [bet for bet in bets if bet.settlement is not None]
    risked = sum((bet.stake for bet in settled), Decimal(0))
    profit = sum((bet.settlement.net_profit for bet in settled), Decimal(0))
    clv_values = [float(bet.closing_snapshot.clv_percentage) for bet in bets
                  if bet.closing_snapshot and bet.closing_snapshot.clv_percentage is not None]
    closed = [bet for bet in bets if bet.closing_snapshot is not None]
    cumulative = Decimal(0)
    peak = Decimal(0)
    max_drawdown = Decimal(0)
    for bet in sorted(settled, key=lambda item: item.settlement.settled_at):
        cumulative += bet.settlement.net_profit
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    def grouped(key: Callable[[PaperBet], str]) -> dict[str, PerformanceSlice]:
        groups: dict[str, list[PaperBet]] = {}
        for bet in bets:
            groups.setdefault(str(key(bet)), []).append(bet)
        return {name: _performance_slice(items) for name, items in groups.items()}

    return PerformanceResponse(
        total_bets=len(bets),
        wins=sum(bet.settlement.outcome == "WIN" for bet in settled),
        losses=sum(bet.settlement.outcome == "LOSS" for bet in settled),
        pushes=sum(bet.settlement.outcome == "PUSH" for bet in settled),
        amount_risked=risked,
        net_profit=profit,
        roi=float(profit / risked) if risked else 0.0,
        average_expected_value_at_entry=(
            sum(float(bet.expected_value) for bet in bets) / len(bets) if bets else None
        ),
        average_clv=(sum(clv_values) / len(clv_values) if clv_values else None),
        clv_hit_rate=(
            sum(bet.closing_snapshot.beat_closing_line for bet in closed) / len(closed)
            if closed else None
        ),
        by_market=grouped(lambda bet: bet.market),
        by_sportsbook=grouped(lambda bet: bet.sportsbook.name),
        by_recommendation_rating=grouped(lambda bet: bet.recommendation_rating),
        maximum_drawdown=max_drawdown,
    )
