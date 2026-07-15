from dataclasses import dataclass
from enum import Enum

from app.odds_math import american_to_decimal, implied_probability


class Rating(str, Enum):
    PASS = "PASS"
    WATCH = "WATCH"
    BET = "BET"


@dataclass(frozen=True)
class ExpectedValueResult:
    model_probability: float
    implied_probability: float
    expected_return: float
    rating: Rating


class ExpectedValueService:
    def __init__(self, *, watch_threshold: float = 0.0, bet_threshold: float = 0.05):
        if bet_threshold <= watch_threshold:
            raise ValueError("Bet threshold must be greater than watch threshold.")
        self.watch_threshold = watch_threshold
        self.bet_threshold = bet_threshold

    def evaluate(self, model_probability: float, american_odds: int) -> ExpectedValueResult:
        if not 0 <= model_probability <= 1:
            raise ValueError("Model probability must be between 0 and 1.")

        expected_return = model_probability * american_to_decimal(american_odds) - 1
        if expected_return >= self.bet_threshold:
            rating = Rating.BET
        elif expected_return >= self.watch_threshold:
            rating = Rating.WATCH
        else:
            rating = Rating.PASS

        return ExpectedValueResult(
            model_probability=model_probability,
            implied_probability=implied_probability(american_odds),
            expected_return=expected_return,
            rating=rating,
        )
