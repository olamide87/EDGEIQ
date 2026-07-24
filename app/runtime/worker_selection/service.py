from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock

from app.runtime.worker_selection.domain import (
    SelectionIdempotencyConflict,
    SelectionReplayDiverged,
    SelectionReplayFailed,
    SelectionVersionConflict,
    WorkerSelection,
    WorkerSelectionRequest,
)
from app.runtime.worker_selection.evaluator import WorkerSelectionEvaluator
from app.runtime.worker_selection.ports import WorkerSelectionHistoryRecord
from app.runtime.worker_selection.serialization import canonical_hash


class InMemoryWorkerSelectionHistory:
    """Thread-safe reference adapter for the immutable history port."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._streams: dict[tuple[str, str], list[WorkerSelectionHistoryRecord]] = {}
        self._by_id: dict[str, WorkerSelectionHistoryRecord] = {}
        self._idempotency: dict[tuple[str, str, str, str], WorkerSelectionHistoryRecord] = {}

    def append(
        self,
        record: WorkerSelectionHistoryRecord,
        *,
        expected_version: int,
    ) -> WorkerSelection:
        selection = record.selection
        stream_key = (selection.organization_id, selection.workload_context_id)
        operation_key = (*stream_key, "evaluate", record.idempotency_key)
        with self._lock:
            prior = self._idempotency.get(operation_key)
            if prior is not None:
                if prior.canonical_input_hash != record.canonical_input_hash:
                    raise SelectionIdempotencyConflict(
                        "Idempotency key was used for different canonical input."
                    )
                return prior.selection
            stream = self._streams.setdefault(stream_key, [])
            current_version = len(stream)
            if expected_version != current_version:
                raise SelectionVersionConflict(
                    f"Expected version {expected_version}; current version is {current_version}."
                )
            prior_identity = self._by_id.get(selection.selection_id)
            if prior_identity is not None:
                if prior_identity.canonical_input_hash != record.canonical_input_hash:
                    raise SelectionIdempotencyConflict(
                        "Canonical selection identity conflicts with retained input."
                    )
                self._idempotency[operation_key] = prior_identity
                return prior_identity.selection
            accepted = replace(
                selection,
                version=current_version + 1,
                recorded_at=datetime.now(timezone.utc),
            )
            accepted_record = replace(record, selection=accepted)
            stream.append(accepted_record)
            self._by_id[accepted.selection_id] = accepted_record
            self._idempotency[operation_key] = accepted_record
            return accepted

    def get(self, selection_id: str) -> WorkerSelection | None:
        with self._lock:
            record = self._by_id.get(selection_id)
            return record.selection if record else None

    def record(self, selection_id: str) -> WorkerSelectionHistoryRecord | None:
        with self._lock:
            return self._by_id.get(selection_id)

    def history(
        self, organization_id: str, workload_context_id: str
    ) -> tuple[WorkerSelection, ...]:
        with self._lock:
            return tuple(
                record.selection
                for record in self._streams.get(
                    (organization_id, workload_context_id), ()
                )
            )

    def current(
        self, organization_id: str, workload_context_id: str
    ) -> WorkerSelection | None:
        history = self.history(organization_id, workload_context_id)
        return history[-1] if history else None


class WorkerSelectionService:
    def __init__(
        self,
        history: InMemoryWorkerSelectionHistory | None = None,
        evaluator: WorkerSelectionEvaluator | None = None,
    ) -> None:
        self.history_store = history or InMemoryWorkerSelectionHistory()
        self.evaluator = evaluator or WorkerSelectionEvaluator()

    def evaluate(
        self,
        request: WorkerSelectionRequest,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> WorkerSelection:
        if not idempotency_key:
            from app.runtime.worker_selection.domain import SelectionRequestInvalid

            raise SelectionRequestInvalid("An idempotency key is required.")
        input_hash = canonical_hash(
            request, namespace="worker-selection-service-input"
        )
        selection = self.evaluator.evaluate(
            request, version=expected_version + 1
        )
        return self.history_store.append(
            WorkerSelectionHistoryRecord(
                request=request,
                selection=selection,
                idempotency_key=idempotency_key,
                canonical_input_hash=input_hash,
            ),
            expected_version=expected_version,
        )

    def get(self, selection_id: str) -> WorkerSelection | None:
        return self.history_store.get(selection_id)

    def history(
        self, organization_id: str, workload_context_id: str
    ) -> tuple[WorkerSelection, ...]:
        return self.history_store.history(organization_id, workload_context_id)

    def current(
        self, organization_id: str, workload_context_id: str
    ) -> WorkerSelection | None:
        return self.history_store.current(organization_id, workload_context_id)

    def replay(self, selection_id: str) -> WorkerSelection:
        record = self.history_store.record(selection_id)
        if record is None:
            raise SelectionReplayFailed("Selection history is unavailable.")
        replayed = self.evaluator.evaluate(
            record.request, version=record.selection.version
        )
        expected = record.selection
        if (
            replayed.selection_id != expected.selection_id
            or replayed.canonical_hash != expected.canonical_hash
            or replayed.replay_metadata.replay_output_hash
            != expected.replay_metadata.replay_output_hash
        ):
            raise SelectionReplayDiverged("Retained inputs did not reproduce selection.")
        return replace(replayed, recorded_at=expected.recorded_at)


worker_selection_service = WorkerSelectionService()
