import hashlib
import json
from typing import Any, Mapping

from app.runtime.execution_plan.domain import (
    ExecutionPlan,
    ExecutionPlanDigestMismatch,
    ExecutionPlanDraft,
    ExecutionPlanIdentityMismatch,
    ExecutionPlanInvalid,
    ExecutionPlanPolicyConfigurationMismatch,
    ExecutionPlanReconstructionFailed,
    ExecutionPlanReplayDiverged,
    ExecutionPlanRequestDigestInvalid,
    ExecutionPlanRequestInvalid,
    ExecutionPlanRuleVersionUnsupported,
    ExecutionPlanSchemaVersionUnsupported,
    PlanDependency,
    PlanReconstructionMetadata,
    PlanStep,
    SUPPORTED_PLAN_SCHEMA_VERSION,
    SUPPORTED_PLANNER_VERSION,
    SUPPORTED_PLANNING_RULE_VERSION,
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


def _sha256(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode("utf-8") + b"\n" + content).hexdigest()


def _step_document(step: PlanStep) -> dict[str, Any]:
    return {
        "inputs": step.inputs,
        "operation": step.operation,
        "sequence": step.sequence,
        "step_id": step.step_id,
    }


def _dependency_document(
    dependency: PlanDependency,
) -> dict[str, str]:
    return {
        "predecessor_step_id": dependency.predecessor_step_id,
        "successor_step_id": dependency.successor_step_id,
    }


def _reconstruction_document(
    metadata: PlanReconstructionMetadata,
) -> dict[str, Any]:
    return {
        "history_boundary": metadata.history_boundary,
        "input_artifact_hashes": metadata.input_artifact_hashes,
        "planner_version": metadata.planner_version,
        "serialization_version": metadata.serialization_version,
    }


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
        reconstructed, content = build_execution_request(
            draft,
            accepted_idempotency_identity=request.idempotency_identity,
        )
    except ExecutionRequestInvalid as exc:
        raise ExecutionPlanRequestInvalid(
            "Accepted Execution Request evidence is invalid."
        ) from exc
    if reconstructed.canonical_digest != request.canonical_digest:
        raise ExecutionPlanRequestDigestInvalid(
            "Accepted Execution Request digest does not match canonical content."
        )
    if reconstructed.request_id != request.request_id:
        raise ExecutionPlanRequestInvalid(
            "Accepted Execution Request identity does not match canonical content."
        )
    if reconstructed != request:
        raise ExecutionPlanRequestInvalid(
            "Accepted Execution Request differs from reconstructed content."
        )
    return content


def plan_idempotency_identity(
    *,
    organization_id: str,
    workload_context_id: str,
    request_id: str,
    submitted_key: str,
) -> str:
    if not submitted_key:
        raise ExecutionPlanInvalid("An idempotency key is required.")
    scoped = canonical_json(
        {
            "operation": "derive-execution-plan",
            "organization_id": organization_id,
            "request_id": request_id,
            "submitted_key": submitted_key,
            "workload_context_id": workload_context_id,
        }
    ).encode("utf-8")
    return _sha256(PLAN_IDEMPOTENCY_NAMESPACE, scoped)


def canonical_plan_input_document(
    draft: ExecutionPlanDraft,
) -> dict[str, Any]:
    request = draft.request
    return {
        "canonical_request_digest": request.canonical_digest,
        "capability_requirements": draft.capability_requirements,
        "declared_dependencies": tuple(
            _dependency_document(item)
            for item in draft.declared_dependencies
        ),
        "derivation_evidence": draft.derivation_evidence,
        "normalized_plan_constraints": draft.normalized_plan_constraints,
        "organization_id": request.organization_id,
        "plan_schema_version": draft.plan_schema_version,
        "planning_configuration_digest": (
            draft.planning_configuration_digest
        ),
        "planning_rule_version": draft.planning_rule_version,
        "policy_version_or_digest": draft.policy_version_or_digest,
        "reconstruction_metadata": _reconstruction_document(
            draft.reconstruction_metadata
        ),
        "request_id": request.request_id,
        "request_schema_version": request.request_schema_version,
        "resource_requirements": draft.resource_requirements,
        "serialization_version": SERIALIZATION_VERSION,
        "structured_planned_work": tuple(
            _step_document(item) for item in draft.structured_planned_work
        ),
        "workload_context_id": request.workload_context_id,
    }


def canonical_plan_input_bytes(draft: ExecutionPlanDraft) -> bytes:
    validate_accepted_request(draft.request)
    return canonical_json(canonical_plan_input_document(draft)).encode("utf-8")


def _plan_identity(
    *,
    canonical_input_digest: str,
    plan_schema_version: str,
    planning_rule_version: str,
) -> str:
    content = canonical_json(
        {
            "canonical_input_digest": canonical_input_digest,
            "plan_schema_version": plan_schema_version,
            "planning_rule_version": planning_rule_version,
        }
    ).encode("utf-8")
    return _sha256(PLAN_ID_NAMESPACE, content)


def canonical_plan_document(
    draft: ExecutionPlanDraft,
    *,
    plan_id: str,
    canonical_input_digest: str,
) -> dict[str, Any]:
    request = draft.request
    return {
        "canonical_input_digest": canonical_input_digest,
        "canonical_request_digest": request.canonical_digest,
        "capability_requirements": draft.capability_requirements,
        "declared_dependencies": tuple(
            _dependency_document(item)
            for item in draft.declared_dependencies
        ),
        "derivation_evidence": draft.derivation_evidence,
        "normalized_plan_constraints": draft.normalized_plan_constraints,
        "organization_id": request.organization_id,
        "plan_id": plan_id,
        "plan_schema_version": draft.plan_schema_version,
        "planning_configuration_digest": (
            draft.planning_configuration_digest
        ),
        "planning_rule_version": draft.planning_rule_version,
        "policy_version_or_digest": draft.policy_version_or_digest,
        "reconstruction_metadata": _reconstruction_document(
            draft.reconstruction_metadata
        ),
        "request_id": request.request_id,
        "request_schema_version": request.request_schema_version,
        "resource_requirements": draft.resource_requirements,
        "serialization_version": SERIALIZATION_VERSION,
        "structured_planned_work": tuple(
            _step_document(item) for item in draft.structured_planned_work
        ),
        "workload_context_id": request.workload_context_id,
    }


def build_execution_plan(
    draft: ExecutionPlanDraft,
) -> tuple[ExecutionPlan, bytes, bytes]:
    canonical_input = canonical_plan_input_bytes(draft)
    input_digest = _sha256(PLAN_INPUT_DIGEST_NAMESPACE, canonical_input)
    plan_id = _plan_identity(
        canonical_input_digest=input_digest,
        plan_schema_version=draft.plan_schema_version,
        planning_rule_version=draft.planning_rule_version,
    )
    plan_content = canonical_json(
        canonical_plan_document(
            draft,
            plan_id=plan_id,
            canonical_input_digest=input_digest,
        )
    ).encode("utf-8")
    plan_digest = _sha256(PLAN_DIGEST_NAMESPACE, plan_content)
    request = draft.request
    return (
        ExecutionPlan(
            plan_id=plan_id,
            plan_schema_version=draft.plan_schema_version,
            request_id=request.request_id,
            request_schema_version=request.request_schema_version,
            canonical_request_digest=request.canonical_digest,
            organization_id=request.organization_id,
            workload_context_id=request.workload_context_id,
            planning_rule_version=draft.planning_rule_version,
            planning_configuration_digest=(
                draft.planning_configuration_digest
            ),
            policy_version_or_digest=draft.policy_version_or_digest,
            canonical_input_digest=input_digest,
            canonical_plan_digest=plan_digest,
            structured_planned_work=draft.structured_planned_work,
            capability_requirements=draft.capability_requirements,
            resource_requirements=draft.resource_requirements,
            declared_dependencies=draft.declared_dependencies,
            normalized_plan_constraints=draft.normalized_plan_constraints,
            derivation_evidence=draft.derivation_evidence,
            reconstruction_metadata=draft.reconstruction_metadata,
        ),
        canonical_input,
        plan_content,
    )


def _required_mapping(
    value: Any, field_name: str
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} must be a canonical object."
        )
    return value


def _required_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} must be a canonical array."
        )
    return value


def _load_canonical_document(
    content: bytes | None, *, field_name: str
) -> dict[str, Any]:
    if not content:
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} is required."
        )
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} is malformed."
        ) from exc
    if not isinstance(document, dict):
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} must be a canonical object."
        )
    if canonical_json(document).encode("utf-8") != content:
        raise ExecutionPlanReconstructionFailed(
            f"{field_name} is not canonical."
        )
    if document.get("serialization_version") != SERIALIZATION_VERSION:
        raise ExecutionPlanSchemaVersionUnsupported(
            "Unsupported canonical serialization version."
        )
    return document


def _draft_from_input_document(
    document: Mapping[str, Any], *, request: ExecutionRequest
) -> ExecutionPlanDraft:
    if document.get("plan_schema_version") != SUPPORTED_PLAN_SCHEMA_VERSION:
        raise ExecutionPlanSchemaVersionUnsupported(
            "Unsupported plan schema version."
        )
    if (
        document.get("planning_rule_version")
        != SUPPORTED_PLANNING_RULE_VERSION
    ):
        raise ExecutionPlanRuleVersionUnsupported(
            "Unsupported planning-rule version."
        )
    if document.get("request_id") != request.request_id:
        raise ExecutionPlanRequestInvalid(
            "Retained plan input references a different request identity."
        )
    if document.get("request_schema_version") != request.request_schema_version:
        raise ExecutionPlanRequestInvalid(
            "Retained plan input references a different request schema."
        )
    if (
        document.get("canonical_request_digest")
        != request.canonical_digest
    ):
        raise ExecutionPlanRequestDigestInvalid(
            "Retained plan input references a different request digest."
        )
    if (
        document.get("organization_id") != request.organization_id
        or document.get("workload_context_id")
        != request.workload_context_id
    ):
        raise ExecutionPlanRequestInvalid(
            "Retained plan input and request scope differ."
        )
    try:
        steps = tuple(
            PlanStep(
                sequence=item["sequence"],
                step_id=item["step_id"],
                operation=item["operation"],
                inputs=_required_mapping(item["inputs"], "step inputs"),
            )
            for item in (
                _required_mapping(value, "structured plan step")
                for value in _required_list(
                    document["structured_planned_work"],
                    "structured_planned_work",
                )
            )
        )
        dependencies = tuple(
            PlanDependency(
                predecessor_step_id=item["predecessor_step_id"],
                successor_step_id=item["successor_step_id"],
            )
            for item in (
                _required_mapping(value, "declared dependency")
                for value in _required_list(
                    document["declared_dependencies"],
                    "declared_dependencies",
                )
            )
        )
        metadata_document = _required_mapping(
            document["reconstruction_metadata"],
            "reconstruction_metadata",
        )
        metadata = PlanReconstructionMetadata(
            history_boundary=metadata_document["history_boundary"],
            planner_version=metadata_document["planner_version"],
            serialization_version=metadata_document[
                "serialization_version"
            ],
            input_artifact_hashes=tuple(
                _required_list(
                    metadata_document["input_artifact_hashes"],
                    "input_artifact_hashes",
                )
            ),
        )
        return ExecutionPlanDraft(
            request=request,
            structured_planned_work=steps,
            capability_requirements=tuple(
                _required_list(
                    document["capability_requirements"],
                    "capability_requirements",
                )
            ),
            resource_requirements=_required_mapping(
                document["resource_requirements"],
                "resource_requirements",
            ),
            declared_dependencies=dependencies,
            normalized_plan_constraints=_required_mapping(
                document["normalized_plan_constraints"],
                "normalized_plan_constraints",
            ),
            planning_configuration_digest=document[
                "planning_configuration_digest"
            ],
            policy_version_or_digest=document[
                "policy_version_or_digest"
            ],
            derivation_evidence=tuple(
                _required_list(
                    document["derivation_evidence"],
                    "derivation_evidence",
                )
            ),
            reconstruction_metadata=metadata,
            plan_schema_version=document["plan_schema_version"],
            planning_rule_version=document["planning_rule_version"],
        )
    except (
        KeyError,
        TypeError,
        ExecutionPlanInvalid,
    ) as exc:
        if isinstance(
            exc,
            (
                ExecutionPlanSchemaVersionUnsupported,
                ExecutionPlanRuleVersionUnsupported,
            ),
        ):
            raise
        raise ExecutionPlanReconstructionFailed(
            "Canonical plan input evidence is incomplete or invalid."
        ) from exc


def reconstruct_execution_plan(
    *,
    request: ExecutionRequest,
    canonical_input_content: bytes | None,
    canonical_plan_content: bytes | None,
    expected_input_digest: str,
    expected_plan_digest: str,
    expected_plan_id: str,
) -> ExecutionPlan:
    validate_accepted_request(request)
    if not canonical_input_content:
        raise ExecutionPlanReconstructionFailed(
            "Canonical plan input content is required."
        )
    actual_input_digest = _sha256(
        PLAN_INPUT_DIGEST_NAMESPACE,
        canonical_input_content,
    )
    if actual_input_digest != expected_input_digest:
        raise ExecutionPlanDigestMismatch(
            "Stored and recomputed canonical input digests differ."
        )
    input_document = _load_canonical_document(
        canonical_input_content, field_name="Canonical plan input content"
    )
    draft = _draft_from_input_document(input_document, request=request)
    reconstructed, reconstructed_input, reconstructed_plan = (
        build_execution_plan(draft)
    )
    if reconstructed_input != canonical_input_content:
        raise ExecutionPlanReplayDiverged(
            "Reconstructed canonical plan input diverged."
        )
    if not canonical_plan_content:
        raise ExecutionPlanReconstructionFailed(
            "Canonical plan content is required."
        )
    actual_plan_digest = _sha256(
        PLAN_DIGEST_NAMESPACE,
        canonical_plan_content,
    )
    if actual_plan_digest != expected_plan_digest:
        raise ExecutionPlanDigestMismatch(
            "Stored and recomputed canonical plan digests differ."
        )
    actual_plan_document = _load_canonical_document(
        canonical_plan_content, field_name="Canonical plan content"
    )
    if actual_plan_document.get("plan_id") != expected_plan_id:
        raise ExecutionPlanIdentityMismatch(
            "Stored plan identity differs from the expected identity."
        )
    if (
        actual_plan_document.get("planning_configuration_digest")
        != reconstructed.planning_configuration_digest
        or actual_plan_document.get("policy_version_or_digest")
        != reconstructed.policy_version_or_digest
    ):
        raise ExecutionPlanPolicyConfigurationMismatch(
            "Stored plan policy or configuration evidence diverged."
        )
    if reconstructed.plan_id != expected_plan_id:
        raise ExecutionPlanIdentityMismatch(
            "Reconstructed plan identity differs from the expected identity."
        )
    if reconstructed.canonical_plan_digest != expected_plan_digest:
        raise ExecutionPlanReplayDiverged(
            "Reconstructed plan digest diverged from retained plan evidence."
        )
    if reconstructed_plan != canonical_plan_content:
        raise ExecutionPlanReplayDiverged(
            "Reconstructed canonical plan content diverged."
        )
    return reconstructed
