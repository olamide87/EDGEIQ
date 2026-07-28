from concurrent.futures import ThreadPoolExecutor

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanIdempotencyConflict,
    ExecutionPlanPersistenceFailure,
    ExecutionPlanRequestInvalid,
    ExecutionPlanVersionConflict,
    PlanDerivationOutcome,
    PlanningConfiguration,
)
from app.runtime.execution_plan.service import (
    ExecutionPlanService,
    InMemoryExecutionPlanRepository,
)
from app.runtime.execution_plan.validation import (
    InMemoryRequestValidationEvidenceRepository,
    ValidationOutcome,
    build_request_validation_evidence,
)
from app.runtime.execution_request.service import ExecutionRequestService
from tests.runtime.test_execution_plan_domain import (
    accepted_context,
    planning_input,
)


class FailingRepository(InMemoryExecutionPlanRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail = False

    def _commit_state(self, state) -> None:
        if self.fail:
            self.fail = False
            raise ExecutionPlanPersistenceFailure("injected failure")
        super()._commit_state(state)


def context(repository=None):
    requests, request, validations, evidence = accepted_context()
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
        repository=repository,
    )
    return service, request, evidence


def test_valid_plan_is_atomically_published() -> None:
    service, request, evidence = context()
    result = service.derive(
        planning_input(request, evidence),
        expected_version=0,
        idempotency_key="plan-1",
    )
    assert result.outcome is PlanDerivationOutcome.CREATED
    assert result.stream_version == 1
    assert service.current(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) == result.plan


def test_missing_validation_evidence_fails_without_publication() -> None:
    requests, request, _, evidence = accepted_context()
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=InMemoryRequestValidationEvidenceRepository(),
    )
    with pytest.raises(ExecutionPlanRequestInvalid):
        service.derive(
            planning_input(request, evidence),
            expected_version=0,
            idempotency_key="plan-1",
        )


def test_unretained_request_fails_without_publication() -> None:
    _, request, validations, evidence = accepted_context()
    service = ExecutionPlanService(
        accepted_requests=ExecutionRequestService().repository,
        validation_evidence=validations,
    )
    with pytest.raises(ExecutionPlanRequestInvalid):
        service.derive(
            planning_input(request, evidence),
            expected_version=0,
            idempotency_key="plan-1",
        )


def test_validation_source_cannot_substitute_different_evidence() -> None:
    requests, request, _, evidence = accepted_context()

    class SubstitutingSource:
        def get(self, validation_evidence_id):
            return evidence

    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=SubstitutingSource(),
    )
    substituted = planning_input(
        request,
        evidence,
        validation_evidence_id="different-evidence",
    )
    with pytest.raises(ExecutionPlanRequestInvalid):
        service.derive(
            substituted,
            expected_version=0,
            idempotency_key="plan-1",
        )


@pytest.mark.parametrize("defect", ["request", "scope", "outcome", "digest"])
def test_invalid_validation_evidence_fails_closed(defect: str) -> None:
    requests, request, _, _ = accepted_context()
    kwargs = {
        "request_id": request.request_id,
        "canonical_request_digest": request.canonical_digest,
        "organization_id": request.organization_id,
        "workload_context_id": request.workload_context_id,
        "validation_policy_version": "validation.v1",
        "outcome": ValidationOutcome.VALID,
        "history_boundary": "request:1",
    }
    if defect == "request":
        kwargs["request_id"] = "f" * 64
    elif defect == "scope":
        kwargs["organization_id"] = "org-2"
    elif defect == "outcome":
        kwargs["outcome"] = ValidationOutcome.INVALID
    evidence = build_request_validation_evidence(**kwargs)
    if defect == "digest":
        from dataclasses import replace

        evidence = replace(evidence, canonical_digest="f" * 64)
    validations = InMemoryRequestValidationEvidenceRepository()
    if defect == "digest":
        with pytest.raises(ExecutionPlanRequestInvalid):
            validations.retain(evidence)
        return
    validations.retain(evidence)
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
    )
    with pytest.raises(ExecutionPlanRequestInvalid):
        service.derive(
            planning_input(request, evidence),
            expected_version=0,
            idempotency_key="plan-1",
        )


def test_equivalent_retry_returns_existing_without_duplicate_history() -> None:
    service, request, evidence = context()
    plan_input = planning_input(request, evidence)
    first = service.derive(
        plan_input, expected_version=0, idempotency_key="plan-1"
    )
    second = service.derive(
        plan_input, expected_version=0, idempotency_key="plan-1"
    )
    assert second.outcome is PlanDerivationOutcome.EXISTING_EQUIVALENT
    assert second.plan == first.plan
    assert len(
        service.history(
            organization_id="org-1",
            workload_context_id="workload-1",
            request_id=request.request_id,
        )
    ) == 1


def test_conflicting_idempotency_and_stale_writer_fail() -> None:
    service, request, evidence = context()
    service.derive(
        planning_input(request, evidence),
        expected_version=0,
        idempotency_key="plan-1",
    )
    changed = planning_input(
        request,
        evidence,
        configuration=PlanningConfiguration(
            configuration_version="planning-config.v2"
        ),
    )
    with pytest.raises(ExecutionPlanIdempotencyConflict):
        service.derive(
            changed, expected_version=1, idempotency_key="plan-1"
        )
    with pytest.raises(ExecutionPlanVersionConflict):
        service.derive(
            changed, expected_version=0, idempotency_key="plan-2"
        )


def test_concurrent_equivalent_derivations_converge() -> None:
    service, request, evidence = context()
    plan_input = planning_input(request, evidence)

    def derive(_):
        return service.derive(
            plan_input, expected_version=0, idempotency_key="plan-1"
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(derive, range(20)))
    assert sum(
        result.outcome is PlanDerivationOutcome.CREATED for result in results
    ) == 1
    assert len({result.plan.plan_id for result in results}) == 1


def test_atomic_failure_leaves_no_history_or_pointer() -> None:
    repository = FailingRepository()
    service, request, evidence = context(repository)
    repository.fail = True
    with pytest.raises(ExecutionPlanPersistenceFailure):
        service.derive(
            planning_input(request, evidence),
            expected_version=0,
            idempotency_key="plan-1",
        )
    assert service.history(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) == ()
    assert service.current(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) is None


def test_later_plan_preserves_prior_history() -> None:
    service, request, evidence = context()
    first = service.derive(
        planning_input(request, evidence),
        expected_version=0,
        idempotency_key="plan-1",
    )
    second = service.derive(
        planning_input(
            request,
            evidence,
            configuration=PlanningConfiguration(
                configuration_version="planning-config.v2"
            ),
        ),
        expected_version=1,
        idempotency_key="plan-2",
    )
    history = service.history(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    )
    assert history == (first.plan, second.plan)
    assert history[0] == first.plan
