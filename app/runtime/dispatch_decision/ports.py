from dataclasses import dataclass
from typing import Protocol

from app.runtime.dispatch_decision.domain import DispatchDecision, DispatchRequest


@dataclass(frozen=True)
class DispatchDecisionRecord:
    request: DispatchRequest
    decision: DispatchDecision
    idempotency_identity: str
    canonical_input_content: bytes
    canonical_decision_content: bytes


class DispatchDecisionRepository(Protocol):
    def append(self, record: DispatchDecisionRecord, *, expected_version: int) -> DispatchDecision: ...
    def record(self, decision_id: str) -> DispatchDecisionRecord | None: ...
    def history(self, stream_key: tuple[str, str, str, str, str]) -> tuple[DispatchDecisionRecord, ...]: ...
    def current(self, stream_key: tuple[str, str, str, str, str]) -> DispatchDecision | None: ...
