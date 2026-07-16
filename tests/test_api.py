from datetime import datetime, timezone
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db_models import Event, Player, PropLine, Sportsbook


def seed_props(db: Session) -> list[PropLine]:
    player = Player(name="Amon-Ra St. Brown", team="DET", position="WR")
    event = Event(external_id="game-1", name="DET at CHI")
    draftkings = Sportsbook(name="DraftKings", key="draftkings")
    fanduel = Sportsbook(name="FanDuel", key="fanduel")
    db.add_all([player, event, draftkings, fanduel])
    db.flush()
    captured_at = datetime.now(timezone.utc)
    props = [
        PropLine(
            event_id=event.id,
            player_id=player.id,
            sportsbook_id=draftkings.id,
            market="player_receptions",
            side="over",
            line=6.5,
            american_odds=-105,
            captured_at=captured_at,
        ),
        PropLine(
            event_id=event.id,
            player_id=player.id,
            sportsbook_id=fanduel.id,
            market="player_receptions",
            side="over",
            line=7.5,
            american_odds=110,
            captured_at=captured_at,
        ),
    ]
    db.add_all(props)
    db.commit()
    return props


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.4.0"}


def test_props_can_be_listed_and_filtered(client: TestClient, db_session: Session):
    seed_props(db_session)
    response = client.get(
        "/props",
        params={"player": "Amon-Ra St. Brown", "market": "player_receptions", "side": "over"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert {item["sportsbook_name"] for item in response.json()} == {"DraftKings", "FanDuel"}
    assert all(item["raw_implied_probability"] > 0 for item in response.json())
    assert all(item["fair_market_probability"] is None for item in response.json())
    assert all(item["vig_removed"] is False for item in response.json())


def test_best_props_prefers_the_better_line(client: TestClient, db_session: Session):
    seed_props(db_session)
    response = client.get("/props/best")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["sportsbook_name"] == "DraftKings"
    assert response.json()[0]["line"] == 6.5
    assert "lowest OVER line" in response.json()[0]["selection_reason"]


def test_projection_creates_paper_recommendation(client: TestClient, db_session: Session):
    prop = seed_props(db_session)[0]
    response = client.post(
        "/projections",
        json={
            "prop_line_id": prop.id,
            "model_probability": 0.60,
            "projected_value": 7.2,
            "model_name": "test-model",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["projection"]["model_name"] == "test-model"
    assert body["recommendation"]["rating"] == "BET"
    assert body["recommendation"]["recommended_stake"] == 5
    assert "Paper recommendation only" in body["recommendation"]["rationale"]

    listed = client.get("/recommendations", params={"rating": "BET"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["prop_line_id"] == prop.id


def test_projection_rejects_unknown_prop(client: TestClient):
    response = client.post(
        "/projections", json={"prop_line_id": 999, "model_probability": 0.55}
    )
    assert response.status_code == 404


def test_projection_uses_best_line_before_expected_value(client: TestClient, db_session: Session):
    worse_prop = seed_props(db_session)[1]
    response = client.post(
        "/projections", json={"prop_line_id": worse_prop.id, "model_probability": 0.60}
    )
    assert response.status_code == 201
    assert response.json()["projection"]["prop_line_id"] != worse_prop.id
    assert response.json()["recommendation"]["sportsbook_name"] == "DraftKings"


def test_stale_low_confidence_projection_is_pass_with_reasons(
    client: TestClient, db_session: Session
):
    props = seed_props(db_session)
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    for prop in props:
        prop.captured_at = stale
    db_session.commit()
    response = client.post(
        "/projections",
        json={
            "prop_line_id": props[0].id,
            "model_probability": 0.70,
            "captured_at": stale.isoformat(),
            "confidence": {
                "data_quality": 0.2,
                "sample_size": 0.2,
                "role_stability": 0.2,
                "injury_certainty": 0.2,
                "matchup_certainty": 0.2,
                "market_stability": 0.2
            }
        },
    )
    assert response.status_code == 201
    recommendation = response.json()["recommendation"]
    assert recommendation["rating"] == "PASS"
    assert recommendation["recommended_stake"] == 0
    assert recommendation["data_age_seconds"] >= 7200
    assert len(recommendation["rejection_reasons"]) == 2
    assert response.json()["projection"]["confidence"]["overall_confidence"] == 0.2


def test_wr_receptions_baseline_endpoint(client: TestClient):
    response = client.post(
        "/projections/wr-receptions",
        json={
            "projected_team_pass_attempts": 35,
            "route_participation": 0.9,
            "targets_per_route_run": 0.25,
            "catch_probability": 0.7,
            "line": 5.5,
            "contextual_multipliers": {"matchup": 1.05}
        },
    )
    assert response.status_code == 200
    assert "not production-grade" in response.json()["model_label"]
    assert response.json()["captured_at"]
