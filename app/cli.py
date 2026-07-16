import argparse
import asyncio
import json

from sqlalchemy import select

from app.line_shopper import rank_offers
from app.models import Market, Side
from app.providers.mock import MockOddsProvider
from app.providers.theoddsapi import TheOddsAPIProvider
from app.storage import append_snapshot
from app.database import SessionLocal
from app.db_models import ProviderHealth
from app.services.ingestion import IngestionService


async def run(provider_name: str) -> None:
    provider = MockOddsProvider() if provider_name == "mock" else TheOddsAPIProvider()
    offers = await provider.fetch_nfl_player_props()
    append_snapshot(offers)

    # Demo query; the next version will expose filters through FastAPI/UI.
    player = "Amon-Ra St. Brown"
    board = rank_offers(
        offers,
        player=player,
        market=Market.PLAYER_RECEPTIONS,
        side=Side.OVER,
    )

    if not board.offers:
        print("No matching offers found.")
        return

    print(f"\nBest available lines: {board.player} — {board.market.value} {board.side.value}\n")
    for ranked in board.offers:
        o = ranked.offer
        line_text = "" if o.line is None else f"{o.line:g}"
        print(
            f"{ranked.rank}. {o.bookmaker:15} "
            f"{o.side.value.upper()} {line_text:>5} "
            f"{o.american_odds:+d} "
            f"(implied {ranked.implied_probability:.1%})"
        )


async def ingest_once(provider_name: str) -> None:
    result = await IngestionService().run_provider(provider_name)
    print(json.dumps({
        "job_id": result.job_id,
        "correlation_id": result.correlation_id,
        "provider": result.provider,
        "status": result.status,
        "row_count": result.row_count,
        "duplicate_suppressed": result.duplicate_suppressed,
    }))


def show_provider_health() -> None:
    with SessionLocal() as session:
        rows = session.scalars(select(ProviderHealth).order_by(ProviderHealth.provider)).all()
        print(json.dumps([{
            "provider": row.provider,
            "status": row.status,
            "consecutive_failures": row.consecutive_failures,
            "average_latency_ms": float(row.average_latency_ms),
            "records_returned": row.records_returned,
        } for row in rows]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["ingest-once", "provider-health"])
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--provider", choices=["mock", "theoddsapi"], default="mock")
    args = parser.parse_args()
    if args.command == "ingest-once":
        asyncio.run(ingest_once(args.provider))
    elif args.command == "provider-health":
        show_provider_health()
    else:
        asyncio.run(run("mock" if args.demo else args.provider))
