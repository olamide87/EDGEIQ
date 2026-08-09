from datetime import datetime, timedelta, timezone
from typing import Any

from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.work_claim.canonical import canonical_json, namespaced_digest
from app.runtime.work_claim.domain import (
    EvidenceReference,
    WorkClaimDigestMismatch,
    WorkClaimEvent,
    WorkClaimReconstructionMetadata,
    WorkClaimRequest,
)
from app.runtime.work_claim.evidence import RetainedClaimantEvidence
from app.runtime.work_claim.policy import RegisteredWorkClaimPolicy, WorkClaimDecision

LINEAGE_ID_NAMESPACE = "edgeiq.work-claim-lineage-id.v1"
INPUT_DIGEST_NAMESPACE = "edgeiq.work-claim-input.v1"
EVENT_DIGEST_NAMESPACE = "edgeiq.work-claim-event.v1"
EVENT_ID_NAMESPACE = "edgeiq.work-claim-event-id.v1"
IDEMPOTENCY_NAMESPACE = "edgeiq.work-claim-idempotency.v1"


def lineage_identity(lineage_key: tuple[str, str, str, str]) -> str:
    return namespaced_digest(
        LINEAGE_ID_NAMESPACE,
        canonical_json({"lineage_key": lineage_key}).encode("utf-8"),
    )


def work_claim_idempotency_identity(request: WorkClaimRequest) -> str:
    document = {
        "operation": request.operation,
        "organization_id": request.organization_id,
        "plan_id": request.plan_id,
        "submitted_key": request.idempotency_key,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }
    return namespaced_digest(IDEMPOTENCY_NAMESPACE, canonical_json(document).encode("utf-8"))


def canonical_input_document(
    request: WorkClaimRequest,
    dispatch: DispatchDecisionRecord,
    claimant: RetainedClaimantEvidence,
    policy: RegisteredWorkClaimPolicy,
) -> dict[str, Any]:
    decision = dispatch.decision
    return {
        "claim_policy": {
            "canonical_digest": policy.canonical_digest,
            "claim_ttl_seconds": policy.claim_ttl_seconds,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
        },
        "claimant_evidence": {
            "authentication_boundary": claimant.authentication_boundary,
            "canonical_digest": claimant.canonical_digest,
            "claimant_id": claimant.claimant_id,
            "effective_at": claimant.effective_at,
            "evidence_id": claimant.evidence_id,
            "expires_at": claimant.expires_at,
            "producer_version": claimant.producer_version,
            "schema_version": claimant.schema_version,
            "selected_candidate_id": claimant.selected_candidate_id,
        },
        "clock_source_id": request.clock_source_id,
        "clock_source_version": request.clock_source_version,
        "component_version": request.component_version,
        "configuration_version": request.configuration_version,
        "dispatch_evidence": {
            "canonical_decision_digest": decision.canonical_decision_digest,
            "canonical_input_digest": decision.canonical_input_digest,
            "component_version": dispatch.request.component_version,
            "dispatch_decision_id": decision.dispatch_decision_id,
            "dispatch_policy_version": decision.dispatch_policy_version,
            "history_boundary": decision.reconstruction_metadata.history_boundary,
            "outcome": decision.outcome,
            "schema_version": decision.schema_version,
            "serialization_version": dispatch.request.serialization_version,
            "stream_version": decision.stream_version,
        },
        "evidence_boundary": request.evidence_boundary,
        "expected_lineage_version": request.expected_lineage_version,
        "operation": request.operation,
        "organization_id": request.organization_id,
        "plan_id": request.plan_id,
        "release_reason": request.release_reason,
        "schema_version": request.schema_version,
        "selected_candidate_id": request.selected_candidate_id,
        "semantic_at": request.semantic_at,
        "serialization_version": request.serialization_version,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }


def canonical_input_content(
    request: WorkClaimRequest,
    dispatch: DispatchDecisionRecord,
    claimant: RetainedClaimantEvidence,
    policy: RegisteredWorkClaimPolicy,
) -> bytes:
    return canonical_json(canonical_input_document(request, dispatch, claimant, policy)).encode("utf-8")


def build_work_claim_event(
    request: WorkClaimRequest,
    dispatch: DispatchDecisionRecord,
    claimant: RetainedClaimantEvidence,
    policy: RegisteredWorkClaimPolicy,
    decision: WorkClaimDecision,
    *,
    lineage_version: int,
    idempotency_identity: str,
    recorded_at: datetime | None = None,
) -> tuple[WorkClaimEvent, bytes, bytes]:
    input_content = canonical_input_content(request, dispatch, claimant, policy)
    input_digest = namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content)
    lineage_id = lineage_identity(request.lineage_key)
    expires_at = (
        None
        if decision.expires_at_delta_seconds is None
        else request.semantic_at + timedelta(seconds=decision.expires_at_delta_seconds)
    )
    payload = {
        "canonical_input_digest": input_digest,
        "causal_event_id": decision.causal_event_id,
        "claim_policy_reference": {
            "artifact_id": policy.policy_id,
            "canonical_digest": policy.canonical_digest,
            "policy_version": policy.policy_version,
        },
        "claimant_reference": {
            "artifact_id": claimant.evidence_id,
            "canonical_digest": claimant.canonical_digest,
        },
        "claimant_id": claimant.claimant_id,
        "dispatch_reference": {
            "artifact_id": dispatch.decision.dispatch_decision_id,
            "canonical_digest": dispatch.decision.canonical_decision_digest,
        },
        "event_type": decision.event_type,
        "expires_at": expires_at,
        "fence": decision.fence,
        "generation": decision.generation,
        "idempotency_identity": idempotency_identity,
        "lineage_id": lineage_id,
        "lineage_version": lineage_version,
        "organization_id": request.organization_id,
        "outcome": decision.outcome,
        "plan_id": request.plan_id,
        "reason_codes": decision.reason_codes,
        "reconstruction_metadata": {
            "clock_source_id": request.clock_source_id,
            "clock_source_version": request.clock_source_version,
            "component_version": request.component_version,
            "configuration_version": request.configuration_version,
            "evidence_boundary": request.evidence_boundary,
            "semantic_at": request.semantic_at,
            "serialization_version": request.serialization_version,
        },
        "release_reason": request.release_reason,
        "schema_version": request.schema_version,
        "selected_candidate_id": request.selected_candidate_id,
        "semantic_at": request.semantic_at,
        "work_item_id": request.work_item_id,
        "workload_context_id": request.workload_context_id,
    }
    event_content = canonical_json(payload).encode("utf-8")
    event_digest = namespaced_digest(EVENT_DIGEST_NAMESPACE, event_content)
    event_id = namespaced_digest(
        EVENT_ID_NAMESPACE,
        canonical_json(
            {
                "canonical_event_digest": event_digest,
                "lineage_id": lineage_id,
                "lineage_version": lineage_version,
            }
        ).encode("utf-8"),
    )
    event = WorkClaimEvent(
        event_id=event_id,
        lineage_id=lineage_id,
        organization_id=request.organization_id,
        workload_context_id=request.workload_context_id,
        plan_id=request.plan_id,
        work_item_id=request.work_item_id,
        event_type=decision.event_type,
        outcome=decision.outcome,
        reason_codes=decision.reason_codes,
        dispatch_reference=EvidenceReference(
            dispatch.decision.dispatch_decision_id,
            dispatch.decision.canonical_decision_digest,
        ),
        claimant_reference=EvidenceReference(claimant.evidence_id, claimant.canonical_digest),
        claimant_id=claimant.claimant_id,
        selected_candidate_id=request.selected_candidate_id,
        claim_policy_reference=EvidenceReference(policy.policy_id, policy.canonical_digest),
        claim_policy_version=policy.policy_version,
        lineage_version=lineage_version,
        generation=decision.generation,
        fence=decision.fence,
        semantic_at=request.semantic_at,
        expires_at=expires_at,
        release_reason=request.release_reason,
        causal_event_id=decision.causal_event_id,
        canonical_input_digest=input_digest,
        canonical_event_digest=event_digest,
        idempotency_identity=idempotency_identity,
        reconstruction_metadata=WorkClaimReconstructionMetadata(
            evidence_boundary=request.evidence_boundary,
            semantic_at=request.semantic_at,
            clock_source_id=request.clock_source_id,
            clock_source_version=request.clock_source_version,
            configuration_version=request.configuration_version,
        ),
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    return event, input_content, event_content


def verify_recorded_content(
    event: WorkClaimEvent,
    input_content: bytes,
    event_content: bytes,
) -> None:
    if namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content) != event.canonical_input_digest:
        raise WorkClaimDigestMismatch("Retained Work Claim input digest does not match.")
    if namespaced_digest(EVENT_DIGEST_NAMESPACE, event_content) != event.canonical_event_digest:
        raise WorkClaimDigestMismatch("Retained Work Claim event digest does not match.")
