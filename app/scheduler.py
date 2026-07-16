from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings, settings
from app.services.ingestion import IngestionService


def build_scheduler(
    *, config: Settings = settings, service: IngestionService | None = None
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    ingestion = service or IngestionService(config=config)
    for provider in config.enabled_provider_keys:
        scheduler.add_job(
            ingestion.run_provider,
            "interval",
            minutes=config.ingestion_poll_interval_minutes,
            args=[provider],
            id=f"ingest-{provider}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    return scheduler
