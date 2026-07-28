import hashlib
import json
from typing import Any, Mapping

from app.runtime.execution_plan.domain import (
    ExecutionPlan,
    ExecutionPlanDigestMismatch,
    ExecutionPlanIdentityMismatch,
    ExecutionPlanInvalid,
    ExecutionPlanPolicyConfigurationMismatch,
    ExecutionPlanReconstructionFailed,
    ExecutionPlanReplayDiverged,
    ExecutionPlanRequestDigestInvalid,
    ExecutionPlanRequestInvalid,
    ExecutionPlanSchemaVersionUnsupported,
    ExecutionPlanningInput,
    PlanReconstructionMetadata,
    PlanningConfiguration,
    PlanningPolicy,
    SUPPORTED_PLAN_SCHEMA_VERSION,
    SUPPORTED_PLANNER_VERSION,
)
from app.runtime.execution_plan.rules import planning_rule
from app.runtime.execution_plan.validation import (
    RequestValidationEvidence,
    ValidationOutcome,
    build_request_validation_evidence,
    validate_request_validation_evidence,
)
from app.runtime.execution_request.domain import (
    ExecutionRequest,
    ExecutionRequestDraft,
    ExecutionRequestInvalid,
)
from app.runtime.execution_request.serialization import (
    SERIALIZATION_VERSION,
    build_execution_request,
    canonical_json,
)


PLAN_INPUT_DIGEST_NAMESPACE = "edgeiq.execution-plan-input.v1"
PLAN_DIGEST_NAMESPACE = "edgeiq.execution-plan.v1"
PLAN_ID_NAMESPACE = "edgeiq.execution-plan-id.v1"
PLAN_IDEMPOTENCY_NAMESPACE = "edgeiq.execution-plan-idempotency.v1"
POLICY_DIGEST_NAMESPACE = "edgeiq.execution-plan-policy.v1"
CONFIGURATION_DIGEST_NAMESPACE = "edgeiq.execution-plan-configuration.v1"


def _sha256(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode() + b"\n" + content).hexdigest()


def validate_accepted_request(request: ExecutionRequest) -> bytes:
    try:
        draft = ExecutionRequestDraft(
            organization_id=request.organization_id,
            workload_context_id=request.workload_context_id,
            requested_work_type=request.requested_work_type,
            immutable_payload=request.immutable_payload,
            immutable_payload_reference=request.immutable_payload_reference,
            request_constraints=request.request_constraints,
            provenance=request.provenance,
            request_schema_version=request.request_schema_version,
        )
        rebuilt, content = build_execution_request(
            draft,
            accepted_idempotency_identity=request.idempotency_identity,
        )
    except ExecutionRequestInvalid as exc:
        raise ExecutionPlanRequestInvalid(
            "Accepted Execution Request evidence is invalid."
        ) from exc
    if rebuilt.canonical_digest != request.canonical_digest:
        raise ExecutionPlanRequestDigestInvalid(
            "Accepted Execution Request digest is invalid."
        )
    if rebuilt != request:
        raise ExecutionPlanRequestInvalid(
            "Accepted Execution Request failed reconstruction."
        )
    return content


def policy_document(policy: PlanningPolicy) -> dict[str, Any]:
    return {
        "plan_constraint_defaults": policy.plan_constraint_defaults,
        "policy_version": policy.policy_version,
        "required_capabilities": policy.required_capabilities,
        "resource_requirements": policy.resource_requirements,
    }


def configuration_document(
    configuration: PlanningConfiguration,
) -> dict[str, str]:
    return {
        "configuration_version": configuration.configuration_version,
        "work_step_id": configuration.work_step_id,
    }


def policy_digest(policy: PlanningPolicy) -> str:
    return _sha256(
        POLICY_DIGEST_NAMESPACE, canonical_json(policy_document(policy)).encode()
    )


def configuration_digest(configuration: PlanningConfiguration) -> str:
    return _sha256(
        CONFIGURATION_DIGEST_NAMESPACE,
        canonical_json(configuration_document(configuration)).encode(),
    )


def plan_idempotency_identity(
    *,
    organization_id: str,
    workload_context_id: str,
    request_id: str,
    submitted_key: str,
) -> str:
    if not submitted_key:
        raise ExecutionPlanInvalid("An idempotency key is required.")
    content = canonical_json(
        {
            "operation": "derive-execution-plan",
            "organization_id": organization_id,
            "request_id": request_id,
            "submitted_key": submitted_key,
            "workload_context_id": workload_context_id,
        }
    ).encode()
    return _sha256(PLAN_IDEMPOTENCY_NAMESPACE, content)


def validation_document(
    evidence: RequestValidationEvidence,
) -> dict[str, Any]:
    return {
        "canonical_digest": evidence.canonical_digest,
        "canonical_request_digest": evidence.canonical_request_digest,
        "findings": evidence.findings,
        "history_boundary": evidence.history_boundary,
        "organization_id": evidence.organization_id,
        "outcome": evidence.outcome.value,
        "request_id": evidence.request_id,
        "schema_version": evidence.schema_version,
        "validation_evidence_id": evidence.validation_evidence_id,
        "validation_policy_version": evidence.validation_policy_version,
        "workload_context_id": evidence.workload_context_id,
    }


def canonical_plan_input_document(
    planning_input: ExecutionPlanningInput,
    *,
    request: ExecutionRequest,
    validation: RequestValidationEvidence,
) -> dict[str, Any]:
    return {
        "canonical_request_digest": request.canonical_digest,
        "configuration": configuration_document(planning_input.configuration),
        "configuration_digest": configuration_digest(
            planning_input.configuration
        ),
        "organization_id": planning_input.organization_id,
        "plan_schema_version": planning_input.plan_schema_version,
        "planning_rule_version": planning_input.planning_rule_version,
        "policy": policy_document(planning_input.policy),
        "policy_digest": policy_digest(planning_input.policy),
        "request_id": planning_input.request_id,
        "request_schema_version": request.request_schema_version,
        "serialization_version": SERIALIZATION_VERSION,
        "validation_evidence": validation_document(validation),
        "workload_context_id": planning_input.workload_context_id,
    }


def _step_document(step: Any) -> dict[str, Any]:
    return {
        "inputs": step.inputs,
        "operation": step.operation,
        "sequence": step.sequence,
        "step_id": step.step_id,
    }


def _dependency_document(dependency: Any) -> dict[str, str]:
    return {
        "predecessor_step_id": dependency.predecessor_step_id,
        "successor_step_id": dependency.successor_step_id,
    }


def _plan_id(input_digest: str, planning_input: ExecutionPlanningInput) -> str:
    return _sha256(
        PLAN_ID_NAMESPACE,
        canonical_json(
            {
                "canonical_input_digest": input_digest,
                "plan_schema_version": planning_input.plan_schema_version,
                "planning_rule_version": planning_input.planning_rule_version,
            }
        ).encode(),
    )


def build_execution_plan(
    planning_input: ExecutionPlanningInput,
    *,
    request: ExecutionRequest,
    validation: RequestValidationEvidence,
) -> tuple[ExecutionPlan, bytes, bytes]:
    validate_accepted_request(request)
    validate_request_validation_evidence(validation)
    if (
        request.request_id != planning_input.request_id
        or request.organization_id != planning_input.organization_id
        or request.workload_context_id != planning_input.workload_context_id
    ):
        raise ExecutionPlanRequestInvalid(
            "Planning input and accepted request scope differ."
        )
    if (
        validation.validation_evidence_id
        != planning_input.validation_evidence_id
        or validation.request_id != request.request_id
        or validation.canonical_request_digest != request.canonical_digest
        or validation.organization_id != request.organization_id
        or validation.workload_context_id != request.workload_context_id
    ):
        raise ExecutionPlanRequestInvalid(
            "Request Validation evidence does not apply to the request."
        )
    if validation.outcome is not ValidationOutcome.VALID:
        raise ExecutionPlanRequestInvalid(
            "Execution Request is not valid for planning."
        )
    rule = planning_rule(planning_input.planning_rule_version)
    output = rule(
        request,
        validation,
        planning_input.policy,
        planning_input.configuration,
    )
    input_document = canonical_plan_input_document(
        planning_input, request=request, validation=validation
    )
    input_content = canonical_json(input_document).encode()
    input_digest = _sha256(PLAN_INPUT_DIGEST_NAMESPACE, input_content)
    plan_id = _plan_id(input_digest, planning_input)
    metadata = PlanReconstructionMetadata(
        history_boundary=validation.history_boundary,
        input_artifact_hashes=tuple(
            sorted(
                (
                    request.canonical_digest,
                    validation.canonical_digest,
                    policy_digest(planning_input.policy),
                    configuration_digest(planning_input.configuration),
                )
            )
        ),
    )
    plan_document = {
        "canonical_input_digest": input_digest,
        "canonical_request_digest": request.canonical_digest,
        "capability_requirements": output.capability_requirements,
        "declared_dependencies": tuple(
            _dependency_document(item)
            for item in output.declared_dependencies
        ),
        "derivation_evidence": output.derivation_evidence,
        "normalized_plan_constraints": output.normalized_plan_constraints,
        "organization_id": request.organization_id,
        "plan_id": plan_id,
        "plan_schema_version": planning_input.plan_schema_version,
        "planning_configuration_digest": configuration_digest(
            planning_input.configuration
        ),
        "planning_rule_version": planning_input.planning_rule_version,
        "policy_version_or_digest": policy_digest(planning_input.policy),
        "reconstruction_metadata": {
            "history_boundary": metadata.history_boundary,
            "input_artifact_hashes": metadata.input_artifact_hashes,
            "planner_version": metadata.planner_version,
            "serialization_version": metadata.serialization_version,
        },
        "request_id": request.request_id,
        "request_schema_version": request.request_schema_version,
        "resource_requirements": output.resource_requirements,
        "serialization_version": SERIALIZATION_VERSION,
        "structured_planned_work": tuple(
            _step_document(item) for item in output.structured_planned_work
        ),
        "workload_context_id": request.workload_context_id,
    }
    plan_content = canonical_json(plan_document).encode()
    plan_digest = _sha256(PLAN_DIGEST_NAMESPACE, plan_content)
    return (
        ExecutionPlan(
            plan_id=plan_id,
            plan_schema_version=planning_input.plan_schema_version,
            request_id=request.request_id,
            request_schema_version=request.request_schema_version,
            canonical_request_digest=request.canonical_digest,
            organization_id=request.organization_id,
            workload_context_id=request.workload_context_id,
            planning_rule_version=planning_input.planning_rule_version,
            planning_configuration_digest=configuration_digest(
                planning_input.configuration
            ),
            policy_version_or_digest=policy_digest(planning_input.policy),
            canonical_input_digest=input_digest,
            canonical_plan_digest=plan_digest,
            structured_planned_work=output.structured_planned_work,
            capability_requirements=output.capability_requirements,
            resource_requirements=output.resource_requirements,
            declared_dependencies=output.declared_dependencies,
            normalized_plan_constraints=output.normalized_plan_constraints,
            derivation_evidence=output.derivation_evidence,
            reconstruction_metadata=metadata,
        ),
        input_content,
        plan_content,
    )


def _load(content: bytes | None, name: str) -> dict[str, Any]:
    if not content:
        raise ExecutionPlanReconstructionFailed(f"{name} is required.")
    try:
        document = json.loads(content.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionPlanReconstructionFailed(f"{name} is malformed.") from exc
    if not isinstance(document, dict):
        raise ExecutionPlanReconstructionFailed(f"{name} must be an object.")
    if canonical_json(document).encode() != content:
        raise ExecutionPlanReconstructionFailed(f"{name} is not canonical.")
    return document


def _planning_input_from_document(
    document: Mapping[str, Any],
) -> tuple[ExecutionPlanningInput, RequestValidationEvidence]:
    try:
        policy_data = document["policy"]
        config_data = document["configuration"]
        validation_data = document["validation_evidence"]
        policy = PlanningPolicy(
            policy_version=policy_data["policy_version"],
            required_capabilities=tuple(policy_data["required_capabilities"]),
            resource_requirements=policy_data["resource_requirements"],
            plan_constraint_defaults=policy_data["plan_constraint_defaults"],
        )
        configuration = PlanningConfiguration(
            configuration_version=config_data["configuration_version"],
            work_step_id=config_data["work_step_id"],
        )
        validation = build_request_validation_evidence(
            request_id=validation_data["request_id"],
            canonical_request_digest=validation_data[
                "canonical_request_digest"
            ],
            organization_id=validation_data["organization_id"],
            workload_context_id=validation_data["workload_context_id"],
            validation_policy_version=validation_data[
                "validation_policy_version"
            ],
            outcome=ValidationOutcome(validation_data["outcome"]),
            findings=tuple(validation_data["findings"]),
            history_boundary=validation_data["history_boundary"],
        )
        planning_input = ExecutionPlanningInput(
            organization_id=document["organization_id"],
            workload_context_id=document["workload_context_id"],
            request_id=document["request_id"],
            validation_evidence_id=validation_data[
                "validation_evidence_id"
            ],
            policy=policy,
            configuration=configuration,
            plan_schema_version=document["plan_schema_version"],
            planning_rule_version=document["planning_rule_version"],
        )
    except (KeyError, TypeError, ValueError, ExecutionPlanInvalid) as exc:
        raise ExecutionPlanReconstructionFailed(
            "Canonical planning input is incomplete or invalid."
        ) from exc
    if (
        policy_digest(policy) != document.get("policy_digest")
        or configuration_digest(configuration)
        != document.get("configuration_digest")
        or validation != RequestValidationEvidence(
            validation_evidence_id=validation_data[
                "validation_evidence_id"
            ],
            request_id=validation_data["request_id"],
            canonical_request_digest=validation_data[
                "canonical_request_digest"
            ],
            organization_id=validation_data["organization_id"],
            workload_context_id=validation_data["workload_context_id"],
            validation_policy_version=validation_data[
                "validation_policy_version"
            ],
            outcome=ValidationOutcome(validation_data["outcome"]),
            findings=tuple(validation_data["findings"]),
            history_boundary=validation_data["history_boundary"],
            schema_version=validation_data["schema_version"],
            canonical_digest=validation_data["canonical_digest"],
        )
    ):
        raise ExecutionPlanPolicyConfigurationMismatch(
            "Retained upstream evidence digest mismatch."
        )
    return planning_input, validation


def reconstruct_execution_plan(
    *,
    request: ExecutionRequest,
    canonical_input_content: bytes | None,
    canonical_plan_content: bytes | None,
    expected_input_digest: str,
    expected_plan_digest: str,
    expected_plan_id: str,
) -> ExecutionPlan:
    if not canonical_input_content or _sha256(
        PLAN_INPUT_DIGEST_NAMESPACE, canonical_input_content
    ) != expected_input_digest:
        raise ExecutionPlanDigestMismatch("Canonical input digest mismatch.")
    input_document = _load(canonical_input_content, "Canonical plan input")
    if input_document.get("serialization_version") != SERIALIZATION_VERSION:
        raise ExecutionPlanSchemaVersionUnsupported(
            "Unsupported canonical serialization version."
        )
    planning_input, validation = _planning_input_from_document(input_document)
    rebuilt, rebuilt_input, rebuilt_plan = build_execution_plan(
        planning_input, request=request, validation=validation
    )
    if rebuilt_input != canonical_input_content:
        raise ExecutionPlanReplayDiverged(
            "Planning-rule input reconstruction diverged."
        )
    if not canonical_plan_content or _sha256(
        PLAN_DIGEST_NAMESPACE, canonical_plan_content
    ) != expected_plan_digest:
        raise ExecutionPlanDigestMismatch("Canonical plan digest mismatch.")
    _load(canonical_plan_content, "Canonical plan content")
    if rebuilt.plan_id != expected_plan_id:
        raise ExecutionPlanIdentityMismatch("Plan identity diverged.")
    if (
        rebuilt.canonical_plan_digest != expected_plan_digest
        or rebuilt_plan != canonical_plan_content
    ):
        raise ExecutionPlanReplayDiverged(
            "Registered planning rule did not reproduce retained plan output."
        )
    return rebuilt
