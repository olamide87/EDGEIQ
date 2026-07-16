from app.config import Settings
from app.scheduler import build_scheduler


def test_scheduler_uses_configured_interval_without_starting():
    scheduler = build_scheduler(config=Settings(
        enabled_providers="mock", ingestion_poll_interval_minutes=15
    ))
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "ingest-mock"
    assert str(jobs[0].trigger) == "interval[0:15:00]"
