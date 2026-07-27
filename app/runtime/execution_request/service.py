from threading import RLock

from app.runtime.execution_request.domain import (
    AdmissionOutcome,
    AdmissionResult,
    ExecutionRequest,
    ExecutionRequestDigestMismatch,
    ExecutionRequestDraft,
    ExecutionRequestIdempotencyConflict,
    ExecutionRequestNotFound,
)
from app.runtime.execution_request.ports import (
    ExecutionRequestRecord,
    ExecutionRequestRepository,
)
from app.runtime.execution_request.serialization import (
    build_execution_request,
    idempotency_identity,
    reconstruct_execution_request,
)


class InMemoryExecutionRequestRepository:
    """Thread-safe reference adapter with atomic immutable admission."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_id: dict[str, ExecutionRequestRecord] = {}
        self._by_idempotency: dict[str, ExecutionRequestRecord] = {}

    def admit(
        self, record: ExecutionRequestRecord
    ) -> tuple[ExecutionRequest, bool]:
        with self._lock:
            prior = self._by_idempotency.get(
                record.request.idempotency_identity
            )
            if prior is not None:
                if (
                    prior.request.canonical_digest
                    != record.request.canonical_digest
                    or prior.canonical_content != record.canonical_content
                ):
                    raise ExecutionRequestIdempotencyConflict(
                        "Idempotency identity was used for different canonical content."
                    )
                return prior.request, False
            prior_identity = self._by_id.get(record.request.request_id)
            if prior_identity is not None:
                if prior_identity.canonical_content != record.canonical_content:
                    raise ExecutionRequestDigestMismatch(
                        "Canonical request identity conflicts with retained content."
                    )
                self._by_idempotency[
                    record.request.idempotency_identity
                ] = prior_identity
                return prior_identity.request, False
            self._by_id[record.request.request_id] = record
            self._by_idempotency[record.request.idempotency_identity] = record
            return record.request, True

    def get(self, request_id: str) -> ExecutionRequest | None:
        with self._lock:
            record = self._by_id.get(request_id)
            return record.request if record else None

    def record(self, request_id: str) -> ExecutionRequestRecord | None:
        with self._lock:
            return self._by_id.get(request_id)


class ExecutionRequestService:
    def __init__(
        self, repository: ExecutionRequestRepository | None = None
    ) -> None:
        self.repository = repository or InMemoryExecutionRequestRepository()

    def admit(
        self, draft: ExecutionRequestDraft, *, idempotency_key: str
    ) -> AdmissionResult:
        accepted_identity = idempotency_identity(
            organization_id=draft.organization_id,
            workload_context_id=draft.workload_context_id,
            submitted_key=idempotency_key,
        )
        request, canonical_content = build_execution_request(
            draft, accepted_idempotency_identity=accepted_identity
        )
        accepted, created = self.repository.admit(
            ExecutionRequestRecord(
                request=request,
                canonical_content=canonical_content,
            )
        )
        return AdmissionResult(
            outcome=(
                AdmissionOutcome.CREATED
                if created
                else AdmissionOutcome.EXISTING_EQUIVALENT
            ),
            request=accepted,
        )

    def get(
        self, request_id: str, *, organization_id: str
    ) -> ExecutionRequest | None:
        request = self.repository.get(request_id)
        if request is None or request.organization_id != organization_id:
            return None
        return request

    def reconstruct(
        self, request_id: str, *, organization_id: str
    ) -> ExecutionRequest:
        record = self.repository.record(request_id)
        if (
            record is None
            or record.request.organization_id != organization_id
        ):
            raise ExecutionRequestNotFound("Execution Request was not found.")
        reconstructed = reconstruct_execution_request(
            record.canonical_content,
            expected_digest=record.request.canonical_digest,
        )
        if reconstructed != record.request:
            raise ExecutionRequestDigestMismatch(
                "Reconstructed request differs from retained request."
            )
        return reconstructed
