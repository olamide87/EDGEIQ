from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.paper_api import router as paper_router
from app.ingestion_api import router as ingestion_router
from app.config import settings
from app.logging_config import configure_logging
from app.scheduler import build_scheduler
from app.database import Base, engine
import app.db_models  # noqa: F401  Ensures all tables are registered.


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if getattr(application.state, "initialize_database", True):
        Path("data").mkdir(exist_ok=True)
        Base.metadata.create_all(bind=engine)
    scheduler = None
    if settings.ingestion_enabled and getattr(application.state, "start_scheduler", True):
        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="EDGE IQ API",
    version="0.2.0",
    description="Paper-only NFL player-prop line shopping and expected-value API.",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(paper_router)
app.include_router(ingestion_router)
configure_logging()
