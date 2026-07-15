from dataclasses import dataclass

from app.odds_math import implied_probability


@dataclass(frozen=True)
class NormalizedProbability:
    raw_implied_probability: float
    fair_market_probability: float | None
    vig_removed: bool


def normalize_two_way_market(american_odds: list[int]) -> list[NormalizedProbability]:
    """Remove vig proportionally when, and only when, both opposing prices exist."""
    raw = [implied_probability(price) for price in american_odds]
    if len(raw) != 2:
        return [NormalizedProbability(value, None, False) for value in raw]
    total = sum(raw)
    if total <= 0:
        return [NormalizedProbability(value, None, False) for value in raw]
    return [NormalizedProbability(value, value / total, True) for value in raw]
