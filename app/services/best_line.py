from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypeVar

from app.models import Side
from app.odds_math import american_to_decimal


class LineOffer(Protocol):
    line: Decimal | float | None
    american_odds: int
    side: str


T = TypeVar("T", bound=LineOffer)


@dataclass(frozen=True)
class BestLineSelection:
    offer: LineOffer
    reason: str


def select_best_line(offers: list[T]) -> tuple[T, str]:
    if not offers:
        raise ValueError("At least one offer is required.")
    side = offers[0].side

    def score(offer: T) -> tuple[float, float]:
        price = american_to_decimal(offer.american_odds)
        if offer.line is None or side in (Side.YES.value, Side.NO.value):
            return (0.0, price)
        line = float(offer.line)
        return (-line if side == Side.OVER.value else line, price)

    selected = max(offers, key=score)
    if selected.line is None or side in (Side.YES.value, Side.NO.value):
        reason = "Selected the best available price for this binary market."
    elif side == Side.OVER.value:
        reason = "Selected the lowest OVER line; price breaks ties between equal lines."
    else:
        reason = "Selected the highest UNDER line; price breaks ties between equal lines."
    return selected, reason
