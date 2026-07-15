import pytest

from app.services.expected_value import ExpectedValueService, Rating


@pytest.mark.parametrize(
    ("probability", "odds", "expected_return", "rating"),
    [
        (0.60, -110, 0.14545, Rating.BET),
        (0.53, -110, 0.01182, Rating.WATCH),
        (0.50, -110, -0.04545, Rating.PASS),
        (0.40, 150, 0.0, Rating.WATCH),
    ],
)
def test_expected_value_ratings(probability, odds, expected_return, rating):
    result = ExpectedValueService().evaluate(probability, odds)
    assert result.expected_return == pytest.approx(expected_return, abs=0.00001)
    assert result.rating is rating


def test_expected_value_exposes_implied_probability():
    result = ExpectedValueService().evaluate(0.60, -110)
    assert result.implied_probability == pytest.approx(0.5238095)


def test_expected_value_validates_inputs_and_thresholds():
    with pytest.raises(ValueError):
        ExpectedValueService(watch_threshold=0.05, bet_threshold=0.05)
    with pytest.raises(ValueError):
        ExpectedValueService().evaluate(1.1, -110)
    with pytest.raises(ValueError):
        ExpectedValueService().evaluate(0.5, 0)
