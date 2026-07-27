import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.runtime.execution_request.domain import (
    AdmissionOutcome,
    ExecutionRequestDigestMismatch,
    ExecutionRequestDraft,
    ExecutionRequestIdempotencyConflict,
    ExecutionRequestInvalid,
    ExecutionRequestReconstructionFailed,
    ExecutionRequestSchemaVersionUnsupported,
)
from app.runtime.execution_request.ports import ExecutionRequestRecord
from app.runtime.execution_request.serialization import (
    build_execution_request,
    idempotency_identity,
)
from app.runtime.execution_request.service import (
    ExecutionRequestService,
    InMemoryExecutionRequestRepository,
)
from tests.runtime.test_execution_request_domain import draft


def admission_record(
    request_draft: ExecutionRequestDraft | None = None,
    *,
    key: str = "request-1",
) -> ExecutionRequestRecord:
    request_draft = request_draft or draft()
    identity = idempotency_identity(
        organization_id=request_draft.organization_id,
        workload_context_id=request_draft.workload_context_id,
        submitted_key=key,
    )
    request, content = build_execution_request(
        request_draft, accepted_idempotency_identity=identity
    )
    return ExecutionRequestRecord(request=request, canonical_content=content)


def assert_rejected_without_state(
    record: ExecutionRequestRecord, error: type[Exception]
) -> None:
    repository = InMemoryExecutionRequestRepository()
    with pytest.raises(error):
        repository.admit(record)
    assert repository.get(record.request.request_id) is None
    accepted, created = repository.admit(admission_record())
    assert created
    assert accepted == admission_record().request


class FailingCommitRepository(InMemoryExecutionRequestRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_commit = False

    def _commit_state(self, state) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("injected atomic commit failure")
        super()._commit_state(state)


def test_new_valid_request_is_created_once() -> None:
    service = ExecutionRequestService()
    result = service.admit(draft(), idempotency_key="request-1")
    assert result.outcome is AdmissionOutcome.CREATED
    assert (
        service.get(result.request.request_id, organization_id="org-1")
        == result.request
    )


def test_equivalent_idempotent_admission_returns_existing_request() -> None:
    service = ExecutionRequestService()
    first = service.admit(draft(), idempotency_key="request-1")
    second = service.admit(draft(), idempotency_key="request-1")
    assert second.outcome is AdmissionOutcome.EXISTING_EQUIVALENT
    assert second.request == first.request


def test_idempotency_key_reuse_with_different_content_conflicts() -> None:
    service = ExecutionRequestService()
    accepted = service.admit(draft(), idempotency_key="request-1")
    with pytest.raises(ExecutionRequestIdempotencyConflict):
        service.admit(
            draft(immutable_payload={"message": "different"}),
            idempotency_key="request-1",
        )
    assert (
        service.get(accepted.request.request_id, organization_id="org-1")
        == accepted.request
    )


def test_read_isolation_does_not_expose_cross_organization_request() -> None:
    service = ExecutionRequestService()
    accepted = service.admit(draft(), idempotency_key="request-1").request
    assert service.get(accepted.request_id, organization_id="org-2") is None


def test_concurrent_equivalent_admissions_converge_on_one_request() -> None:
    repository = InMemoryExecutionRequestRepository()
    service = ExecutionRequestService(repository)

    def admit() -> tuple[AdmissionOutcome, str]:
        result = service.admit(draft(), idempotency_key="request-1")
        return result.outcome, result.request.request_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: admit(), range(20)))
    assert sum(outcome is AdmissionOutcome.CREATED for outcome, _ in outcomes) == 1
    assert len({request_id for _, request_id in outcomes}) == 1
    request_id = outcomes[0][1]
    assert repository.get(request_id) is not None
    _, created = repository.admit(admission_record())
    assert not created


def test_failed_validation_persists_no_partial_state() -> None:
    repository = InMemoryExecutionRequestRepository()
    service = ExecutionRequestService(repository)
    with pytest.raises(ExecutionRequestInvalid):
        service.admit(
            ExecutionRequestDraft(
                organization_id="org-1",
                workload_context_id="workload-1",
                requested_work_type="demo.echo",
                immutable_payload={"unsupported_float": 1.5},
                provenance={"source": "unit-test"},
            ),
            idempotency_key="request-1",
        )
    result = service.admit(draft(), idempotency_key="request-1")
    assert result.outcome is AdmissionOutcome.CREATED


def test_empty_idempotency_key_persists_no_partial_state() -> None:
    repository = InMemoryExecutionRequestRepository()
    service = ExecutionRequestService(repository)
    with pytest.raises(ExecutionRequestInvalid):
        service.admit(draft(), idempotency_key="")
    result = service.admit(draft(), idempotency_key="request-1")
    assert result.outcome is AdmissionOutcome.CREATED


def test_admission_has_no_external_side_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("External network access is forbidden during admission.")

    monkeypatch.setattr("socket.create_connection", forbidden)
    result = ExecutionRequestService().admit(
        draft(), idempotency_key="request-1"
    )
    assert result.outcome is AdmissionOutcome.CREATED


def test_request_contract_contains_no_downstream_runtime_state() -> None:
    field_names = set(ExecutionRequestDraft.__dataclass_fields__)
    forbidden = {
        "worker",
        "readiness",
        "selection",
        "dispatch",
        "claim",
        "lease",
        "execution",
        "retry",
        "monitoring",
        "completion",
    }
    assert field_names.isdisjoint(forbidden)


def test_repository_rejects_forged_empty_canonical_content() -> None:
    valid = admission_record()
    assert_rejected_without_state(
        replace(valid, canonical_content=b"{}"),
        ExecutionRequestDigestMismatch,
    )


def test_repository_rejects_content_for_different_request() -> None:
    first = admission_record()
    second = admission_record(
        draft(immutable_payload={"message": "different"})
    )
    assert_rejected_without_state(
        replace(first, canonical_content=second.canonical_content),
        ExecutionRequestDigestMismatch,
    )


def test_repository_rejects_canonical_digest_mismatch() -> None:
    valid = admission_record()
    forged = replace(
        valid,
        request=replace(valid.request, canonical_digest="f" * 64),
    )
    assert_rejected_without_state(forged, ExecutionRequestDigestMismatch)


def test_repository_rejects_request_id_mismatch() -> None:
    valid = admission_record()
    forged = replace(
        valid,
        request=replace(valid.request, request_id="f" * 64),
    )
    assert_rejected_without_state(forged, ExecutionRequestDigestMismatch)


def test_repository_rejects_idempotency_identity_mismatch() -> None:
    valid = admission_record()
    forged = replace(
        valid,
        request=replace(valid.request, idempotency_identity="f" * 64),
    )
    assert_rejected_without_state(forged, ExecutionRequestDigestMismatch)


def test_repository_rejects_unsupported_retained_schema() -> None:
    valid = admission_record()
    changed = valid.canonical_content.replace(
        b"execution-request.v1", b"execution-request.v2"
    )
    digest = hashlib.sha256(
        b"edgeiq.execution-request.v1\n" + changed
    ).hexdigest()
    forged = replace(
        valid,
        request=replace(valid.request, canonical_digest=digest),
        canonical_content=changed,
    )
    assert_rejected_without_state(
        forged, ExecutionRequestSchemaVersionUnsupported
    )


@pytest.mark.parametrize("missing_field", ["provenance", "request_constraints"])
def test_repository_rejects_missing_required_canonical_field(
    missing_field: str,
) -> None:
    valid = admission_record()
    document = json.loads(valid.canonical_content)
    document.pop(missing_field)
    changed = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"edgeiq.execution-request.v1\n" + changed
    ).hexdigest()
    forged = replace(
        valid,
        request=replace(valid.request, canonical_digest=digest),
        canonical_content=changed,
    )
    assert_rejected_without_state(
        forged, ExecutionRequestReconstructionFailed
    )


def test_failure_during_atomic_commit_leaves_no_partial_state() -> None:
    repository = FailingCommitRepository()
    valid = admission_record()
    repository.fail_next_commit = True
    with pytest.raises(RuntimeError, match="injected atomic commit failure"):
        repository.admit(valid)
    assert repository.get(valid.request.request_id) is None
    accepted, created = repository.admit(valid)
    assert created
    assert accepted == valid.request


def test_failed_atomic_commit_preserves_previously_accepted_state() -> None:
    repository = FailingCommitRepository()
    first = admission_record()
    second = admission_record(
        draft(immutable_payload={"message": "second"}), key="request-2"
    )
    repository.admit(first)
    repository.fail_next_commit = True
    with pytest.raises(RuntimeError, match="injected atomic commit failure"):
        repository.admit(second)
    assert repository.get(first.request.request_id) == first.request
    assert repository.get(second.request.request_id) is None
    accepted, created = repository.admit(second)
    assert created
    assert accepted == second.request
