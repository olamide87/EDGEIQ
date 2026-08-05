from datetime import datetime, timezone
from typing import Any

from app.runtime.dispatch_decision.canonical import canonical_json, namespaced_digest
from app.runtime.dispatch_decision.domain import (
    DispatchDecision,
    DispatchDecisionDigestMismatch,
    DispatchReconstructionMetadata,
    DispatchRequest,
    EvidenceReference,
)
from app.runtime.dispatch_decision.policy import RegisteredDispatchPolicy, VerifiedDispatchEvidence

INPUT_DIGEST_NAMESPACE = "edgeiq.dispatch-decision-input.v1"
DECISION_DIGEST_NAMESPACE = "edgeiq.dispatch-decision.v1"
DECISION_ID_NAMESPACE = "edgeiq.dispatch-decision-id.v1"
IDEMPOTENCY_NAMESPACE = "edgeiq.dispatch-decision-idempotency.v1"


def reference_document(reference: EvidenceReference) -> dict[str, str]:
    return {"artifact_id": reference.artifact_id, "canonical_digest": reference.canonical_digest}


def canonical_input_document(
    evidence: VerifiedDispatchEvidence,
    policy: RegisteredDispatchPolicy,
) -> dict[str, Any]:
    request = evidence.request
    return {
        "causal_authorization_reference": reference_document(evidence.lease.causal_authorization_reference),
        "clock_source_id": request.clock_source_id,
        "clock_source_version": request.clock_source_version,
        "component_version": request.component_version,
        "configuration_version": request.configuration_version,
        "effective_at": request.effective_at,
        "evaluation_boundary": request.evaluation_boundary,
        "lease_reference": {"artifact_id": evidence.lease.lease_id, "canonical_digest": evidence.lease.canonical_digest},
        "lease_policy_version": evidence.lease.lease_policy_version,
        "lease_schema_version": evidence.lease.schema_version,
        "organization_id": request.organization_id,
        "plan_reference": {"artifact_id": evidence.plan.plan_id, "canonical_digest": evidence.plan.canonical_digest},
        "plan_schema_version": evidence.plan.schema_version,
        "planning_rule_version": evidence.plan.planning_rule_version,
        "policy_reference": {
            "artifact_id": policy.policy_id,
            "canonical_digest": policy.canonical_digest,
            "policy_version": policy.policy_version,
        },
        "readiness_references": [
            {"artifact_id": item.readiness_id, "canonical_digest": item.canonical_digest}
            for item in evidence.readiness
        ],
        "schema_version": request.schema_version,
        "selected_candidate_id": request.selected_candidate_id,
        "selection_policy_version": evidence.selection.selection_policy_version,
        "selection_reference": {
            "artifact_id": evidence.selection.selection_id,
            "canonical_digest": evidence.selection.canonical_digest,
        },
        "selection_schema_version": evidence.selection.schema_version,
        "serialization_version": request.serialization_version,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }


def canonical_input_content(evidence: VerifiedDispatchEvidence, policy: RegisteredDispatchPolicy) -> bytes:
    return canonical_json(canonical_input_document(evidence, policy)).encode("utf-8")


def dispatch_idempotency_identity(request: DispatchRequest, submitted_key: str) -> str:
    if not isinstance(submitted_key, str) or not submitted_key:
        from app.runtime.dispatch_decision.domain import DispatchDecisionInvalid

        raise DispatchDecisionInvalid("An idempotency key is required.")
    content = canonical_json(
        {
            "operation": "evaluate_dispatch",
            "organization_id": request.organization_id,
            "plan_id": request.plan_id,
            "selected_candidate_id": request.selected_candidate_id,
            "submitted_key": submitted_key,
            "work_item_id": request.work_item_id,
            "workload_context_id": request.workload_context_id,
        }
    ).encode("utf-8")
    return namespaced_digest(IDEMPOTENCY_NAMESPACE, content)


def build_dispatch_decision(
    evidence: VerifiedDispatchEvidence,
    policy: RegisteredDispatchPolicy,
    *,
    stream_version: int,
    idempotency_identity: str,
    recorded_at: datetime | None = None,
) -> tuple[DispatchDecision, bytes, bytes]:
    request = evidence.request
    input_content = canonical_input_content(evidence, policy)
    input_digest = namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content)
    outcome, reasons = policy.evaluate(evidence)
    readiness_refs = tuple(
        EvidenceReference(item.readiness_id, item.canonical_digest) for item in evidence.readiness
    )
    payload = {
        "canonical_input_digest": input_digest,
        "causal_authorization_reference": reference_document(evidence.lease.causal_authorization_reference),
        "dispatch_policy_reference": {
            "artifact_id": policy.policy_id,
            "canonical_digest": policy.canonical_digest,
            "policy_version": policy.policy_version,
        },
        "idempotency_identity": idempotency_identity,
        "lease_reference": {"artifact_id": evidence.lease.lease_id, "canonical_digest": evidence.lease.canonical_digest},
        "organization_id": request.organization_id,
        "outcome": outcome,
        "plan_reference": {"artifact_id": evidence.plan.plan_id, "canonical_digest": evidence.plan.canonical_digest},
        "readiness_references": [reference_document(item) for item in readiness_refs],
        "reason_codes": reasons,
        "reconstruction_metadata": {
            "clock_source_id": request.clock_source_id,
            "clock_source_version": request.clock_source_version,
            "component_version": request.component_version,
            "configuration_version": request.configuration_version,
            "effective_at": request.effective_at,
            "history_boundary": request.evaluation_boundary,
            "serialization_version": request.serialization_version,
        },
        "schema_version": request.schema_version,
        "selected_candidate_id": request.selected_candidate_id,
        "selection_reference": {
            "artifact_id": evidence.selection.selection_id,
            "canonical_digest": evidence.selection.canonical_digest,
        },
        "stream_version": stream_version,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }
    decision_content = canonical_json(payload).encode("utf-8")
    decision_digest = namespaced_digest(DECISION_DIGEST_NAMESPACE, decision_content)
    decision_id = namespaced_digest(
        DECISION_ID_NAMESPACE,
        canonical_json(
            {"canonical_decision_digest": decision_digest, "stream_key": request.stream_key, "stream_version": stream_version}
        ).encode("utf-8"),
    )
    decision = DispatchDecision(
        dispatch_decision_id=decision_id,
        organization_id=request.organization_id,
        workload_context_id=request.workload_context_id,
        plan_reference=EvidenceReference(evidence.plan.plan_id, evidence.plan.canonical_digest),
        work_item_id=request.work_item_id,
        selection_reference=EvidenceReference(evidence.selection.selection_id, evidence.selection.canonical_digest),
        selected_candidate_id=request.selected_candidate_id,
        readiness_references=readiness_refs,
        lease_reference=EvidenceReference(evidence.lease.lease_id, evidence.lease.canonical_digest),
        causal_authorization_reference=evidence.lease.causal_authorization_reference,
        dispatch_policy_reference=EvidenceReference(policy.policy_id, policy.canonical_digest),
        dispatch_policy_version=policy.policy_version,
        outcome=outcome,
        reason_codes=reasons,
        canonical_input_digest=input_digest,
        canonical_decision_digest=decision_digest,
        stream_version=stream_version,
        idempotency_identity=idempotency_identity,
        reconstruction_metadata=DispatchReconstructionMetadata(
            history_boundary=request.evaluation_boundary,
            effective_at=request.effective_at,
            clock_source_id=request.clock_source_id,
            clock_source_version=request.clock_source_version,
            configuration_version=request.configuration_version,
        ),
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    return decision, input_content, decision_content


def verify_recorded_content(decision: DispatchDecision, input_content: bytes, decision_content: bytes) -> None:
    if namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content) != decision.canonical_input_digest:
        raise DispatchDecisionDigestMismatch("Retained dispatch input digest does not match.")
    if namespaced_digest(DECISION_DIGEST_NAMESPACE, decision_content) != decision.canonical_decision_digest:
        raise DispatchDecisionDigestMismatch("Retained dispatch decision digest does not match.")
