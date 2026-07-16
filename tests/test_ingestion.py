import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db_models import IngestionJob, OddsSnapshotBatch, PropLine, ProviderHealth
from app.models import Market, Offer, Side
from app.providers.base import OddsProvider
from app.providers.registry import ProviderRegistry
from app.services.ingestion import IngestionService


class FakeProvider(OddsProvider):
    key = "fake"

    def __init__(self, *, failures: int = 0, malformed: bool = False):
        self.failures = failures
        self.malformed = malformed
        self.calls = 0

    async def fetch_nfl_player_props(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("provider failed apiKey=super-secret")
        if self.malformed:
            return {"bad": "payload"}
        return [Offer(
            event_id="event-1", event_name="DET at CHI", bookmaker="Book",
            market=Market.PLAYER_RECEPTIONS, player="A.J. Brown Jr.",
            side=Side.OVER, line=5.5, american_odds=-110,
        )]


def make_service(db_session: Session, provider: FakeProvider, **settings_overrides):
    registry = ProviderRegistry()
    registry.register("fake", lambda: provider)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    config = Settings(
        provider_retry_count=settings_overrides.pop("provider_retry_count", 0),
        provider_timeout_seconds=1,
        odds_api_key="super-secret",
        **settings_overrides,
    )
    return IngestionService(registry=registry, session_factory=factory, config=config)


def test_successful_ingestion_and_duplicate_suppression(db_session: Session):
    provider = FakeProvider()
    service = make_service(db_session, provider)
    first = asyncio.run(service.run_provider("fake"))
    second = asyncio.run(service.run_provider("fake"))
    assert first.status == "SUCCESS"
    assert first.row_count == 1
    assert second.status == "DUPLICATE_SUPPRESSED"
    assert second.row_count == 0
    assert db_session.scalar(select(func.count(PropLine.id))) == 1
    assert db_session.scalar(select(func.count(OddsSnapshotBatch.id))) == 2
    health = db_session.scalar(select(ProviderHealth).where(ProviderHealth.provider == "fake"))
    assert health.status == "HEALTHY"
    assert health.records_returned == 1


def test_ingestion_retries_then_recovers(db_session: Session):
    provider = FakeProvider(failures=2)
    result = asyncio.run(make_service(
        db_session, provider, provider_retry_count=2
    ).run_provider("fake"))
    assert result.status == "SUCCESS"
    assert provider.calls == 3
    job = db_session.get(IngestionJob, result.job_id)
    assert job.attempt_count == 3


def test_provider_failures_transition_health_to_down_and_redact_secrets(db_session: Session):
    provider = FakeProvider(failures=99)
    service = make_service(db_session, provider)
    for _ in range(3):
        result = asyncio.run(service.run_provider("fake"))
        assert result.status == "FAILED"
    health = db_session.scalar(select(ProviderHealth).where(ProviderHealth.provider == "fake"))
    assert health.status == "DOWN"
    assert health.consecutive_failures == 3
    job = db_session.scalar(select(IngestionJob).order_by(IngestionJob.id.desc()))
    assert "super-secret" not in job.error_message
    assert "[REDACTED]" in job.error_message


def test_malformed_payload_is_recorded_as_data_quality_failure(db_session: Session):
    result = asyncio.run(make_service(
        db_session, FakeProvider(malformed=True)
    ).run_provider("fake"))
    assert result.status == "FAILED"
    assert result.quality_flags[0].category == "MALFORMED_PAYLOAD"
    job = db_session.get(IngestionJob, result.job_id)
    assert job.error_category == "DATA_QUALITY"
