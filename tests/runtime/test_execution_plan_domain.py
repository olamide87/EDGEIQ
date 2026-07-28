from dataclasses import FrozenInstanceError, fields, replace

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanInvalid,
    ExecutionPlanRuleVersionUnsupported,
    ExecutionPlanningInput,
    PlanningConfiguration,
    PlanningPolicy,
)
from app.runtime.execution_plan.serialization import build_execution_plan
from app.runtime.execution_plan.validation import (
    InMemoryRequestValidationEvidenceRepository,
    RequestValidationEvidence,
    ValidationOutcome,
    build_request_validation_evidence,
)
from app.runtime.execution_request.domain import ExecutionRequest
from app.runtime.execution_request.service import ExecutionRequestService
from tests.runtime.test_execution_request_domain import draft as request_draft


def accepted_context() -> tuple[
    ExecutionRequestService,
    ExecutionRequest,
    InMemoryRequestValidationEvidenceRepository,
    RequestValidationEvidence,
]:
    request_service = ExecutionRequestService()
    request = request_service.admit(
        request_draft(), idempotency_key="request-1"
    ).request
    evidence = build_request_validation_evidence(
        request_id=request.request_id,
        canonical_request_digest=request.canonical_digest,
        organization_id=request.organization_id,
        workload_context_id=request.workload_context_id,
        validation_policy_version="request-validation-policy.v1",
        outcome=ValidationOutcome.VALID,
        history_boundary="execution-request:1",
    )
    validations = InMemoryRequestValidationEvidenceRepository()
    validations.retain(evidence)
    return request_service, request, validations, evidence


def planning_input(
    request: ExecutionRequest,
    evidence: RequestValidationEvidence,
    **overrides: object,
) -> ExecutionPlanningInput:
    values: dict[str, object] = {
        "organization_id": request.organization_id,
        "workload_context_id": request.workload_context_id,
        "request_id": request.request_id,
        "validation_evidence_id": evidence.validation_evidence_id,
        "policy": PlanningPolicy(
            policy_version="planning-policy.v1",
            required_capabilities=("reports.write", "reports.prepare"),
            resource_requirements={"memory_mb": 256},
            plan_constraint_defaults={"paper_only": True},
        ),
        "configuration": PlanningConfiguration(
            configuration_version="planning-config.v1",
            work_step_id="work",
        ),
    }
    values.update(overrides)
    return ExecutionPlanningInput(**values)  # type: ignore[arg-type]


def build_default():
    _, request, _, evidence = accepted_context()
    return build_execution_plan(
        planning_input(request, evidence),
        request=request,
        validation=evidence,
    )


def test_registered_rule_deterministically_owns_plan_outputs() -> None:
    first = build_default()
    second = build_default()
    assert first == second
    plan = first[0]
    assert plan.structured_planned_work[0].operation == "demo.echo"
    assert plan.capability_requirements == (
        "reports.prepare",
        "reports.write",
    )
    assert plan.declared_dependencies == ()


def test_public_input_has_no_planner_owned_output_fields() -> None:
    input_fields = {field.name for field in fields(ExecutionPlanningInput)}
    forbidden = {
        "structured_planned_work",
        "capability_requirements",
        "resource_requirements",
        "declared_dependencies",
        "normalized_plan_constraints",
        "derivation_evidence",
    }
    assert input_fields.isdisjoint(forbidden)


def test_callers_cannot_override_planner_owned_outputs() -> None:
    _, request, _, evidence = accepted_context()
    with pytest.raises(TypeError):
        planning_input(
            request,
            evidence,
            structured_planned_work=("caller-authored",),
        )


def test_policy_map_order_does_not_change_plan() -> None:
    _, request, _, evidence = accepted_context()
    first = planning_input(
        request,
        evidence,
        policy=PlanningPolicy(
            policy_version="planning-policy.v1",
            required_capabilities=("b", "a"),
            resource_requirements={"b": 2, "a": 1},
        ),
    )
    second = planning_input(
        request,
        evidence,
        policy=PlanningPolicy(
            policy_version="planning-policy.v1",
            required_capabilities=("a", "b"),
            resource_requirements={"a": 1, "b": 2},
        ),
    )
    assert build_execution_plan(
        first, request=request, validation=evidence
    ) == build_execution_plan(
        second, request=request, validation=evidence
    )


@pytest.mark.parametrize("changed", ["policy", "configuration", "validation"])
def test_changing_authorized_input_changes_input_identity(changed: str) -> None:
    _, request, _, evidence = accepted_context()
    base = planning_input(request, evidence)
    changed_evidence = evidence
    if changed == "policy":
        candidate = replace(
            base,
            policy=PlanningPolicy(policy_version="planning-policy.v2"),
        )
    elif changed == "configuration":
        candidate = replace(
            base,
            configuration=PlanningConfiguration(
                configuration_version="planning-config.v2"
            ),
        )
    else:
        changed_evidence = build_request_validation_evidence(
            request_id=request.request_id,
            canonical_request_digest=request.canonical_digest,
            organization_id=request.organization_id,
            workload_context_id=request.workload_context_id,
            validation_policy_version="request-validation-policy.v2",
            outcome=ValidationOutcome.VALID,
            history_boundary="execution-request:2",
        )
        candidate = replace(
            base,
            validation_evidence_id=changed_evidence.validation_evidence_id,
        )
    original = build_execution_plan(
        base, request=request, validation=evidence
    )[0]
    changed_plan = build_execution_plan(
        candidate, request=request, validation=changed_evidence
    )[0]
    assert original.canonical_input_digest != changed_plan.canonical_input_digest
    assert original.plan_id != changed_plan.plan_id


def test_unsupported_rule_version_fails_closed() -> None:
    _, request, _, evidence = accepted_context()
    with pytest.raises(ExecutionPlanRuleVersionUnsupported):
        planning_input(
            request,
            evidence,
            planning_rule_version="execution-plan.rule.v2",
        )


def test_noncanonical_policy_value_fails() -> None:
    with pytest.raises(ExecutionPlanInvalid):
        PlanningPolicy(
            policy_version="planning-policy.v1",
            resource_requirements={"cpu": float("nan")},
        )


def test_plan_and_nested_content_are_immutable() -> None:
    plan = build_default()[0]
    with pytest.raises(FrozenInstanceError):
        plan.plan_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.resource_requirements["memory_mb"] = 512  # type: ignore[index]
    with pytest.raises(TypeError):
        plan.structured_planned_work[0].inputs["request_id"] = "changed"  # type: ignore[index]


def test_plan_contract_contains_no_downstream_fields() -> None:
    field_names = {field.name for field in fields(build_default()[0])}
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
