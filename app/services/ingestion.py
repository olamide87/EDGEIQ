import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.database import SessionLocal
from app.db_models import IngestionJob, OddsSnapshotBatch, ProviderHealth
from app.models import Offer
from app.persistence import persist_offers
from app.providers.registry import ProviderRegistry, provider_registry
from app.services.data_quality import QualityFlag, validate_provider_payload

logger = logging.getLogger("edgeiq.ingestion")
SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class IngestionRunResult:
    job_id: int
    correlation_id: str
    provider: str
    status: str
    row_count: int
    duplicate_suppressed: bool
    quality_flags: list[QualityFlag]


def _payload_hash(offers: list[Offer]) -> str:
    records = [
        {
            "event_id": item.event_id,
            "event_name": item.event_name,
            "commence_time": item.commence_time.isoformat() if item.commence_time else None,
            "bookmaker": item.bookmaker,
            "market": item.market.value,
            "player": item.player,
            "side": item.side.value,
            "line": item.line,
            "american_odds": item.american_odds,
        }
        for item in offers
    ]
    serialized = json.dumps(sorted(records, key=lambda value: json.dumps(value, sort_keys=True)), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _safe_error(error: Exception, api_key: str) -> str:
    message = str(error)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1[REDACTED]", message)
    return message[:1000]


class IngestionService:
    def __init__(
        self,
        *,
        registry: ProviderRegistry = provider_registry,
        session_factory: SessionFactory = SessionLocal,
        config: Settings = settings,
    ) -> None:
        self.registry = registry
        self.session_factory = session_factory
        self.config = config

    async def run_provider(self, provider_key: str) -> IngestionRunResult:
        correlation_id = str(uuid4())
        started = datetime.now(timezone.utc)
        with self.session_factory() as session:
            job = IngestionJob(
                correlation_id=correlation_id,
                provider=provider_key,
                status="RUNNING",
                started_at=started,
            )
            session.add(job)
            session.commit()
            job_id = job.id

        error: Exception | None = None
        error_category: str | None = None
        payload: object = []
        latency_ms = 0.0
        attempts = 0
        try:
            provider = self.registry.get(provider_key)
        except KeyError as exc:
            error = exc
            error_category = "CONFIGURATION"
            provider = None

        if provider is not None:
            for attempts in range(1, self.config.provider_retry_count + 2):
                began = perf_counter()
                try:
                    payload = await asyncio.wait_for(
                        provider.fetch_nfl_player_props(),
                        timeout=self.config.provider_timeout_seconds,
                    )
                    latency_ms = (perf_counter() - began) * 1000
                    error = None
                    break
                except asyncio.TimeoutError as exc:
                    latency_ms = (perf_counter() - began) * 1000
                    error = exc
                    error_category = "TIMEOUT"
                except Exception as exc:  # Provider boundaries categorize external failures.
                    latency_ms = (perf_counter() - began) * 1000
                    error = exc
                    error_category = "PROVIDER_ERROR"

        if error is not None:
            message = _safe_error(error, self.config.odds_api_key)
            with self.session_factory() as session:
                job = session.get(IngestionJob, job_id)
                if job is None:
                    raise RuntimeError("Ingestion job disappeared during execution.")
                job.status = "FAILED"
                job.ended_at = datetime.now(timezone.utc)
                job.attempt_count = attempts
                job.error_category = error_category
                job.error_message = message
                self._record_failure(session, provider_key, latency_ms)
                session.commit()
            logger.error(
                "Provider ingestion failed",
                extra={"correlation_id": correlation_id, "provider": provider_key,
                       "error_category": error_category},
            )
            return IngestionRunResult(job_id, correlation_id, provider_key, "FAILED", 0, False, [])

        validated = validate_provider_payload(
            payload,
            stale_event_hours=self.config.ingestion_stale_event_hours,
        )
        flags = validated.flags
        if not validated.offers and payload:
            with self.session_factory() as session:
                job = session.get(IngestionJob, job_id)
                if job is None:
                    raise RuntimeError("Ingestion job disappeared during validation.")
                job.status = "FAILED"
                job.ended_at = datetime.now(timezone.utc)
                job.attempt_count = attempts
                job.error_category = "DATA_QUALITY"
                job.error_message = "Provider payload contained no valid offers."
                self._record_failure(session, provider_key, latency_ms)
                session.commit()
            return IngestionRunResult(job_id, correlation_id, provider_key, "FAILED", 0, False, flags)

        digest = _payload_hash(validated.offers)
        with self.session_factory() as session:
            latest = session.scalar(
                select(OddsSnapshotBatch)
                .where(OddsSnapshotBatch.provider == provider_key)
                .order_by(OddsSnapshotBatch.captured_at.desc(), OddsSnapshotBatch.id.desc())
                .limit(1)
            )
            duplicate = latest is not None and latest.payload_hash == digest
            batch = OddsSnapshotBatch(
                ingestion_job_id=job_id,
                provider=provider_key,
                payload_hash=digest,
                row_count=0 if duplicate else len(validated.offers),
                duplicate_suppressed=duplicate,
                quality_flags=json.dumps([asdict(flag) for flag in flags]),
            )
            session.add(batch)
            session.commit()
            batch_id = batch.id

        row_count = 0
        status = "DUPLICATE_SUPPRESSED" if duplicate else "SUCCESS"
        if not duplicate:
            try:
                with self.session_factory() as session:
                    rows = persist_offers(
                        session,
                        validated.offers,
                        provider_key=provider_key,
                        snapshot_batch_id=batch_id,
                    )
                    row_count = len(rows)
            except Exception as exc:
                message = _safe_error(exc, self.config.odds_api_key)
                with self.session_factory() as session:
                    job = session.get(IngestionJob, job_id)
                    batch = session.get(OddsSnapshotBatch, batch_id)
                    if job is None or batch is None:
                        raise RuntimeError("Ingestion audit records disappeared.") from exc
                    job.status = "FAILED"
                    job.ended_at = datetime.now(timezone.utc)
                    job.attempt_count = attempts
                    job.error_category = "PERSISTENCE"
                    job.error_message = message
                    batch.row_count = 0
                    self._record_failure(session, provider_key, latency_ms)
                    session.commit()
                return IngestionRunResult(
                    job_id, correlation_id, provider_key, "FAILED", 0, False, flags
                )
        with self.session_factory() as session:
            job = session.get(IngestionJob, job_id)
            if job is None:
                raise RuntimeError("Ingestion job disappeared during completion.")
            job.status = status
            job.ended_at = datetime.now(timezone.utc)
            job.attempt_count = attempts
            job.row_count = row_count
            self._record_success(session, provider_key, latency_ms, len(validated.offers))
            session.commit()
        logger.info(
            "Provider ingestion completed",
            extra={"correlation_id": correlation_id, "provider": provider_key, "row_count": row_count},
        )
        return IngestionRunResult(
            job_id, correlation_id, provider_key, status, row_count, duplicate, flags
        )

    @staticmethod
    def _health(session: Session, provider: str) -> ProviderHealth:
        health = session.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider))
        if health is None:
            health = ProviderHealth(provider=provider)
            session.add(health)
            session.flush()
        return health

    def _record_success(
        self, session: Session, provider: str, latency_ms: float, records: int
    ) -> None:
        health = self._health(session, provider)
        previous_count = health.successful_fetches
        previous_average = Decimal(health.average_latency_ms)
        health.successful_fetches += 1
        health.average_latency_ms = (
            previous_average * previous_count + Decimal(str(latency_ms))
        ) / health.successful_fetches
        health.last_successful_fetch = datetime.now(timezone.utc)
        health.consecutive_failures = 0
        health.records_returned = records
        health.status = "HEALTHY"

    def _record_failure(self, session: Session, provider: str, latency_ms: float) -> None:
        health = self._health(session, provider)
        health.last_failed_fetch = datetime.now(timezone.utc)
        health.consecutive_failures += 1
        health.status = "DOWN" if health.consecutive_failures >= 3 else "DEGRADED"
        if health.successful_fetches == 0:
            health.average_latency_ms = Decimal(str(latency_ms))
