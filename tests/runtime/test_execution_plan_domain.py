from dataclasses import FrozenInstanceError, replace

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanDraft,
    ExecutionPlanInvalid,
    ExecutionPlanRequestDigestInvalid,
    ExecutionPlanRuleVersionUnsupported,
    ExecutionPlanSchemaVersionUnsupported,
    PlanDependency,
    PlanReconstructionMetadata,
    PlanStep,
)
from app.runtime.execution_plan.serialization import build_execution_plan
from app.runtime.execution_request.domain import ExecutionRequest
from app.runtime.execution_request.service import ExecutionRequestService
from tests.runtime.test_execution_request_domain import draft as request_draft


def accepted_request(
    *,
    organization_id: str = "org-1",
    workload_context_id: str = "workload-1",
) -> tuple[ExecutionRequestService, ExecutionRequest]:
    service = ExecutionRequestService()
    request = service.admit(
        request_draft(
            organization_id=organization_id,
            workload_context_id=workload_context_id,
        ),
        idempotency_key="request-1",
    ).request
    return service, request


def plan_draft(
    request: ExecutionRequest | None = None,
    **overrides: object,
) -> ExecutionPlanDraft:
    if request is None:
        _, request = accepted_request()
    values: dict[str, object] = {
        "request": request,
        "structured_planned_work": (
            PlanStep(
                sequence=0,
                step_id="prepare",
                operation="demo.prepare",
                inputs={"format": "canonical", "options": {"count": 2}},
            ),
            PlanStep(
                sequence=1,
                step_id="produce",
                operation="demo.produce",
                inputs={"source_step": "prepare"},
            ),
        ),
        "capability_requirements": ("reports.write", "reports.prepare"),
        "resource_requirements": {
            "memory_mb": 256,
            "regions": ["us-central", "us-east"],
        },
        "declared_dependencies": (
            PlanDependency(
                predecessor_step_id="prepare",
                successor_step_id="produce",
            ),
        ),
        "normalized_plan_constraints": {
            "max_attempts": 1,
            "paper_only": True,
        },
        "planning_configuration_digest": "c" * 64,
        "policy_version_or_digest": "planning-policy.v1",
        "derivation_evidence": (
            "validation:request-1",
            "policy:planning-policy.v1",
        ),
        "reconstruction_metadata": PlanReconstructionMetadata(
            history_boundary="execution-request:1",
            input_artifact_hashes=(request.canonical_digest,),
        ),
    }
    values.update(overrides)
    return ExecutionPlanDraft(**values)  # type: ignore[arg-type]


def test_identical_canonical_inputs_produce_identical_plan() -> None:
    _, request = accepted_request()
    first, first_input, first_content = build_execution_plan(
        plan_draft(request)
    )
    second, second_input, second_content = build_execution_plan(
        plan_draft(request)
    )
    assert first == second
    assert first_input == second_input
    assert first_content == second_content
    assert first.plan_id == second.plan_id
    assert first.canonical_plan_digest == second.canonical_plan_digest


def test_map_and_set_like_input_order_do_not_change_plan() -> None:
    _, request = accepted_request()
    first = plan_draft(
        request,
        capability_requirements=("b", "a"),
        resource_requirements={"cpu": 1, "nested": {"b": 2, "a": 1}},
        derivation_evidence=("evidence:b", "evidence:a"),
    )
    second = plan_draft(
        request,
        capability_requirements=("a", "b"),
        resource_requirements={"nested": {"a": 1, "b": 2}, "cpu": 1},
        derivation_evidence=("evidence:a", "evidence:b"),
    )
    assert build_execution_plan(first) == build_execution_plan(second)


def test_semantic_step_order_changes_plan_identity() -> None:
    original = plan_draft()
    changed_steps = (
        replace(original.structured_planned_work[0], operation="demo.changed"),
        original.structured_planned_work[1],
    )
    changed = replace(original, structured_planned_work=changed_steps)
    assert build_execution_plan(original)[0].plan_id != build_execution_plan(
        changed
    )[0].plan_id


def test_plan_and_nested_values_are_immutable() -> None:
    plan, _, _ = build_execution_plan(plan_draft())
    with pytest.raises(FrozenInstanceError):
        plan.plan_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.resource_requirements["memory_mb"] = 512  # type: ignore[index]
    with pytest.raises(TypeError):
        inputs = plan.structured_planned_work[0].inputs
        inputs["format"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("field_name", "value", "error"),
    [
        (
            "plan_schema_version",
            "execution-plan.v2",
            ExecutionPlanSchemaVersionUnsupported,
        ),
        (
            "planning_rule_version",
            "execution-plan.rule.v2",
            ExecutionPlanRuleVersionUnsupported,
        ),
        ("resource_requirements", {"cpu": 1.5}, ExecutionPlanInvalid),
        ("normalized_plan_constraints", {"limit": float("nan")}, ExecutionPlanInvalid),
    ],
)
def test_unsupported_or_noncanonical_values_fail(
    field_name: str, value: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        plan_draft(**{field_name: value})


def test_steps_require_contiguous_order_and_valid_dependencies() -> None:
    invalid_steps = (
        PlanStep(sequence=1, step_id="late", operation="demo.late"),
    )
    with pytest.raises(ExecutionPlanInvalid):
        plan_draft(
            structured_planned_work=invalid_steps,
            declared_dependencies=(),
        )
    with pytest.raises(ExecutionPlanInvalid):
        plan_draft(
            declared_dependencies=(
                PlanDependency("missing", "produce"),
            )
        )
    with pytest.raises(ExecutionPlanInvalid):
        plan_draft(
            declared_dependencies=(
                PlanDependency("produce", "prepare"),
            )
        )
    with pytest.raises(ExecutionPlanInvalid):
        PlanStep(
            sequence="zero",  # type: ignore[arg-type]
            step_id="prepare",
            operation="demo.prepare",
        )


def test_plan_contract_contains_no_downstream_runtime_fields() -> None:
    field_names = set(
        build_execution_plan(plan_draft())[0].__dataclass_fields__
    )
    forbidden = {
        "worker_identity",
        "worker_readiness",
        "worker_selection",
        "selected_worker",
        "authorization_checkpoint",
        "dispatch_decision",
        "work_claim",
        "execution_lease",
        "queue_envelope",
        "attempt_state",
        "monitoring_state",
        "completion_state",
        "retry_state",
        "runtime_status",
    }
    assert field_names.isdisjoint(forbidden)


def test_invalid_request_digest_fails_before_plan_construction() -> None:
    _, request = accepted_request()
    forged = replace(request, canonical_digest="f" * 64)
    with pytest.raises(ExecutionPlanRequestDigestInvalid):
        build_execution_plan(plan_draft(forged))


def test_reconstruction_metadata_must_retain_request_digest() -> None:
    with pytest.raises(ExecutionPlanInvalid):
        plan_draft(
            reconstruction_metadata=PlanReconstructionMetadata(
                history_boundary="execution-request:1",
                input_artifact_hashes=("f" * 64,),
            )
        )
