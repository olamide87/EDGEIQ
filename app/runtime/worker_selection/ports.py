from dataclasses import dataclass
from typing import Protocol

from app.runtime.worker_selection.domain import WorkerSelection, WorkerSelectionRequest


@dataclass(frozen=True)
class WorkerSelectionHistoryRecord:
    request: WorkerSelectionRequest
    selection: WorkerSelection
    idempotency_key: str
    canonical_input_hash: str


class WorkerSelectionHistory(Protocol):
    def append(
        self,
        record: WorkerSelectionHistoryRecord,
        *,
        expected_version: int,
    ) -> WorkerSelection: ...

    def get(self, selection_id: str) -> WorkerSelection | None: ...

    def history(
        self, organization_id: str, workload_context_id: str
    ) -> tuple[WorkerSelection, ...]: ...

    def current(
        self, organization_id: str, workload_context_id: str
    ) -> WorkerSelection | None: ...

    def record(self, selection_id: str) -> WorkerSelectionHistoryRecord | None: ...
