from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanDigestMismatch,
    ExecutionPlanIdempotencyConflict,
    ExecutionPlanIdentityMismatch,
    ExecutionPlanOrganizationMismatch,
    ExecutionPlanPersistenceFailure,
    ExecutionPlanRequestInvalid,
    ExecutionPlanVersionConflict,
    PlanDerivationOutcome,
)
from app.runtime.execution_plan.ports import ExecutionPlanRecord
from app.runtime.execution_plan.serialization import (
    build_execution_plan,
    plan_idempotency_identity,
)
from app.runtime.execution_plan.service import (
    ExecutionPlanService,
    InMemoryExecutionPlanRepository,
)
from app.runtime.execution_request.service import ExecutionRequestService
from tests.runtime.test_execution_plan_domain import (
    accepted_request,
    plan_draft,
)


def planning_service(
) -> tuple[ExecutionRequestService, ExecutionPlanService]:
    request_service, _ = accepted_request()
    return (
        request_service,
        ExecutionPlanService(
            accepted_requests=request_service.repository
        ),
    )


def plan_record(
    *,
    key: str = "plan-1",
    configuration_digest: str = "c" * 64,
) -> tuple[ExecutionRequestService, ExecutionPlanRecord]:
    request_service, request = accepted_request()
    plan, canonical_input, canonical_plan = build_execution_plan(
        plan_draft(
            request,
            planning_configuration_digest=configuration_digest,
        )
    )
    return (
        request_service,
        ExecutionPlanRecord(
            plan=plan,
            request=request,
            canonical_input_content=canonical_input,
            canonical_plan_content=canonical_plan,
            idempotency_identity=plan_idempotency_identity(
                organization_id=request.organization_id,
                workload_context_id=request.workload_context_id,
                request_id=request.request_id,
                submitted_key=key,
            ),
        ),
    )


class FailingCommitRepository(InMemoryExecutionPlanRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_commit = False

    def _commit_state(self, state) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise ExecutionPlanPersistenceFailure(
                "injected atomic commit failure"
            )
        super()._commit_state(state)


def test_valid_plan_is_published_as_one_complete_snapshot() -> None:
    request_service, request = accepted_request()
    repository = InMemoryExecutionPlanRepository()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=repository,
    )
    result = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    )
    assert result.outcome is PlanDerivationOutcome.CREATED
    assert result.stream_version == 1
    assert service.get(
        result.plan.plan_id, organization_id="org-1"
    ) == result.plan
    assert service.current(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) == result.plan
    record = repository.record(result.plan.plan_id)
    assert record is not None
    assert record.canonical_input_content
    assert record.canonical_plan_content


def test_unretained_request_fails_before_publication() -> None:
    _, request = accepted_request()
    empty_source = ExecutionRequestService()
    repository = InMemoryExecutionPlanRepository()
    service = ExecutionPlanService(
        accepted_requests=empty_source.repository,
        repository=repository,
    )
    with pytest.raises(ExecutionPlanRequestInvalid):
        service.derive(
            plan_draft(request),
            expected_version=0,
            idempotency_key="plan-1",
        )
    assert repository.get("missing") is None


def test_equivalent_retry_returns_existing_without_duplicate_history() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    first = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    )
    second = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
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


def test_conflicting_idempotency_reuse_preserves_accepted_plan() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    accepted = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    )
    with pytest.raises(ExecutionPlanIdempotencyConflict):
        service.derive(
            plan_draft(
                request, planning_configuration_digest="d" * 64
            ),
            expected_version=1,
            idempotency_key="plan-1",
        )
    assert service.get(
        accepted.plan.plan_id, organization_id="org-1"
    ) == accepted.plan


def test_stale_writer_appends_nothing() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    )
    with pytest.raises(ExecutionPlanVersionConflict):
        service.derive(
            plan_draft(
                request, planning_configuration_digest="d" * 64
            ),
            expected_version=0,
            idempotency_key="plan-2",
        )
    assert len(
        service.history(
            organization_id="org-1",
            workload_context_id="workload-1",
            request_id=request.request_id,
        )
    ) == 1


def test_concurrent_equivalent_derivations_converge() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )

    def derive() -> tuple[PlanDerivationOutcome, str]:
        result = service.derive(
            plan_draft(request),
            expected_version=0,
            idempotency_key="plan-1",
        )
        return result.outcome, result.plan.plan_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: derive(), range(20)))
    assert sum(
        outcome is PlanDerivationOutcome.CREATED
        for outcome, _ in results
    ) == 1
    assert len({plan_id for _, plan_id in results}) == 1


def test_competing_expected_version_writers_have_one_winner() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )

    def derive(index: int) -> str:
        try:
            return service.derive(
                plan_draft(
                    request,
                    planning_configuration_digest=f"{index + 1:064x}",
                ),
                expected_version=0,
                idempotency_key=f"plan-{index}",
            ).outcome.value
        except ExecutionPlanVersionConflict:
            return "VersionConflict"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(derive, range(8)))
    assert outcomes.count("Created") == 1
    assert outcomes.count("VersionConflict") == 7


def test_failure_before_commit_leaves_no_record_or_pointer() -> None:
    request_service, request = accepted_request()
    repository = FailingCommitRepository()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=repository,
    )
    repository.fail_next_commit = True
    with pytest.raises(ExecutionPlanPersistenceFailure):
        service.derive(
            plan_draft(request),
            expected_version=0,
            idempotency_key="plan-1",
        )
    assert service.current(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) is None
    assert service.history(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    ) == ()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda record: replace(
                record,
                canonical_input_content=record.canonical_input_content + b" ",
            ),
            ExecutionPlanDigestMismatch,
        ),
        (
            lambda record: replace(
                record,
                plan=replace(record.plan, plan_id="f" * 64),
            ),
            ExecutionPlanIdentityMismatch,
        ),
        (
            lambda record: replace(
                record,
                plan=replace(record.plan, organization_id="org-2"),
            ),
            ExecutionPlanOrganizationMismatch,
        ),
    ],
)
def test_invalid_candidate_is_rejected_without_mutation(
    mutation, error: type[Exception]
) -> None:
    _, record = plan_record()
    repository = InMemoryExecutionPlanRepository()
    with pytest.raises(error):
        repository.append(mutation(record), expected_version=0)
    assert repository.get(record.plan.plan_id) is None


def test_returned_plan_cannot_mutate_repository_snapshot() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    accepted = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    ).plan
    with pytest.raises(TypeError):
        constraints = accepted.normalized_plan_constraints
        constraints["paper_only"] = False  # type: ignore[index]
    assert service.get(
        accepted.plan_id, organization_id="org-1"
    ) == accepted


def test_later_plan_preserves_prior_history() -> None:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    first = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    ).plan
    second = service.derive(
        plan_draft(request, planning_configuration_digest="d" * 64),
        expected_version=1,
        idempotency_key="plan-2",
    ).plan
    history = service.history(
        organization_id="org-1",
        workload_context_id="workload-1",
        request_id=request.request_id,
    )
    assert history == (first, second)
    assert history[0] == first
