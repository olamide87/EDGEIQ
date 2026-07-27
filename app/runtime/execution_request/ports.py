from dataclasses import dataclass
from typing import Protocol

from app.runtime.execution_request.domain import ExecutionRequest


@dataclass(frozen=True)
class ExecutionRequestRecord:
    request: ExecutionRequest
    canonical_content: bytes


class ExecutionRequestRepository(Protocol):
    def admit(
        self, record: ExecutionRequestRecord
    ) -> tuple[ExecutionRequest, bool]: ...

    def get(self, request_id: str) -> ExecutionRequest | None: ...

    def record(self, request_id: str) -> ExecutionRequestRecord | None: ...
