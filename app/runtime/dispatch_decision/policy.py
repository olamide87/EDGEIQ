from dataclasses import dataclass

from app.runtime.dispatch_decision.canonical import canonical_json, namespaced_digest
from app.runtime.dispatch_decision.domain import (
    DispatchDecisionDigestMismatch,
    DispatchDecisionOutcome,
    DispatchDecisionVersionUnsupported,
    DispatchRequest,
)
from app.runtime.dispatch_decision.evidence import (
    RetainedLeaseEvidence,
    RetainedPlanEvidence,
    RetainedReadinessEvidence,
    RetainedSelectionCandidate,
    RetainedSelectionEvidence,
)

POLICY_NAMESPACE = "edgeiq.dispatch-policy.v1"


@dataclass(frozen=True)
class VerifiedDispatchEvidence:
    request: DispatchRequest
    plan: RetainedPlanEvidence
    selection: RetainedSelectionEvidence
    candidate: RetainedSelectionCandidate
    readiness: tuple[RetainedReadinessEvidence, ...]
    lease: RetainedLeaseEvidence


@dataclass(frozen=True)
class RegisteredDispatchPolicy:
    policy_id: str
    policy_version: str
    canonical_digest: str

    def evaluate(self, evidence: VerifiedDispatchEvidence) -> tuple[DispatchDecisionOutcome, tuple[str, ...]]:
        reasons: list[str] = []
        instant = evidence.request.effective_at
        if not evidence.lease.bounded_permission or instant < evidence.lease.effective_at:
            reasons.append("LEASE_INAPPLICABLE")
        if instant > evidence.lease.expires_at:
            reasons.append("LEASE_EXPIRED")
        if evidence.lease.revoked:
            reasons.append("LEASE_REVOKED")
        if any(instant > item.expires_at for item in evidence.readiness):
            reasons.append("READINESS_EXPIRED")
        if any(item.superseded for item in evidence.readiness):
            reasons.append("READINESS_SUPERSEDED")
        if reasons:
            return DispatchDecisionOutcome.DENIED, tuple(sorted(reasons))
        return DispatchDecisionOutcome.APPROVED, ("OFFER_APPROVED",)


def _policy(policy_id: str, policy_version: str) -> RegisteredDispatchPolicy:
    content = canonical_json(
        {
            "evaluation_rules": (
                "bounded_lease",
                "lease_effective_time",
                "lease_expiry",
                "lease_revocation",
                "readiness_expiry",
                "readiness_supersession",
            ),
            "policy_id": policy_id,
            "policy_version": policy_version,
        }
    ).encode("utf-8")
    return RegisteredDispatchPolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        canonical_digest=namespaced_digest(POLICY_NAMESPACE, content),
    )


DISPATCH_POLICY_V1 = _policy("dispatch-policy", "dispatch-policy.v1")
POLICY_REGISTRY = (DISPATCH_POLICY_V1,)


def policy_for(policy_id: str, policy_version: str, canonical_digest: str) -> RegisteredDispatchPolicy:
    matches = tuple(
        policy
        for policy in POLICY_REGISTRY
        if policy.policy_id == policy_id and policy.policy_version == policy_version
    )
    if len(matches) != 1:
        raise DispatchDecisionVersionUnsupported("Unsupported Dispatch policy identity or version.")
    policy = matches[0]
    if policy.canonical_digest != canonical_digest:
        raise DispatchDecisionDigestMismatch("Dispatch policy digest does not match the registered policy.")
    return policy
