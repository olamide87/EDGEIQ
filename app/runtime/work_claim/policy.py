from dataclasses import dataclass
from datetime import timedelta

from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.work_claim.canonical import canonical_json, namespaced_digest
from app.runtime.work_claim.domain import (
    WorkClaimDigestMismatch,
    WorkClaimEvent,
    WorkClaimEventType,
    WorkClaimIllegalTransition,
    WorkClaimOperation,
    WorkClaimOutcome,
    WorkClaimRequest,
    WorkClaimVersionUnsupported,
)
from app.runtime.work_claim.evidence import RetainedClaimantEvidence

POLICY_NAMESPACE = "edgeiq.work-claim-policy.v1"


@dataclass(frozen=True)
class WorkClaimDerivedState:
    lineage_version: int = 0
    current_generation: int = 0
    generation_event: WorkClaimEvent | None = None
    accepted_event: WorkClaimEvent | None = None
    ended_event: WorkClaimEvent | None = None
    latest_fence: int = 0
    last_event: WorkClaimEvent | None = None


@dataclass(frozen=True)
class WorkClaimDecision:
    event_type: WorkClaimEventType
    outcome: WorkClaimOutcome
    reason_codes: tuple[str, ...]
    generation: int
    fence: int | None
    expires_at_delta_seconds: int | None
    causal_event_id: str | None


@dataclass(frozen=True)
class RegisteredWorkClaimPolicy:
    policy_id: str
    policy_version: str
    claim_ttl_seconds: int
    canonical_digest: str

    def decide(
        self,
        request: WorkClaimRequest,
        dispatch: DispatchDecisionRecord,
        claimant: RetainedClaimantEvidence,
        state: WorkClaimDerivedState,
    ) -> WorkClaimDecision:
        if state.last_event is not None and request.semantic_at < state.last_event.semantic_at:
            raise WorkClaimIllegalTransition("Semantic claim time cannot precede committed lineage evidence.")
        if request.operation is WorkClaimOperation.CREATE_GENERATION:
            if state.lineage_version == 0:
                generation = 1
                causal = None
            else:
                if state.generation_event is None or state.ended_event is None:
                    raise WorkClaimIllegalTransition("A later generation requires valid expiry or release evidence.")
                generation = state.current_generation + 1
                causal = state.ended_event.event_id
            return WorkClaimDecision(
                WorkClaimEventType.GENERATION_CREATED,
                WorkClaimOutcome.GENERATION_CREATED,
                ("GENERATION_CREATED",),
                generation,
                None,
                None,
                causal,
            )
        if state.generation_event is None or state.ended_event is not None:
            raise WorkClaimIllegalTransition("The lineage has no open claim generation.")
        if request.operation is WorkClaimOperation.CLAIM:
            if state.accepted_event is not None:
                return WorkClaimDecision(
                    WorkClaimEventType.CLAIM_REJECTED,
                    WorkClaimOutcome.REJECTED,
                    ("ACTIVE_CLAIM_EXISTS",),
                    state.current_generation,
                    None,
                    None,
                    state.accepted_event.event_id,
                )
            if not _claimant_matches_dispatch_candidate(claimant, dispatch):
                return WorkClaimDecision(
                    WorkClaimEventType.CLAIM_REJECTED,
                    WorkClaimOutcome.REJECTED,
                    ("CLAIMANT_NOT_SELECTED_CANDIDATE",),
                    state.current_generation,
                    None,
                    None,
                    state.generation_event.event_id,
                )
            return WorkClaimDecision(
                WorkClaimEventType.CLAIM_ACCEPTED,
                WorkClaimOutcome.ACCEPTED,
                ("CLAIM_ACCEPTED",),
                state.current_generation,
                state.latest_fence + 1,
                self.claim_ttl_seconds,
                state.generation_event.event_id,
            )
        if state.accepted_event is None:
            raise WorkClaimIllegalTransition("Expiry or release requires an accepted claim.")
        if request.dispatch_decision_id != state.accepted_event.dispatch_reference.artifact_id:
            raise WorkClaimIllegalTransition("Lifecycle termination must reference the accepted Dispatch Decision.")
        if request.operation is WorkClaimOperation.EXPIRE:
            if state.accepted_event.expires_at is None or request.semantic_at < state.accepted_event.expires_at:
                raise WorkClaimIllegalTransition("The accepted claim is not expired at the retained semantic time.")
            return WorkClaimDecision(
                WorkClaimEventType.CLAIM_EXPIRED,
                WorkClaimOutcome.EXPIRED,
                ("CLAIM_EXPIRED",),
                state.current_generation,
                None,
                None,
                state.accepted_event.event_id,
            )
        if request.operation is WorkClaimOperation.RELEASE:
            if claimant.claimant_id != state.accepted_event.claimant_id:
                raise WorkClaimIllegalTransition("Only the retained current claimant may release the claim.")
            if (
                not _claimant_matches_dispatch_candidate(claimant, dispatch)
                or claimant.selected_candidate_id != state.accepted_event.selected_candidate_id
            ):
                raise WorkClaimIllegalTransition(
                    "Retained claimant evidence does not match the accepted Dispatch-selected candidate."
                )
            return WorkClaimDecision(
                WorkClaimEventType.CLAIM_RELEASED,
                WorkClaimOutcome.RELEASED,
                ("CLAIM_RELEASED",),
                state.current_generation,
                None,
                None,
                state.accepted_event.event_id,
            )
        raise WorkClaimIllegalTransition("Unsupported Work Claim operation.")


def _claimant_matches_dispatch_candidate(
    claimant: RetainedClaimantEvidence,
    dispatch: DispatchDecisionRecord,
) -> bool:
    return claimant.selected_candidate_id == dispatch.decision.selected_candidate_id


def _policy(policy_id: str, policy_version: str, claim_ttl_seconds: int) -> RegisteredWorkClaimPolicy:
    content = canonical_json(
        {
            "claim_ttl_seconds": claim_ttl_seconds,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "rules": (
                "one_lineage",
                "owner_assigned_generation",
                "one_acceptance_per_generation",
                "acceptance_only_fence",
                "claimant_candidate_equivalence",
                "retained_semantic_expiry",
                "current_claimant_release",
            ),
        }
    ).encode("utf-8")
    return RegisteredWorkClaimPolicy(
        policy_id,
        policy_version,
        claim_ttl_seconds,
        namespaced_digest(POLICY_NAMESPACE, content),
    )


WORK_CLAIM_POLICY_V1 = _policy("work-claim-policy", "work-claim-policy.v1", 300)
POLICY_REGISTRY = (WORK_CLAIM_POLICY_V1,)


def policy_for(policy_id: str, policy_version: str, canonical_digest: str) -> RegisteredWorkClaimPolicy:
    matches = tuple(
        policy
        for policy in POLICY_REGISTRY
        if policy.policy_id == policy_id and policy.policy_version == policy_version
    )
    if len(matches) != 1:
        raise WorkClaimVersionUnsupported("Unsupported Work Claim policy identity or version.")
    policy = matches[0]
    if policy.canonical_digest != canonical_digest:
        raise WorkClaimDigestMismatch("Work Claim policy digest does not match the registered policy.")
    return policy
