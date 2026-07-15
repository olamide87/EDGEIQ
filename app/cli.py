import argparse
import asyncio

from app.line_shopper import rank_offers
from app.models import Market, Side
from app.providers.mock import MockOddsProvider
from app.providers.theoddsapi import TheOddsAPIProvider
from app.storage import append_snapshot


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--provider", choices=["mock", "theoddsapi"], default="mock")
    args = parser.parse_args()
    asyncio.run(run("mock" if args.demo else args.provider))
