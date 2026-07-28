from dataclasses import dataclass, replace
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.runtime.execution_plan.domain import (
    ExecutionPlan,
    ExecutionPlanDigestMismatch,
    ExecutionPlanIdempotencyConflict,
    ExecutionPlanIdentityMismatch,
    ExecutionPlanNotFound,
    ExecutionPlanOrganizationMismatch,
    ExecutionPlanRequestInvalid,
    ExecutionPlanReplayDiverged,
    ExecutionPlanReconstructionFailed,
    ExecutionPlanVersionConflict,
    ExecutionPlanningInput,
    PlanDerivationOutcome,
    PlanDerivationResult,
)
from app.runtime.execution_plan.ports import (
    AcceptedExecutionRequestSource,
    ExecutionPlanRecord,
    ExecutionPlanRepository,
)
from app.runtime.execution_plan.serialization import (
    build_execution_plan,
    plan_idempotency_identity,
    reconstruct_execution_plan,
)
from app.runtime.execution_plan.validation import (
    RequestValidationEvidenceSource,
    ValidationOutcome,
    validate_request_validation_evidence,
)
from app.runtime.execution_request.serialization import (
    reconstruct_execution_request,
)
from app.runtime.execution_request.domain import ExecutionRequestError


StreamKey = tuple[str, str, str]


@dataclass(frozen=True)
class _RepositoryState:
    streams: Mapping[StreamKey, tuple[ExecutionPlanRecord, ...]]
    by_id: Mapping[str, ExecutionPlanRecord]
    by_idempotency: Mapping[str, ExecutionPlanRecord]
    current: Mapping[StreamKey, str]


class InMemoryExecutionPlanRepository:
    """Thread-safe reference adapter with atomic immutable publication."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = _RepositoryState(
            streams=MappingProxyType({}),
            by_id=MappingProxyType({}),
            by_idempotency=MappingProxyType({}),
            current=MappingProxyType({}),
        )

    @staticmethod
    def _stream_key(plan: ExecutionPlan) -> StreamKey:
        return (
            plan.organization_id,
            plan.workload_context_id,
            plan.request_id,
        )

    def append(
        self,
        record: ExecutionPlanRecord,
        *,
        expected_version: int,
    ) -> tuple[ExecutionPlanRecord, bool]:
        self._validate_record(record)
        plan = record.plan
        stream_key = self._stream_key(plan)
        with self._lock:
            state = self._state
            prior = state.by_idempotency.get(
                record.idempotency_identity
            )
            if prior is not None:
                if not self._equivalent(prior, record):
                    raise ExecutionPlanIdempotencyConflict(
                        "Idempotency identity was used for different canonical input."
                    )
                return prior, False
            stream = state.streams.get(stream_key, ())
            current_version = len(stream)
            if expected_version != current_version:
                raise ExecutionPlanVersionConflict(
                    f"Expected version {expected_version}; "
                    f"current version is {current_version}."
                )
            prior_identity = state.by_id.get(plan.plan_id)
            if prior_identity is not None:
                if not self._equivalent(prior_identity, record):
                    raise ExecutionPlanIdentityMismatch(
                        "Canonical plan identity conflicts with retained evidence."
                    )
                next_idempotency = dict(state.by_idempotency)
                next_idempotency[record.idempotency_identity] = prior_identity
                self._commit_state(
                    _RepositoryState(
                        streams=state.streams,
                        by_id=state.by_id,
                        by_idempotency=MappingProxyType(
                            next_idempotency
                        ),
                        current=state.current,
                    )
                )
                return prior_identity, False
            accepted = replace(
                record, stream_version=current_version + 1
            )
            next_streams = dict(state.streams)
            next_by_id = dict(state.by_id)
            next_idempotency = dict(state.by_idempotency)
            next_current = dict(state.current)
            next_streams[stream_key] = (*stream, accepted)
            next_by_id[plan.plan_id] = accepted
            next_idempotency[record.idempotency_identity] = accepted
            next_current[stream_key] = plan.plan_id
            self._commit_state(
                _RepositoryState(
                    streams=MappingProxyType(next_streams),
                    by_id=MappingProxyType(next_by_id),
                    by_idempotency=MappingProxyType(next_idempotency),
                    current=MappingProxyType(next_current),
                )
            )
            return accepted, True

    @staticmethod
    def _equivalent(
        first: ExecutionPlanRecord, second: ExecutionPlanRecord
    ) -> bool:
        return (
            first.plan == second.plan
            and first.request == second.request
            and first.canonical_input_content
            == second.canonical_input_content
            and first.canonical_plan_content
            == second.canonical_plan_content
        )

    @staticmethod
    def _validate_record(record: ExecutionPlanRecord) -> None:
        plan = record.plan
        request = record.request
        if (
            request.organization_id != plan.organization_id
            or request.workload_context_id != plan.workload_context_id
        ):
            raise ExecutionPlanOrganizationMismatch(
                "Execution Plan and Execution Request scopes differ."
            )
        if request.request_id != plan.request_id:
            raise ExecutionPlanIdentityMismatch(
                "Execution Plan references a different Execution Request."
            )
        reconstructed = reconstruct_execution_plan(
            request=request,
            canonical_input_content=record.canonical_input_content,
            canonical_plan_content=record.canonical_plan_content,
            expected_input_digest=plan.canonical_input_digest,
            expected_plan_digest=plan.canonical_plan_digest,
            expected_plan_id=plan.plan_id,
        )
        if reconstructed != plan:
            raise ExecutionPlanDigestMismatch(
                "Canonical evidence does not reproduce the supplied plan."
            )
        if record.stream_version != 0:
            raise ExecutionPlanVersionConflict(
                "Candidate records must not predeclare a stream version."
            )
        if (
            len(record.idempotency_identity) != 64
            or any(
                character not in "0123456789abcdef"
                for character in record.idempotency_identity
            )
        ):
            raise ExecutionPlanIdempotencyConflict(
                "Idempotency identity must be lowercase SHA-256 hex."
            )

    def get(self, plan_id: str) -> ExecutionPlan | None:
        with self._lock:
            record = self._state.by_id.get(plan_id)
            return record.plan if record else None

    def record(self, plan_id: str) -> ExecutionPlanRecord | None:
        with self._lock:
            return self._state.by_id.get(plan_id)

    def history(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> tuple[ExecutionPlanRecord, ...]:
        with self._lock:
            return self._state.streams.get(
                (organization_id, workload_context_id, request_id), ()
            )

    def current(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> ExecutionPlan | None:
        with self._lock:
            plan_id = self._state.current.get(
                (organization_id, workload_context_id, request_id)
            )
            if plan_id is None:
                return None
            return self._state.by_id[plan_id].plan

    def _commit_state(self, state: _RepositoryState) -> None:
        """Publish one fully prepared snapshot; override for failure injection."""
        self._state = state


class ExecutionPlanService:
    def __init__(
        self,
        *,
        accepted_requests: AcceptedExecutionRequestSource,
        validation_evidence: RequestValidationEvidenceSource,
        repository: ExecutionPlanRepository | None = None,
    ) -> None:
        self.accepted_requests = accepted_requests
        self.validation_evidence = validation_evidence
        self.repository = repository or InMemoryExecutionPlanRepository()

    def derive(
        self,
        planning_input: ExecutionPlanningInput,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> PlanDerivationResult:
        retained_request = self.accepted_requests.record(
            planning_input.request_id
        )
        if retained_request is None:
            raise ExecutionPlanRequestInvalid(
                "Execution Request is not retained as accepted upstream evidence."
            )
        try:
            reconstructed_request = reconstruct_execution_request(
                retained_request.canonical_content,
                expected_digest=retained_request.request.canonical_digest,
            )
        except ExecutionRequestError as exc:
            raise ExecutionPlanRequestInvalid(
                "Retained Execution Request evidence is invalid."
            ) from exc
        if (
            reconstructed_request != retained_request.request
            or retained_request.request.organization_id
            != planning_input.organization_id
            or retained_request.request.workload_context_id
            != planning_input.workload_context_id
        ):
            raise ExecutionPlanRequestInvalid(
                "Execution Request differs from retained accepted evidence."
            )
        validation = self.validation_evidence.get(
            planning_input.validation_evidence_id
        )
        if validation is None:
            raise ExecutionPlanRequestInvalid(
                "Retained Request Validation evidence is required."
            )
        validate_request_validation_evidence(validation)
        if (
            validation.validation_evidence_id
            != planning_input.validation_evidence_id
            or validation.outcome is not ValidationOutcome.VALID
            or validation.request_id != retained_request.request.request_id
            or validation.canonical_request_digest
            != retained_request.request.canonical_digest
            or validation.organization_id
            != retained_request.request.organization_id
            or validation.workload_context_id
            != retained_request.request.workload_context_id
        ):
            raise ExecutionPlanRequestInvalid(
                "Request Validation evidence is invalid or inapplicable."
            )
        accepted_identity = plan_idempotency_identity(
            organization_id=planning_input.organization_id,
            workload_context_id=planning_input.workload_context_id,
            request_id=planning_input.request_id,
            submitted_key=idempotency_key,
        )
        plan, canonical_input, canonical_plan = build_execution_plan(
            planning_input,
            request=retained_request.request,
            validation=validation,
        )
        accepted, created = self.repository.append(
            ExecutionPlanRecord(
                plan=plan,
                request=retained_request.request,
                canonical_input_content=canonical_input,
                canonical_plan_content=canonical_plan,
                idempotency_identity=accepted_identity,
            ),
            expected_version=expected_version,
        )
        return PlanDerivationResult(
            outcome=(
                PlanDerivationOutcome.CREATED
                if created
                else PlanDerivationOutcome.EXISTING_EQUIVALENT
            ),
            plan=accepted.plan,
            stream_version=accepted.stream_version,
        )

    def get(
        self, plan_id: str, *, organization_id: str
    ) -> ExecutionPlan | None:
        plan = self.repository.get(plan_id)
        if plan is None or plan.organization_id != organization_id:
            return None
        return plan

    def history(
        self,
        *,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> tuple[ExecutionPlan, ...]:
        return tuple(
            record.plan
            for record in self.repository.history(
                organization_id, workload_context_id, request_id
            )
        )

    def current(
        self,
        *,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ) -> ExecutionPlan | None:
        return self.repository.current(
            organization_id, workload_context_id, request_id
        )

    def reconstruct(
        self, plan_id: str, *, organization_id: str
    ) -> ExecutionPlan:
        record = self.repository.record(plan_id)
        if (
            record is None
            or record.plan.organization_id != organization_id
        ):
            raise ExecutionPlanNotFound("Execution Plan was not found.")
        history = self.repository.history(
            record.plan.organization_id,
            record.plan.workload_context_id,
            record.plan.request_id,
        )
        versions = tuple(item.stream_version for item in history)
        if versions != tuple(range(1, len(history) + 1)):
            raise ExecutionPlanReconstructionFailed(
                "Execution Plan history has a version gap."
            )
        reconstructed = reconstruct_execution_plan(
            request=record.request,
            canonical_input_content=record.canonical_input_content,
            canonical_plan_content=record.canonical_plan_content,
            expected_input_digest=record.plan.canonical_input_digest,
            expected_plan_digest=record.plan.canonical_plan_digest,
            expected_plan_id=record.plan.plan_id,
        )
        if reconstructed != record.plan:
            raise ExecutionPlanReplayDiverged(
                "Retained inputs did not reproduce the Execution Plan."
            )
        return reconstructed
