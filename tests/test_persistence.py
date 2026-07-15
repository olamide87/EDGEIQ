import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import Event, Player, PropLine, Sportsbook
from app.persistence import persist_offers
from app.providers.mock import MockOddsProvider
from app.models import Market, Offer, Side


def test_normalized_provider_offers_can_be_persisted(db_session: Session):
    offers = asyncio.run(MockOddsProvider().fetch_nfl_player_props())
    rows = persist_offers(db_session, offers)

    assert len(rows) == 4
    assert db_session.scalar(select(func.count(Player.id))) == 1
    assert db_session.scalar(select(func.count(Event.id))) == 1
    assert db_session.scalar(select(func.count(Sportsbook.id))) == 4
    assert db_session.scalar(select(func.count(PropLine.id))) == 4


def test_persistence_stores_fair_probability_only_for_opposing_pair(db_session: Session):
    common = dict(
        event_id="paired", event_name="DET at CHI", bookmaker="Book",
        market=Market.PLAYER_RECEPTIONS, player="Receiver", line=5.5,
        captured_at=datetime.now(timezone.utc),
    )
    rows = persist_offers(db_session, [
        Offer(**common, side=Side.OVER, american_odds=-110),
        Offer(**common, side=Side.UNDER, american_odds=-110),
    ])
    assert [float(row.fair_market_probability) for row in rows] == [0.5, 0.5]
