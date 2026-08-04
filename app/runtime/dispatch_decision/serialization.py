import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.runtime.dispatch_decision.domain import (
    ArtifactReference,
    DispatchDecision,
    DispatchDecisionDigestMismatch,
    DispatchDecisionInvalid,
    DispatchDecisionOutcome,
    DispatchEvaluationInput,
    DispatchPolicy,
    DispatchReconstructionMetadata,
)

INPUT_DIGEST_NAMESPACE = "edgeiq.dispatch-decision-input.v1"
DECISION_DIGEST_NAMESPACE = "edgeiq.dispatch-decision.v1"
DECISION_ID_NAMESPACE = "edgeiq.dispatch-decision-id.v1"
IDEMPOTENCY_NAMESPACE = "edgeiq.dispatch-decision-idempotency.v1"


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise DispatchDecisionInvalid(f"Unsupported canonical value: {type(value).__name__}.")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def namespaced_digest(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode() + b"\n" + content).hexdigest()


def reference_document(reference: ArtifactReference) -> dict[str, str]:
    return {
        "artifact_id": reference.artifact_id,
        "canonical_digest": reference.canonical_digest,
        "history_boundary": reference.history_boundary,
        "organization_id": reference.organization_id,
        "workload_context_id": reference.workload_context_id,
    }


def policy_document(policy: DispatchPolicy) -> dict[str, str]:
    return {
        "canonical_digest": policy.canonical_digest,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
    }


def input_document(value: DispatchEvaluationInput) -> dict[str, Any]:
    return {
        "causal_authorization_reference": reference_document(value.causal_authorization_reference),
        "clock_source_id": value.clock_source_id,
        "clock_source_version": value.clock_source_version,
        "component_version": value.component_version,
        "configuration_version": value.configuration_version,
        "effective_at": value.effective_at,
        "evaluation_boundary": value.evaluation_boundary,
        "lease": reference_document(value.lease),
        "lease_applicable": value.lease_applicable,
        "lease_expired": value.lease_expired,
        "lease_revoked": value.lease_revoked,
        "organization_id": value.organization_id,
        "plan": reference_document(value.plan),
        "policy": policy_document(value.policy),
        "readiness_applicable": value.readiness_applicable,
        "readiness_references": [reference_document(item) for item in value.readiness_references],
        "schema_version": value.schema_version,
        "selected_candidate_id": value.selected_candidate_id,
        "selection": reference_document(value.selection),
        "selection_applicable": value.selection_applicable,
        "selection_candidate_present": value.selection_candidate_present,
        "serialization_version": value.serialization_version,
        "work_item_id": value.work_item_id,
        "workload_context_id": value.workload_context_id,
    }


def canonical_input_content(value: DispatchEvaluationInput) -> bytes:
    return canonical_json(input_document(value)).encode("utf-8")


def dispatch_idempotency_identity(value: DispatchEvaluationInput, submitted_key: str) -> str:
    if not isinstance(submitted_key, str) or not submitted_key:
        raise DispatchDecisionInvalid("An idempotency key is required.")
    content = canonical_json(
        {
            "operation": "evaluate_dispatch",
            "organization_id": value.organization_id,
            "plan_id": value.plan.artifact_id,
            "selected_candidate_id": value.selected_candidate_id,
            "submitted_key": submitted_key,
            "work_item_id": value.work_item_id,
            "workload_context_id": value.workload_context_id,
        }
    ).encode("utf-8")
    return namespaced_digest(IDEMPOTENCY_NAMESPACE, content)


def evaluate_outcome(value: DispatchEvaluationInput) -> tuple[DispatchDecisionOutcome, tuple[str, ...]]:
    reasons: list[str] = []
    if not value.selection_candidate_present:
        reasons.append("CANDIDATE_NOT_SELECTED")
    if not value.selection_applicable:
        reasons.append("SELECTION_INAPPLICABLE")
    if not value.readiness_applicable:
        reasons.append("READINESS_INAPPLICABLE")
    if not value.lease_applicable:
        reasons.append("LEASE_INAPPLICABLE")
    if value.lease_expired:
        reasons.append("LEASE_EXPIRED")
    if value.lease_revoked:
        reasons.append("LEASE_REVOKED")
    if reasons:
        return DispatchDecisionOutcome.DENIED, tuple(sorted(reasons))
    return DispatchDecisionOutcome.APPROVED, ("OFFER_APPROVED",)


def decision_payload(
    value: DispatchEvaluationInput,
    *,
    outcome: DispatchDecisionOutcome,
    reason_codes: tuple[str, ...],
    canonical_input_digest: str,
    idempotency_identity: str,
    stream_version: int,
) -> dict[str, Any]:
    return {
        "canonical_input_digest": canonical_input_digest,
        "causal_authorization_reference": reference_document(value.causal_authorization_reference),
        "dispatch_policy": policy_document(value.policy),
        "idempotency_identity": idempotency_identity,
        "lease_reference": reference_document(value.lease),
        "organization_id": value.organization_id,
        "outcome": outcome,
        "plan_reference": reference_document(value.plan),
        "readiness_references": [reference_document(item) for item in value.readiness_references],
        "reason_codes": reason_codes,
        "reconstruction_metadata": {
            "clock_source_id": value.clock_source_id,
            "clock_source_version": value.clock_source_version,
            "component_version": value.component_version,
            "configuration_version": value.configuration_version,
            "effective_at": value.effective_at,
            "history_boundary": value.evaluation_boundary,
            "serialization_version": value.serialization_version,
        },
        "schema_version": value.schema_version,
        "selected_candidate_id": value.selected_candidate_id,
        "selection_reference": reference_document(value.selection),
        "stream_version": stream_version,
        "work_item_id": value.work_item_id,
        "workload_context_id": value.workload_context_id,
    }


def build_dispatch_decision(
    value: DispatchEvaluationInput,
    *,
    stream_version: int,
    idempotency_identity: str,
    recorded_at: datetime | None = None,
) -> tuple[DispatchDecision, bytes, bytes]:
    input_content = canonical_input_content(value)
    input_digest = namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content)
    outcome, reasons = evaluate_outcome(value)
    payload = decision_payload(
        value,
        outcome=outcome,
        reason_codes=reasons,
        canonical_input_digest=input_digest,
        idempotency_identity=idempotency_identity,
        stream_version=stream_version,
    )
    decision_content = canonical_json(payload).encode("utf-8")
    decision_digest = namespaced_digest(DECISION_DIGEST_NAMESPACE, decision_content)
    decision_id = namespaced_digest(
        DECISION_ID_NAMESPACE,
        canonical_json(
            {
                "canonical_decision_digest": decision_digest,
                "stream_key": value.stream_key,
                "stream_version": stream_version,
            }
        ).encode("utf-8"),
    )
    decision = DispatchDecision(
        dispatch_decision_id=decision_id,
        organization_id=value.organization_id,
        workload_context_id=value.workload_context_id,
        plan_reference=value.plan,
        work_item_id=value.work_item_id,
        selection_reference=value.selection,
        selected_candidate_id=value.selected_candidate_id,
        readiness_references=value.readiness_references,
        lease_reference=value.lease,
        causal_authorization_reference=value.causal_authorization_reference,
        dispatch_policy=value.policy,
        outcome=outcome,
        reason_codes=reasons,
        canonical_input_digest=input_digest,
        canonical_decision_digest=decision_digest,
        stream_version=stream_version,
        idempotency_identity=idempotency_identity,
        reconstruction_metadata=DispatchReconstructionMetadata(
            history_boundary=value.evaluation_boundary,
            effective_at=value.effective_at,
            clock_source_id=value.clock_source_id,
            clock_source_version=value.clock_source_version,
            configuration_version=value.configuration_version,
        ),
        recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    return decision, input_content, decision_content


def verify_recorded_content(
    decision: DispatchDecision,
    input_content: bytes,
    decision_content: bytes,
) -> None:
    if namespaced_digest(INPUT_DIGEST_NAMESPACE, input_content) != decision.canonical_input_digest:
        raise DispatchDecisionDigestMismatch("Retained dispatch input digest does not match.")
    if namespaced_digest(DECISION_DIGEST_NAMESPACE, decision_content) != decision.canonical_decision_digest:
        raise DispatchDecisionDigestMismatch("Retained dispatch decision digest does not match.")
