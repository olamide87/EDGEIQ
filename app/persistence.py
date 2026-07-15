from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import Event, Player, PropLine, Sportsbook
from app.models import Offer
from app.services.market_normalization import normalize_two_way_market


def persist_offers(session: Session, offers: list[Offer]) -> list[PropLine]:
    """Persist normalized provider offers without coupling providers to SQLAlchemy."""
    rows: list[PropLine] = []
    for offer in offers:
        player = session.scalar(select(Player).where(Player.name == offer.player))
        if player is None:
            player = Player(name=offer.player)
            session.add(player)

        book_key = offer.bookmaker.casefold().replace(" ", "-")
        sportsbook = session.scalar(select(Sportsbook).where(Sportsbook.key == book_key))
        if sportsbook is None:
            sportsbook = Sportsbook(name=offer.bookmaker, key=book_key)
            session.add(sportsbook)

        event = session.scalar(select(Event).where(Event.external_id == offer.event_id))
        if event is None:
            event = Event(
                external_id=offer.event_id,
                name=offer.event_name,
                commence_time=offer.commence_time,
            )
            session.add(event)

        session.flush()
        row = PropLine(
            event_id=event.id,
            player_id=player.id,
            sportsbook_id=sportsbook.id,
            market=offer.market.value,
            side=offer.side.value,
            line=offer.line,
            american_odds=offer.american_odds,
            captured_at=offer.captured_at,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    groups: dict[tuple[int, int, int, str, object], list[PropLine]] = {}
    for row in rows:
        key = (row.event_id, row.player_id, row.sportsbook_id, row.market, row.line)
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        sides = {row.side for row in group}
        opposing = sides in ({"over", "under"}, {"yes", "no"}) and len(group) == 2
        normalized = normalize_two_way_market(
            [row.american_odds for row in group] if opposing else [row.american_odds for row in group]
        )
        for row, result in zip(group, normalized):
            row.fair_market_probability = result.fair_market_probability
    session.commit()
    return rows
