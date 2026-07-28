from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from app.runtime.execution_plan.domain import (
    ExecutionPlanRuleVersionUnsupported,
    PlanDependency,
    PlanStep,
    PlanningConfiguration,
    PlanningPolicy,
    SUPPORTED_PLANNING_RULE_VERSION,
    immutable_mapping,
)
from app.runtime.execution_plan.validation import RequestValidationEvidence
from app.runtime.execution_request.domain import ExecutionRequest


@dataclass(frozen=True)
class PlanRuleResult:
    structured_planned_work: tuple[PlanStep, ...]
    capability_requirements: tuple[str, ...]
    resource_requirements: Mapping[str, object]
    declared_dependencies: tuple[PlanDependency, ...]
    normalized_plan_constraints: Mapping[str, object]
    derivation_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        steps = tuple(self.structured_planned_work)
        if not steps or any(not isinstance(step, PlanStep) for step in steps):
            raise TypeError("Planning rules must produce PlanStep values.")
        if tuple(step.sequence for step in steps) != tuple(range(len(steps))):
            raise ValueError(
                "Planning-rule steps must have contiguous zero-based sequence."
            )
        step_ids = tuple(step.step_id for step in steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Planning-rule step identifiers must be unique.")
        dependencies = tuple(sorted(self.declared_dependencies))
        if any(
            not isinstance(dependency, PlanDependency)
            for dependency in dependencies
        ):
            raise TypeError(
                "Planning rules must produce PlanDependency values."
            )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("Planning-rule dependencies must be unique.")
        step_positions = {
            step_id: position for position, step_id in enumerate(step_ids)
        }
        for dependency in dependencies:
            predecessor = step_positions.get(
                dependency.predecessor_step_id
            )
            successor = step_positions.get(dependency.successor_step_id)
            if (
                predecessor is None
                or successor is None
                or predecessor >= successor
            ):
                raise ValueError(
                    "Planning-rule dependencies must point forward between "
                    "retained steps."
                )
        capabilities = tuple(sorted(self.capability_requirements))
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("Planning-rule capabilities must be unique.")
        derivation = tuple(sorted(self.derivation_evidence))
        if not derivation or len(derivation) != len(set(derivation)):
            raise ValueError(
                "Planning-rule derivation evidence must be non-empty and unique."
            )
        object.__setattr__(self, "structured_planned_work", steps)
        object.__setattr__(self, "capability_requirements", capabilities)
        object.__setattr__(
            self,
            "resource_requirements",
            immutable_mapping(self.resource_requirements),
        )
        object.__setattr__(self, "declared_dependencies", dependencies)
        object.__setattr__(
            self,
            "normalized_plan_constraints",
            immutable_mapping(self.normalized_plan_constraints),
        )
        object.__setattr__(self, "derivation_evidence", derivation)


def _payload_digest(request: ExecutionRequest) -> str:
    reference = request.immutable_payload_reference
    return (
        reference.canonical_digest
        if reference is not None
        else request.canonical_digest
    )


def deterministic_rule_v1(
    request: ExecutionRequest,
    validation: RequestValidationEvidence,
    policy: PlanningPolicy,
    configuration: PlanningConfiguration,
) -> PlanRuleResult:
    step = PlanStep(
        sequence=0,
        step_id=configuration.work_step_id,
        operation=request.requested_work_type,
        inputs={
            "payload_digest": _payload_digest(request),
            "request_id": request.request_id,
        },
    )
    constraints = immutable_mapping(
        {
            "policy_defaults": policy.plan_constraint_defaults,
            "request_constraints": request.request_constraints,
        }
    )
    return PlanRuleResult(
        structured_planned_work=(step,),
        capability_requirements=policy.required_capabilities,
        resource_requirements=policy.resource_requirements,
        declared_dependencies=(),
        normalized_plan_constraints=constraints,
        derivation_evidence=tuple(
            sorted(
                (
                    request.request_id,
                    request.canonical_digest,
                    validation.validation_evidence_id,
                    validation.canonical_digest,
                )
            )
        ),
    )


PlanningRule = Callable[
    [
        ExecutionRequest,
        RequestValidationEvidence,
        PlanningPolicy,
        PlanningConfiguration,
    ],
    PlanRuleResult,
]

PLANNING_RULES: Mapping[str, PlanningRule] = MappingProxyType(
    {SUPPORTED_PLANNING_RULE_VERSION: deterministic_rule_v1}
)


def planning_rule(version: str) -> PlanningRule:
    try:
        return PLANNING_RULES[version]
    except KeyError as exc:
        raise ExecutionPlanRuleVersionUnsupported(
            f"Unsupported planning-rule version: {version}."
        ) from exc
