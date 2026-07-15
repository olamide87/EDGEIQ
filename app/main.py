from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.paper_api import router as paper_router
from app.database import Base, engine
import app.db_models  # noqa: F401  Ensures all tables are registered.


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if getattr(application.state, "initialize_database", True):
        Path("data").mkdir(exist_ok=True)
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="EDGE IQ API",
    version="0.2.0",
    description="Paper-only NFL player-prop line shopping and expected-value API.",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(paper_router)
