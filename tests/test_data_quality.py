from datetime import datetime, timedelta, timezone

from app.models import Market, Offer, Side
from app.services.data_quality import validate_provider_payload


def valid_offer(**overrides):
    values = dict(
        event_id="event", event_name="DET at CHI", bookmaker="Book",
        market=Market.PLAYER_RECEPTIONS, player="Receiver", side=Side.OVER,
        line=5.5, american_odds=-110,
    )
    values.update(overrides)
    return Offer(**values)


def test_data_quality_detects_invalid_and_duplicate_contracts():
    offer = valid_offer()
    result = validate_provider_payload([offer, offer, valid_offer(american_odds=0)])
    categories = {flag.category for flag in result.flags}
    assert "DUPLICATE_CONTRACT" in categories
    assert "INVALID_ODDS" in categories
    assert len(result.offers) == 1


def test_data_quality_detects_stale_impossible_and_malformed_records():
    result = validate_provider_payload([
        valid_offer(commence_time=datetime.now(timezone.utc) - timedelta(days=1)),
        valid_offer(line=-1),
        {"market": "unsupported", "player": "Receiver"},
    ], stale_event_hours=1)
    categories = {flag.category for flag in result.flags}
    assert {"STALE_EVENT", "IMPOSSIBLE_LINE", "UNSUPPORTED_MARKET"} <= categories


def test_data_quality_rejects_non_list_payload():
    result = validate_provider_payload({"not": "a list"})
    assert result.offers == []
    assert result.flags[0].category == "MALFORMED_PAYLOAD"
