from dataclasses import dataclass
from typing import Protocol

from app.runtime.execution_plan.domain import ExecutionPlan
from app.runtime.execution_request.domain import ExecutionRequest
from app.runtime.execution_request.ports import ExecutionRequestRecord


@dataclass(frozen=True)
class ExecutionPlanRecord:
    plan: ExecutionPlan
    request: ExecutionRequest
    canonical_input_content: bytes
    canonical_plan_content: bytes
    idempotency_identity: str
    stream_version: int = 0


class ExecutionPlanRepository(Protocol):
    def append(
        self,
        record: ExecutionPlanRecord,
        *,
        expected_version: int,
    ) -> tuple[ExecutionPlanRecord, bool]: ...

    def get(self, plan_id: str) -> ExecutionPlan | None: ...

    def record(self, plan_id: str) -> ExecutionPlanRecord | None: ...

    def history(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> tuple[ExecutionPlanRecord, ...]: ...

    def current(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> ExecutionPlan | None: ...


class AcceptedExecutionRequestSource(Protocol):
    def record(self, request_id: str) -> ExecutionRequestRecord | None: ...
