import pytest
from app.odds_math import american_to_decimal, implied_probability


def test_negative_american_odds():
    assert american_to_decimal(-110) == pytest.approx(1.9090909)
    assert implied_probability(-110) == pytest.approx(0.5238095)


def test_positive_american_odds():
    assert american_to_decimal(150) == pytest.approx(2.5)
    assert implied_probability(150) == pytest.approx(0.4)
