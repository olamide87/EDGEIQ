from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.db_models import IngestionJob, PropLine, ProviderHealth
from app.schemas import (
    ConsensusResponse,
    IngestionJobResponse,
    IngestionRunRequest,
    IngestionRunResponse,
    MovementPointResponse,
    OddsHistoryResponse,
    OddsMovementResponse,
    ProviderHealthResponse,
)
from app.services.ingestion import IngestionService
from app.services.odds_movement import market_consensus, movement_direction

router = APIRouter()


def get_ingestion_service() -> IngestionService:
    return IngestionService()


@router.post("/ingestion/run", response_model=list[IngestionRunResponse])
async def run_ingestion(
    payload: IngestionRunRequest,
    service: IngestionService = Depends(get_ingestion_service),
) -> list[IngestionRunResponse]:
    providers = [payload.provider] if payload.provider else settings.enabled_provider_keys
    if not providers:
        raise HTTPException(status_code=400, detail="No providers are enabled.")
    results = []
    for provider in providers:
        try:
            result = await service.run_provider(provider)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        results.append(IngestionRunResponse(**asdict(result)))
    return results


@router.get("/ingestion/jobs", response_model=list[IngestionJobResponse])
def ingestion_jobs(
    provider: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[IngestionJobResponse]:
    statement = select(IngestionJob)
    if provider:
        statement = statement.where(IngestionJob.provider == provider)
    statement = statement.order_by(IngestionJob.started_at.desc()).limit(limit)
    return [IngestionJobResponse.model_validate(row, from_attributes=True)
            for row in db.scalars(statement).all()]


@router.get("/providers/health", response_model=list[ProviderHealthResponse])
def providers_health(db: Session = Depends(get_db)) -> list[ProviderHealthResponse]:
    rows = db.scalars(select(ProviderHealth).order_by(ProviderHealth.provider)).all()
    return [ProviderHealthResponse.model_validate(row, from_attributes=True) for row in rows]


@router.get("/odds/history", response_model=list[OddsHistoryResponse])
def odds_history(
    player: str | None = None,
    market: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[OddsHistoryResponse]:
    from app.api import _prop_response

    statement = select(PropLine).options(
        joinedload(PropLine.event), joinedload(PropLine.player), joinedload(PropLine.sportsbook)
    )
    if player:
        statement = statement.where(PropLine.player.has(name=player))
    if market:
        statement = statement.where(PropLine.market == market)
    statement = statement.order_by(PropLine.captured_at.desc()).limit(limit)
    responses = []
    for row in db.scalars(statement).all():
        base = _prop_response(row).model_dump()
        responses.append(OddsHistoryResponse(
            **base,
            provider_key=row.provider_key,
            raw_player_name=row.raw_player_name,
            snapshot_batch_id=row.snapshot_batch_id,
        ))
    return responses


@router.get("/odds/movements", response_model=list[OddsMovementResponse])
def odds_movements(db: Session = Depends(get_db)) -> list[OddsMovementResponse]:
    rows = list(db.scalars(
        select(PropLine).options(joinedload(PropLine.player), joinedload(PropLine.sportsbook))
        .order_by(PropLine.captured_at, PropLine.id)
    ).all())
    markets: dict[tuple[int, int, str, str], list[PropLine]] = {}
    for row in rows:
        markets.setdefault((row.event_id, row.player_id, row.market, row.side), []).append(row)

    output: list[OddsMovementResponse] = []
    for market_key, market_rows in markets.items():
        by_book: dict[int, list[PropLine]] = {}
        for row in market_rows:
            by_book.setdefault(row.sportsbook_id, []).append(row)
        first_moves: list[tuple[datetime, str]] = []
        for series in by_book.values():
            for previous, current in zip(series, series[1:]):
                if movement_direction(previous, current) != "UNCHANGED":
                    first_moves.append((current.captured_at, current.sportsbook.name))
                    break
        moved_first = min(first_moves, key=lambda item: item[0])[1] if first_moves else None
        latest_by_book = [series[-1] for series in by_book.values()]
        consensus = market_consensus(latest_by_book)

        for series in by_book.values():
            first, latest = series[0], series[-1]
            points = [MovementPointResponse(
                captured_at=first.captured_at,
                line=float(first.line) if first.line is not None else None,
                american_odds=first.american_odds,
                direction="INITIAL",
            )]
            for previous, current in zip(series, series[1:]):
                direction = movement_direction(previous, current)
                if direction != "UNCHANGED":
                    points.append(MovementPointResponse(
                        captured_at=current.captured_at,
                        line=float(current.line) if current.line is not None else None,
                        american_odds=current.american_odds,
                        direction=direction,
                    ))
            lines = [float(row.line) for row in series if row.line is not None]
            output.append(OddsMovementResponse(
                event_id=market_key[0], player_id=market_key[1], player_name=first.player.name,
                market=market_key[2], side=market_key[3], sportsbook_name=first.sportsbook.name,
                first_observed_line=float(first.line) if first.line is not None else None,
                first_observed_odds=first.american_odds,
                latest_line=float(latest.line) if latest.line is not None else None,
                latest_odds=latest.american_odds,
                minimum_line=min(lines) if lines else None,
                maximum_line=max(lines) if lines else None,
                minimum_price=min(row.american_odds for row in series),
                maximum_price=max(row.american_odds for row in series),
                movements=points,
                sportsbook_moved_first=moved_first,
                consensus=(ConsensusResponse(**asdict(consensus)) if consensus else None),
            ))
    return output
