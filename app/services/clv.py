from dataclasses import dataclass

from app.models import Side
from app.odds_math import american_to_decimal


@dataclass(frozen=True)
class CLVResult:
    line_movement: float | None
    price_movement: float
    beat_closing_line: bool
    clv_percentage: float | None


def calculate_clv(
    *, side: str, bet_line: float | None, bet_odds: int,
    closing_line: float | None, closing_odds: int,
) -> CLVResult:
    line_movement = (
        closing_line - bet_line if bet_line is not None and closing_line is not None else None
    )
    bet_decimal = american_to_decimal(bet_odds)
    close_decimal = american_to_decimal(closing_odds)
    price_movement = bet_decimal - close_decimal

    if bet_line is None or closing_line is None:
        beat = bet_decimal > close_decimal
    elif side == Side.OVER.value and bet_line != closing_line:
        beat = bet_line < closing_line
    elif side == Side.UNDER.value and bet_line != closing_line:
        beat = bet_line > closing_line
    else:
        beat = bet_decimal > close_decimal

    same_contract = bet_line == closing_line or (bet_line is None and closing_line is None)
    clv = bet_decimal / close_decimal - 1 if same_contract else None
    return CLVResult(line_movement, price_movement, beat, clv)
