from dataclasses import dataclass
from datetime import datetime
from statistics import median

from app.db_models import PropLine
from app.odds_math import implied_probability


@dataclass(frozen=True)
class MovementPoint:
    captured_at: datetime
    line: float | None
    american_odds: int
    direction: str


@dataclass(frozen=True)
class ConsensusResult:
    median_line: float
    median_implied_probability: float
    books_contributing: int


def market_consensus(latest_by_book: list[PropLine]) -> ConsensusResult | None:
    independent = {row.sportsbook_id: row for row in latest_by_book}
    with_lines = [row for row in independent.values() if row.line is not None]
    if len(independent) < 2 or len(with_lines) < 2:
        return None
    return ConsensusResult(
        median_line=float(median(float(row.line) for row in with_lines)),
        median_implied_probability=float(median(implied_probability(row.american_odds) for row in independent.values())),
        books_contributing=len(independent),
    )


def movement_direction(previous: PropLine, current: PropLine) -> str:
    if previous.line is not None and current.line is not None:
        if current.line > previous.line:
            return "UP"
        if current.line < previous.line:
            return "DOWN"
    if current.american_odds > previous.american_odds:
        return "PRICE_UP"
    if current.american_odds < previous.american_odds:
        return "PRICE_DOWN"
    return "UNCHANGED"
