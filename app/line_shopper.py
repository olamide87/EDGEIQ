from collections.abc import Iterable
from app.models import Offer, RankedOffer, MarketBoard, Market, Side
from app.odds_math import american_to_decimal, implied_probability


def _line_score(offer: Offer, side: Side) -> float:
    # For overs, a lower threshold is better. For unders, a higher threshold is better.
    # Binary yes/no markets have no line component.
    if offer.line is None:
        return 0.0
    if side == Side.OVER:
        return -offer.line
    if side == Side.UNDER:
        return offer.line
    return 0.0


def rank_offers(
    offers: Iterable[Offer],
    *,
    player: str,
    market: Market,
    side: Side,
) -> MarketBoard:
    selected = [
        o for o in offers
        if o.player.casefold() == player.casefold()
        and o.market == market
        and o.side == side
    ]

    # Primary sort: best threshold. Secondary sort: best payout.
    selected.sort(
        key=lambda o: (_line_score(o, side), american_to_decimal(o.american_odds)),
        reverse=True,
    )

    ranked = [
        RankedOffer(
            offer=offer,
            decimal_odds=round(american_to_decimal(offer.american_odds), 4),
            implied_probability=round(implied_probability(offer.american_odds), 4),
            rank=index,
        )
        for index, offer in enumerate(selected, start=1)
    ]
    return MarketBoard(player=player, market=market, side=side, offers=ranked)
