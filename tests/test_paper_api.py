from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_api import seed_props
from app.db_models import PropLine


def create_recommendation(client: TestClient, prop_id: int) -> int:
    response = client.post(
        "/projections",
        json={"prop_line_id": prop_id, "model_probability": 0.65, "model_name": "paper-test"},
    )
    assert response.status_code == 201
    return response.json()["recommendation"]["id"]


def test_paper_bet_close_settle_and_performance(client: TestClient, db_session: Session):
    recommendation_id = create_recommendation(client, seed_props(db_session)[0].id)
    created = client.post(
        "/paper-bets", json={"recommendation_id": recommendation_id, "stake": "5.00"}
    )
    assert created.status_code == 201
    bet = created.json()
    assert bet["status"] == "ACTIVE"
    assert Decimal(str(bet["stake"])) == Decimal("5.00")
    assert bet["opening_line"] == 6.5

    duplicate = client.post("/paper-bets", json={"recommendation_id": recommendation_id})
    assert duplicate.status_code == 409
    assert "Duplicate" in duplicate.json()["detail"]

    closed = client.post(
        f"/paper-bets/{bet['id']}/close",
        json={"closing_line": 6.5, "closing_odds": -110},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["closing"]["clv_percentage"] > 0
    assert closed.json()["closing"]["beat_closing_line"] is True

    settled = client.post(
        f"/paper-bets/{bet['id']}/settle", json={"outcome": "WIN", "result_value": 8}
    )
    assert settled.status_code == 200
    assert settled.json()["status"] == "SETTLED"
    assert Decimal(str(settled.json()["settlement"]["net_profit"])) == Decimal("4.76")

    listed = client.get("/paper-bets")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    performance = client.get("/performance")
    assert performance.status_code == 200
    body = performance.json()
    assert body["total_bets"] == 1
    assert body["wins"] == 1
    assert Decimal(str(body["amount_risked"])) == Decimal("5.00")
    assert Decimal(str(body["net_profit"])) == Decimal("4.76")
    assert body["roi"] == 0.952
    assert body["by_market"]["player_receptions"]["bets"] == 1
    assert body["by_sportsbook"]["DraftKings"]["bets"] == 1
    assert body["by_recommendation_rating"]["BET"]["bets"] == 1


def test_paper_bet_enforces_single_stake_limit(client: TestClient, db_session: Session):
    recommendation_id = create_recommendation(client, seed_props(db_session)[0].id)
    response = client.post(
        "/paper-bets", json={"recommendation_id": recommendation_id, "stake": "10.01"}
    )
    assert response.status_code == 409
    assert "single stake" in response.json()["detail"][0]


def test_paper_bets_flag_correlation_and_enforce_player_exposure(
    client: TestClient, db_session: Session
):
    base = seed_props(db_session)[0]
    first_rec = create_recommendation(client, base.id)
    assert client.post("/paper-bets", json={"recommendation_id": first_rec}).status_code == 201

    under = PropLine(
        event_id=base.event_id, player_id=base.player_id, sportsbook_id=base.sportsbook_id,
        market="player_receptions", side="under", line=6.5, american_odds=-105,
        captured_at=base.captured_at,
    )
    db_session.add(under)
    db_session.commit()
    second_rec = create_recommendation(client, under.id)
    correlated = client.post(
        "/paper-bets", json={"recommendation_id": second_rec, "stake": "10.00"}
    )
    assert correlated.status_code == 201
    assert set(correlated.json()["correlation_flags"]) == {
        "CORRELATED_SAME_PLAYER", "CORRELATED_SAME_EVENT"
    }

    third = PropLine(
        event_id=base.event_id, player_id=base.player_id, sportsbook_id=base.sportsbook_id,
        market="player_anytime_td", side="yes", line=None, american_odds=120,
        captured_at=base.captured_at,
    )
    db_session.add(third)
    db_session.commit()
    third_rec = create_recommendation(client, third.id)
    rejected = client.post("/paper-bets", json={"recommendation_id": third_rec})
    assert rejected.status_code == 409
    assert any("player exposure" in reason for reason in rejected.json()["detail"])
