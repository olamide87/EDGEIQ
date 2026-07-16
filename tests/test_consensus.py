from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.db_models import PropLine
from app.services.odds_movement import market_consensus


def row(book_id: int, line: float, odds: int) -> PropLine:
    return PropLine(
        event_id=1, player_id=1, sportsbook_id=book_id,
        market="player_receptions", side="over", line=Decimal(str(line)),
        american_odds=odds, captured_at=datetime.now(timezone.utc),
    )


def test_consensus_requires_two_independent_books():
    assert market_consensus([row(1, 5.5, -110)]) is None


def test_consensus_uses_median_line_and_implied_probability():
    result = market_consensus([row(1, 5.5, -110), row(2, 6.5, 110)])
    assert result.median_line == 6.0
    assert result.median_implied_probability == pytest.approx(
        (0.5238095238 + 0.4761904762) / 2
    )
    assert result.books_contributing == 2
