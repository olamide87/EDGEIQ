from dataclasses import dataclass
from typing import Protocol

from app.runtime.work_claim.domain import WorkClaimEvent, WorkClaimRequest

LineageKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class WorkClaimRecord:
    request: WorkClaimRequest
    event: WorkClaimEvent
    idempotency_identity: str
    canonical_input_content: bytes
    canonical_event_content: bytes


class WorkClaimRepository(Protocol):
    def append(self, record: WorkClaimRecord, *, expected_version: int) -> WorkClaimEvent: ...
    def record(self, event_id: str) -> WorkClaimRecord | None: ...
    def history(self, lineage_key: LineageKey) -> tuple[WorkClaimRecord, ...]: ...
    def current(self, lineage_key: LineageKey) -> WorkClaimEvent | None: ...
