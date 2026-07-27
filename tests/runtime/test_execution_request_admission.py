from concurrent.futures import ThreadPoolExecutor

import pytest

from app.runtime.execution_request.domain import (
    AdmissionOutcome,
    ExecutionRequestDraft,
    ExecutionRequestIdempotencyConflict,
    ExecutionRequestInvalid,
)
from app.runtime.execution_request.service import (
    ExecutionRequestService,
    InMemoryExecutionRequestRepository,
)
from tests.runtime.test_execution_request_domain import draft


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
    assert len(repository._by_id) == 1
    assert len(repository._by_idempotency) == 1


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
    assert repository._by_id == {}
    assert repository._by_idempotency == {}


def test_empty_idempotency_key_persists_no_partial_state() -> None:
    repository = InMemoryExecutionRequestRepository()
    service = ExecutionRequestService(repository)
    with pytest.raises(ExecutionRequestInvalid):
        service.admit(draft(), idempotency_key="")
    assert repository._by_id == {}
    assert repository._by_idempotency == {}


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
