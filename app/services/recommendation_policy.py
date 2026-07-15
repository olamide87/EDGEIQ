from dataclasses import dataclass

from app.services.expected_value import Rating


@dataclass(frozen=True)
class RecommendationDecision:
    rating: Rating
    rejection_reasons: list[str]


@dataclass(frozen=True)
class RecommendationPolicy:
    min_watch_ev: float = 0.0
    min_bet_ev: float = 0.05
    min_watch_confidence: float = 0.50
    min_bet_confidence: float = 0.70
    fresh_data_seconds: int = 900
    stale_data_seconds: int = 3600

    def decide(
        self, *, expected_return: float, confidence: float, data_age_seconds: int
    ) -> RecommendationDecision:
        failures: list[str] = []
        if expected_return < self.min_watch_ev:
            failures.append(
                f"Expected return {expected_return:.2%} is below the minimum edge threshold."
            )
        if confidence < self.min_watch_confidence:
            failures.append(
                f"Overall confidence {confidence:.1%} is below the minimum confidence threshold."
            )
        if data_age_seconds > self.stale_data_seconds:
            failures.append(
                f"Input data is stale at {data_age_seconds} seconds old."
            )
        if failures:
            return RecommendationDecision(Rating.PASS, failures)

        borderline: list[str] = []
        if expected_return < self.min_bet_ev:
            borderline.append(
                f"Expected return {expected_return:.2%} is below the BET threshold."
            )
        if confidence < self.min_bet_confidence:
            borderline.append(
                f"Overall confidence {confidence:.1%} is below the BET threshold."
            )
        if data_age_seconds > self.fresh_data_seconds:
            borderline.append(
                f"Input data is borderline at {data_age_seconds} seconds old."
            )
        if borderline:
            return RecommendationDecision(Rating.WATCH, borderline)
        return RecommendationDecision(Rating.BET, [])
