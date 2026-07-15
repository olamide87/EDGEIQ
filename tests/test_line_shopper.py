import asyncio
from app.line_shopper import rank_offers
from app.models import Market, Side
from app.providers.mock import MockOddsProvider


def test_best_over_prefers_lower_line_then_better_price():
    offers = asyncio.run(MockOddsProvider().fetch_nfl_player_props())
    board = rank_offers(
        offers,
        player="Amon-Ra St. Brown",
        market=Market.PLAYER_RECEPTIONS,
        side=Side.OVER,
    )
    assert board.offers[0].offer.bookmaker == "DraftKings"
    assert board.offers[0].offer.line == 6.5
    assert board.offers[-1].offer.line == 7.5
