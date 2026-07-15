from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.services.best_line import select_best_line
from app.services.confidence import ConfidenceComponents, ConfidenceWeights, calculate_overall_confidence
from app.services.market_normalization import normalize_two_way_market
from app.services.recommendation_policy import RecommendationPolicy
from app.services.expected_value import Rating


@dataclass
class Candidate:
    side: str
    line: Decimal | None
    american_odds: int
    name: str


def test_vig_is_removed_proportionally_for_opposing_outcomes():
    results = normalize_two_way_market([-110, -110])
    assert [item.raw_implied_probability for item in results] == pytest.approx([0.5238095, 0.5238095])
    assert [item.fair_market_probability for item in results] == pytest.approx([0.5, 0.5])
    assert all(item.vig_removed for item in results)


def test_one_sided_market_does_not_claim_vig_removal():
    result = normalize_two_way_market([-110])[0]
    assert result.fair_market_probability is None
    assert result.vig_removed is False


def test_over_prefers_line_over_conflicting_price():
    low = Candidate("over", Decimal("5.5"), -160, "low-line")
    expensive_line = Candidate("over", Decimal("6.5"), 150, "better-price")
    selected, reason = select_best_line([expensive_line, low])
    assert selected.name == "low-line"
    assert "lowest OVER line" in reason


def test_under_prefers_highest_line_then_price():
    high = Candidate("under", Decimal("7.5"), -150, "high-line")
    good_price = Candidate("under", Decimal("6.5"), 140, "better-price")
    selected, _ = select_best_line([good_price, high])
    assert selected.name == "high-line"


def test_binary_market_compares_price_only():
    short = Candidate("yes", None, -130, "short")
    plus = Candidate("yes", None, 115, "plus")
    selected, reason = select_best_line([short, plus])
    assert selected.name == "plus"
    assert "binary market" in reason


def test_confidence_is_weighted_not_supplied():
    components = ConfidenceComponents(
        data_quality=1, sample_size=0.5, role_stability=0.5,
        injury_certainty=1, matchup_certainty=0, market_stability=1,
    )
    weights = ConfidenceWeights(
        data_quality=2, sample_size=1, role_stability=1,
        injury_certainty=0, matchup_certainty=0, market_stability=0,
    )
    assert calculate_overall_confidence(components, weights) == pytest.approx(0.75)


def test_recommendation_policy_rejects_and_downgrades_with_reasons():
    policy = RecommendationPolicy()
    stale = policy.decide(expected_return=0.10, confidence=0.9, data_age_seconds=4000)
    assert stale.rating is Rating.PASS
    assert "stale" in stale.rejection_reasons[0]
    borderline = policy.decide(expected_return=0.03, confidence=0.65, data_age_seconds=100)
    assert borderline.rating is Rating.WATCH
    assert len(borderline.rejection_reasons) == 2
    assert policy.decide(expected_return=0.10, confidence=0.9, data_age_seconds=10).rating is Rating.BET
