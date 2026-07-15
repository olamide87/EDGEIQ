import pytest

from app.services.clv import calculate_clv


def test_clv_tracks_line_movement_and_beating_close():
    result = calculate_clv(
        side="over", bet_line=5.5, bet_odds=-110, closing_line=6.5, closing_odds=-110
    )
    assert result.line_movement == 1
    assert result.beat_closing_line is True
    assert result.clv_percentage is None


def test_clv_percentage_only_compares_same_contract():
    result = calculate_clv(
        side="under", bet_line=6.5, bet_odds=110, closing_line=6.5, closing_odds=-110
    )
    assert result.clv_percentage == pytest.approx(0.1)
    assert result.beat_closing_line is True
