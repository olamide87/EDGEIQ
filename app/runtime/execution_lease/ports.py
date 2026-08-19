from dataclasses import dataclass
from typing import Protocol

from app.runtime.execution_lease.domain import ExecutionLeaseEvent, ExecutionLeaseRequest

LineageKey = tuple[str, str, str, str, str]


@dataclass(frozen=True)
class ExecutionLeaseRecord:
    request: ExecutionLeaseRequest
    event: ExecutionLeaseEvent
    idempotency_identity: str
    canonical_input_content: bytes
    canonical_event_content: bytes


class ExecutionLeaseRepository(Protocol):
    def append(self, record: ExecutionLeaseRecord, *, expected_version: int) -> ExecutionLeaseEvent: ...
    def record(self, event_id: str) -> ExecutionLeaseRecord | None: ...
    def history(self, lineage_key: LineageKey) -> tuple[ExecutionLeaseRecord, ...]: ...
    def current(self, lineage_key: LineageKey) -> ExecutionLeaseEvent | None: ...
