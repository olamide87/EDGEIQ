from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db_models import PropLine
from app.ingestion_api import get_ingestion_service
from app.main import app
from tests.test_api import seed_props
from tests.test_ingestion import FakeProvider, make_service


def test_ingestion_and_health_api(client: TestClient, db_session: Session):
    service = make_service(db_session, FakeProvider())
    app.dependency_overrides[get_ingestion_service] = lambda: service

    run = client.post("/ingestion/run", json={"provider": "fake"})
    assert run.status_code == 200
    assert run.json()[0]["status"] == "SUCCESS"
    assert run.json()[0]["row_count"] == 1

    jobs = client.get("/ingestion/jobs")
    assert jobs.status_code == 200
    assert jobs.json()[0]["provider"] == "fake"
    assert jobs.json()[0]["correlation_id"]

    health = client.get("/providers/health")
    assert health.status_code == 200
    assert health.json()[0]["status"] == "HEALTHY"
    assert health.json()[0]["records_returned"] == 1


def test_odds_history_and_movements_api(client: TestClient, db_session: Session):
    initial = seed_props(db_session)
    draftkings = initial[0]
    moved = PropLine(
        event_id=draftkings.event_id,
        player_id=draftkings.player_id,
        sportsbook_id=draftkings.sportsbook_id,
        market=draftkings.market,
        side=draftkings.side,
        line=7.0,
        american_odds=100,
        captured_at=draftkings.captured_at + timedelta(minutes=10),
        provider_key="test",
        raw_player_name="Amon-Ra St. Brown",
    )
    db_session.add(moved)
    db_session.commit()

    history = client.get("/odds/history", params={"market": "player_receptions"})
    assert history.status_code == 200
    assert len(history.json()) == 3
    assert history.json()[0]["raw_player_name"] == "Amon-Ra St. Brown"

    response = client.get("/odds/movements")
    assert response.status_code == 200
    movements = response.json()
    assert len(movements) == 2
    dk = next(item for item in movements if item["sportsbook_name"] == "DraftKings")
    assert dk["first_observed_line"] == 6.5
    assert dk["latest_line"] == 7.0
    assert dk["movements"][-1]["direction"] == "UP"
    assert dk["sportsbook_moved_first"] == "DraftKings"
    assert dk["consensus"]["median_line"] == 7.25
    assert dk["consensus"]["books_contributing"] == 2
