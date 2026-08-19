from datetime import datetime, timezone
from typing import Any

from app.runtime.execution_lease.canonical import canonical_json, namespaced_digest
from app.runtime.execution_lease.domain import (
    EvidenceReference,
    ExecutionLeaseDigestMismatch,
    ExecutionLeaseEvent,
    ExecutionLeaseRequest,
    LeaseEventType,
    LeaseReconstructionMetadata,
)
from app.runtime.execution_lease.evidence import RetainedAuthorizationEvidence, RetainedRevocationEvidence
from app.runtime.execution_lease.policy import RegisteredExecutionLeasePolicy

LINEAGE_ID_NAMESPACE = "edgeiq.execution-lease-lineage-id.v1"
LEASE_ID_NAMESPACE = "edgeiq.execution-lease-id.v1"
INPUT_DIGEST_NAMESPACE = "edgeiq.execution-lease-input.v1"
EVENT_DIGEST_NAMESPACE = "edgeiq.execution-lease-event.v1"
EVENT_ID_NAMESPACE = "edgeiq.execution-lease-event-id.v1"
IDEMPOTENCY_NAMESPACE = "edgeiq.execution-lease-idempotency.v1"


def lineage_identity(lineage_key: tuple[str, str, str, str, str]) -> str:
    return namespaced_digest(LINEAGE_ID_NAMESPACE, canonical_json({"lineage_key": lineage_key}).encode("utf-8"))


def lease_identity(lineage_id: str, generation: int) -> str:
    return namespaced_digest(LEASE_ID_NAMESPACE, canonical_json({"generation": generation, "lineage_id": lineage_id}).encode("utf-8"))


def idempotency_identity(request: ExecutionLeaseRequest) -> str:
    document = {
        "idempotency_key": request.idempotency_key,
        "lineage_key": request.lineage_key,
        "operation": request.operation,
        "organization_id": request.organization_id,
    }
    return namespaced_digest(IDEMPOTENCY_NAMESPACE, canonical_json(document).encode("utf-8"))


def canonical_input_document(
    request: ExecutionLeaseRequest,
    authorization: RetainedAuthorizationEvidence | None,
    revocation: RetainedRevocationEvidence | None,
    policy: RegisteredExecutionLeasePolicy,
    *, generation: int,
) -> dict[str, Any]:
    return {
        "authorization_evidence": None if authorization is None else {
            "approved": authorization.approved,
            "authorization_id": authorization.authorization_id,
            "canonical_digest": authorization.canonical_digest,
            "component_version": authorization.component_version,
            "configuration_version": authorization.configuration_version,
            "causation_id": authorization.causation_id,
            "clock_source_id": authorization.clock_source_id,
            "clock_source_version": authorization.clock_source_version,
            "correlation_id": authorization.correlation_id,
            "decision_version": authorization.decision_version,
            "effective_at": authorization.effective_at,
            "evaluated_at": authorization.evaluated_at,
            "expires_at": authorization.expires_at,
            "history_boundary": authorization.history_boundary,
            "organization_id": authorization.organization_id,
            "permission_ceiling": authorization.permission_ceiling,
            "plan_id": authorization.plan_id,
            "policy_digest": authorization.policy_digest,
            "policy_id": authorization.policy_id,
            "policy_version": authorization.policy_version,
            "principal_id": authorization.principal_id,
            "schema_version": authorization.schema_version,
            "serialization_version": authorization.serialization_version,
            "work_item_id": authorization.work_item_id,
            "workload_context_id": authorization.workload_context_id,
        },
        "clock_source_id": request.clock_source_id,
        "clock_source_version": request.clock_source_version,
        "component_version": request.component_version,
        "configuration_version": request.configuration_version,
        "effective_at": request.effective_at,
        "evaluation_at": request.evaluation_at,
        "expected_lineage_version": request.expected_lineage_version,
        "expires_at": request.expires_at,
        "idempotency_key": request.idempotency_key,
        "lease_policy": {
            "canonical_digest": policy.canonical_digest,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
        },
        "operation": request.operation,
        "organization_id": request.organization_id,
        "owner_resolved_generation": generation,
        "permission_family": request.permission_family,
        "plan_id": request.plan_id,
        "prior_event_id": request.prior_event_id,
        "requested_permissions": request.requested_permissions,
        "revocation_evidence": None if revocation is None else {
            "authority_id": revocation.authority_id,
            "canonical_digest": revocation.canonical_digest,
            "component_version": revocation.component_version,
            "directive_id": revocation.directive_id,
            "effective_at": revocation.effective_at,
            "policy_id": revocation.policy_id,
            "policy_version": revocation.policy_version,
            "reason": revocation.reason,
            "schema_version": revocation.schema_version,
            "serialization_version": revocation.serialization_version,
        },
        "schema_version": request.schema_version,
        "serialization_version": request.serialization_version,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }


def canonical_input_content(request: ExecutionLeaseRequest, authorization: RetainedAuthorizationEvidence | None, revocation: RetainedRevocationEvidence | None, policy: RegisteredExecutionLeasePolicy, *, generation: int) -> bytes:
    return canonical_json(canonical_input_document(request, authorization, revocation, policy, generation=generation)).encode("utf-8")


def build_execution_lease_event(
    request: ExecutionLeaseRequest,
    authorization: RetainedAuthorizationEvidence | None,
    revocation: RetainedRevocationEvidence | None,
    policy: RegisteredExecutionLeasePolicy,
    *, event_type: LeaseEventType, generation: int, lineage_version: int,
    idempotency: str, superseded_lease_id: str | None = None,
    recorded_at: datetime | None = None,
) -> tuple[ExecutionLeaseEvent, bytes, bytes]:
    input_content = canonical_input_content(request, authorization, revocation, policy, generation=generation)
    input_digest = namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content)
    lineage_id = lineage_identity(request.lineage_key)
    lease_id = lease_identity(lineage_id, generation)
    permissions = request.requested_permissions if authorization is not None else ()
    effective_at = revocation.effective_at if revocation is not None else request.effective_at
    expires_at = request.expires_at if authorization is not None else None
    payload = {
        "authorization_reference": None if authorization is None else {
            "artifact_id": authorization.authorization_id,
            "canonical_digest": authorization.canonical_digest,
        },
        "canonical_input_digest": input_digest,
        "effective_at": effective_at,
        "event_type": event_type,
        "expires_at": expires_at,
        "generation": generation,
        "idempotency_identity": idempotency,
        "lease_id": lease_id,
        "lineage_id": lineage_id,
        "lineage_version": lineage_version,
        "organization_id": request.organization_id,
        "permission_family": request.permission_family,
        "permissions": permissions,
        "plan_id": request.plan_id,
        "policy_reference": {"artifact_id": policy.policy_id, "canonical_digest": policy.canonical_digest},
        "policy_version": policy.policy_version,
        "prior_event_id": request.prior_event_id,
        "reconstruction_metadata": {
            "authorization_history_boundary": request.authorization_history_boundary,
            "clock_source_id": request.clock_source_id,
            "clock_source_version": request.clock_source_version,
            "component_version": request.component_version,
            "configuration_version": request.configuration_version,
            "evaluation_at": request.evaluation_at,
            "serialization_version": request.serialization_version,
        },
        "revocation_reference": None if revocation is None else {
            "artifact_id": revocation.directive_id,
            "canonical_digest": revocation.canonical_digest,
        },
        "schema_version": request.schema_version,
        "superseded_lease_id": superseded_lease_id,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }
    event_content = canonical_json(payload).encode("utf-8")
    event_digest = namespaced_digest(EVENT_DIGEST_NAMESPACE, event_content)
    event_id = namespaced_digest(EVENT_ID_NAMESPACE, canonical_json({
        "canonical_event_digest": event_digest,
        "lineage_id": lineage_id,
        "lineage_version": lineage_version,
    }).encode("utf-8"))
    event = ExecutionLeaseEvent(
        event_id=event_id, lease_id=lease_id, lineage_id=lineage_id,
        organization_id=request.organization_id, workload_context_id=request.workload_context_id,
        plan_id=request.plan_id, work_item_id=request.work_item_id,
        permission_family=request.permission_family, event_type=event_type,
        permissions=permissions,
        authorization_reference=None if authorization is None else EvidenceReference(authorization.authorization_id, authorization.canonical_digest),
        revocation_reference=None if revocation is None else EvidenceReference(revocation.directive_id, revocation.canonical_digest),
        policy_reference=EvidenceReference(policy.policy_id, policy.canonical_digest),
        policy_version=policy.policy_version, generation=generation,
        lineage_version=lineage_version, prior_event_id=request.prior_event_id,
        superseded_lease_id=superseded_lease_id, effective_at=effective_at,
        expires_at=expires_at, canonical_input_digest=input_digest,
        canonical_event_digest=event_digest, idempotency_identity=idempotency,
        reconstruction_metadata=LeaseReconstructionMetadata(
            authorization_history_boundary=request.authorization_history_boundary,
            evaluation_at=request.evaluation_at, clock_source_id=request.clock_source_id,
            clock_source_version=request.clock_source_version,
            configuration_version=request.configuration_version,
        ),
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    return event, input_content, event_content


def verify_recorded_content(event: ExecutionLeaseEvent, input_content: bytes, event_content: bytes) -> None:
    if namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content) != event.canonical_input_digest:
        raise ExecutionLeaseDigestMismatch("Retained Execution Lease input digest does not match.")
    if namespaced_digest(EVENT_DIGEST_NAMESPACE, event_content) != event.canonical_event_digest:
        raise ExecutionLeaseDigestMismatch("Retained Execution Lease event digest does not match.")
