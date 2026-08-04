from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.dispatch_decision.domain import (
    DispatchDecisionDigestMismatch,
    DispatchDecisionIdempotencyConflict,
    DispatchDecisionInvalid,
    DispatchDecisionNotFound,
    DispatchDecisionOutcome,
    DispatchDecisionPersistenceFailure,
    DispatchDecisionVersionConflict,
    DispatchDecisionVersionUnsupported,
    DispatchEvaluationOutcome,
    DispatchEvidenceMissing,
    DispatchRequest,
    EvidenceReference,
)
from app.runtime.dispatch_decision.canonical import canonical_json, namespaced_digest
from app.runtime.dispatch_decision.evidence import (
    InMemoryEvidenceSource,
    RetainedLeaseEvidence,
    RetainedPlanEvidence,
    RetainedReadinessEvidence,
    RetainedSelectionCandidate,
    RetainedSelectionEvidence,
    build_lease_evidence,
    build_plan_evidence,
    build_readiness_evidence,
    build_selection_evidence,
    validate_lease,
    validate_plan,
    validate_readiness,
    validate_selection,
)
from app.runtime.dispatch_decision.policy import DISPATCH_POLICY_V1
from app.runtime.dispatch_decision.serialization import DECISION_DIGEST_NAMESPACE
from app.runtime.dispatch_decision.service import (
    DispatchDecisionService,
    InMemoryDispatchDecisionRepository,
)

NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


class Context:
    def __init__(self, *, repository=None) -> None:
        self.plans = InMemoryEvidenceSource(lambda value: value.plan_id, validate_plan)
        self.selections = InMemoryEvidenceSource(lambda value: value.selection_id, validate_selection)
        self.readiness = InMemoryEvidenceSource(lambda value: value.readiness_id, validate_readiness)
        self.leases = InMemoryEvidenceSource(lambda value: value.lease_id, validate_lease)
        self.plan = build_plan_evidence(
            plan_id="plan:1", organization_id="org-1", workload_context_id="workload-1",
            work_item_ids=("work-item-1",),
        )
        self.ready = build_readiness_evidence(
            readiness_id="readiness:1", organization_id="org-1", workload_context_id="workload-1",
            evaluated_at=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(hours=1),
        )
        self.selection = build_selection_evidence(
            selection_id="selection:1", organization_id="org-1", workload_context_id="workload-1",
            plan_reference=EvidenceReference(self.plan.plan_id, self.plan.canonical_digest),
            candidates=(
                RetainedSelectionCandidate(
                    "worker-1", (EvidenceReference(self.ready.readiness_id, self.ready.canonical_digest),)
                ),
            ),
            evaluation_boundary="selection-history:1",
        )
        self.lease = build_lease_evidence(
            lease_id="lease:1", organization_id="org-1", workload_context_id="workload-1",
            plan_id=self.plan.plan_id, work_item_ids=("work-item-1",), bounded_permission=True,
            effective_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(hours=1), revoked=False,
            causal_authorization_reference=EvidenceReference("authorization:1", "a" * 64),
        )
        self.plans.retain(self.plan)
        self.readiness.retain(self.ready)
        self.selections.retain(self.selection)
        self.leases.retain(self.lease)
        self.service = DispatchDecisionService(
            plans=self.plans, selections=self.selections, readiness=self.readiness,
            leases=self.leases, repository=repository,
        )

    def request(self, **changes: object) -> DispatchRequest:
        values: dict[str, object] = {
            "organization_id": "org-1",
            "workload_context_id": "workload-1",
            "plan_id": self.plan.plan_id,
            "plan_digest": self.plan.canonical_digest,
            "work_item_id": "work-item-1",
            "selection_id": self.selection.selection_id,
            "selection_digest": self.selection.canonical_digest,
            "selected_candidate_id": "worker-1",
            "lease_id": self.lease.lease_id,
            "lease_digest": self.lease.canonical_digest,
            "dispatch_policy_id": DISPATCH_POLICY_V1.policy_id,
            "dispatch_policy_version": DISPATCH_POLICY_V1.policy_version,
            "dispatch_policy_digest": DISPATCH_POLICY_V1.canonical_digest,
            "evaluation_boundary": self.selection.evaluation_boundary,
            "effective_at": NOW,
            "clock_source_id": "trusted-clock",
            "clock_source_version": "clock.v1",
            "configuration_version": "dispatch-config.v1",
        }
        values.update(changes)
        return DispatchRequest(**values)  # type: ignore[arg-type]


def evaluate(context: Context, request: DispatchRequest | None = None, *, version=0, key="offer-1"):
    return context.service.evaluate(request or context.request(), expected_version=version, idempotency_key=key)


def test_public_request_exposes_references_not_dispatch_owned_results() -> None:
    names = {field.name for field in fields(DispatchRequest)}
    for forbidden in (
        "outcome", "reason_codes", "lease_applicable", "lease_expired", "lease_revoked",
        "selection_candidate_present", "selection_applicable", "readiness_applicable",
        "work_item_present", "policy_result", "readiness_references",
    ):
        assert forbidden not in names
    with pytest.raises(TypeError):
        Context().request(outcome="Approved")


def test_valid_approval_is_deterministic_and_immutable() -> None:
    context = Context()
    first = evaluate(context)
    assert first.decision.outcome is DispatchDecisionOutcome.APPROVED
    assert first.decision.reason_codes == ("OFFER_APPROVED",)
    with pytest.raises(FrozenInstanceError):
        first.decision.outcome = DispatchDecisionOutcome.DENIED  # type: ignore[misc]
    other = Context()
    second = evaluate(other)
    assert first.decision.dispatch_decision_id == second.decision.dispatch_decision_id
    assert first.decision.canonical_decision_digest == second.decision.canonical_decision_digest


@pytest.mark.parametrize(
    ("lease_changes", "readiness_changes", "reason"),
    [
        ({"expires_at": NOW - timedelta(seconds=1)}, {}, "LEASE_EXPIRED"),
        ({"revoked": True}, {}, "LEASE_REVOKED"),
        ({"bounded_permission": False}, {}, "LEASE_INAPPLICABLE"),
        ({}, {"expires_at": NOW - timedelta(seconds=1)}, "READINESS_EXPIRED"),
        ({}, {"superseded": True}, "READINESS_SUPERSEDED"),
    ],
)
def test_valid_complete_evidence_produces_deterministic_denial(lease_changes, readiness_changes, reason) -> None:
    context = Context()
    if lease_changes:
        context.lease = build_lease_evidence(
            lease_id="lease:2", organization_id="org-1", workload_context_id="workload-1",
            plan_id=context.plan.plan_id, work_item_ids=("work-item-1",), bounded_permission=lease_changes.get("bounded_permission", True),
            effective_at=NOW - timedelta(hours=1), expires_at=lease_changes.get("expires_at", NOW + timedelta(hours=1)),
            revoked=lease_changes.get("revoked", False), causal_authorization_reference=EvidenceReference("authorization:1", "a" * 64),
        )
        context.leases.retain(context.lease)
    if readiness_changes:
        context.ready = build_readiness_evidence(
            readiness_id="readiness:2", organization_id="org-1", workload_context_id="workload-1",
            evaluated_at=NOW - timedelta(hours=2), expires_at=readiness_changes.get("expires_at", NOW + timedelta(hours=1)),
            superseded=readiness_changes.get("superseded", False),
        )
        context.readiness.retain(context.ready)
        context.selection = build_selection_evidence(
            selection_id="selection:2", organization_id="org-1", workload_context_id="workload-1",
            plan_reference=EvidenceReference(context.plan.plan_id, context.plan.canonical_digest),
            candidates=(RetainedSelectionCandidate("worker-1", (EvidenceReference(context.ready.readiness_id, context.ready.canonical_digest),)),),
            evaluation_boundary="selection-history:1",
        )
        context.selections.retain(context.selection)
    result = evaluate(context)
    assert result.decision.outcome is DispatchDecisionOutcome.DENIED
    assert reason in result.decision.reason_codes


@pytest.mark.parametrize("missing", ["plan", "selection", "readiness", "lease"])
def test_missing_authoritative_evidence_fails_not_denies(missing: str) -> None:
    context = Context()
    source = getattr(context, f"{missing}s" if missing != "readiness" else "readiness")
    source._items.clear()
    with pytest.raises(DispatchEvidenceMissing):
        evaluate(context)
    assert context.service.history(context.request()) == ()


@pytest.mark.parametrize("artifact", ["plan", "selection", "readiness", "lease"])
def test_tampered_authoritative_digest_fails_closed(artifact: str) -> None:
    context = Context()
    source = getattr(context, f"{artifact}s" if artifact != "readiness" else "readiness")
    value = getattr(context, "ready" if artifact == "readiness" else artifact)
    identity = getattr(value, f"{artifact}_id" if artifact != "readiness" else "readiness_id")
    source._items[identity] = replace(value, canonical_digest="f" * 64)
    with pytest.raises(DispatchDecisionDigestMismatch):
        evaluate(context)


def test_plan_work_item_selection_and_lease_relationships_fail_closed() -> None:
    context = Context()
    with pytest.raises(DispatchDecisionInvalid, match="work item"):
        evaluate(context, context.request(work_item_id="missing"))
    wrong_plan = build_plan_evidence(
        plan_id="plan:2", organization_id="org-1", workload_context_id="workload-1", work_item_ids=("work-item-1",)
    )
    context.plans.retain(wrong_plan)
    with pytest.raises(DispatchDecisionInvalid, match="Selection"):
        evaluate(context, context.request(plan_id=wrong_plan.plan_id, plan_digest=wrong_plan.canonical_digest))
    wrong_lease = build_lease_evidence(
        lease_id="lease:2", organization_id="org-1", workload_context_id="workload-1",
        plan_id="plan:other", work_item_ids=("other-item",), bounded_permission=True,
        effective_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(hours=1), revoked=False,
        causal_authorization_reference=EvidenceReference("authorization:1", "a" * 64),
    )
    context.leases.retain(wrong_lease)
    with pytest.raises(DispatchDecisionInvalid, match="Execution Lease"):
        evaluate(context, context.request(lease_id=wrong_lease.lease_id, lease_digest=wrong_lease.canonical_digest))


def test_candidate_membership_and_transitive_readiness_are_selection_owned() -> None:
    context = Context()
    with pytest.raises(DispatchDecisionInvalid, match="candidate"):
        evaluate(context, context.request(selected_candidate_id="worker-2"))
    assert "readiness_references" not in {field.name for field in fields(DispatchRequest)}
    altered = build_readiness_evidence(
        readiness_id="readiness:new", organization_id="org-1", workload_context_id="workload-1",
        evaluated_at=NOW, expires_at=NOW + timedelta(hours=2),
    )
    context.readiness.retain(altered)
    assert evaluate(context).decision.readiness_references == (
        EvidenceReference(context.ready.readiness_id, context.ready.canonical_digest),
    )


def test_scope_and_unsupported_evidence_versions_fail_closed() -> None:
    context = Context()
    cross = build_plan_evidence(
        plan_id="plan:cross", organization_id="org-2", workload_context_id="workload-1", work_item_ids=("work-item-1",)
    )
    context.plans.retain(cross)
    with pytest.raises(Exception, match="organization"):
        evaluate(context, context.request(plan_id=cross.plan_id, plan_digest=cross.canonical_digest))
    context.selections._items[context.selection.selection_id] = replace(
        context.selection, selection_policy_version="unsupported"
    )
    with pytest.raises(DispatchDecisionVersionUnsupported):
        evaluate(context)


def test_invalid_authorization_causal_reference_fails_before_retention() -> None:
    with pytest.raises(DispatchDecisionInvalid):
        EvidenceReference("", "a" * 64)
    with pytest.raises(DispatchDecisionInvalid):
        EvidenceReference("authorization:1", "invalid")


def test_registered_policy_rejects_missing_version_and_digest_mismatch() -> None:
    context = Context()
    with pytest.raises(DispatchDecisionVersionUnsupported):
        evaluate(context, context.request(dispatch_policy_version="dispatch-policy.v2"))
    with pytest.raises(DispatchDecisionDigestMismatch):
        evaluate(context, context.request(dispatch_policy_digest="f" * 64))


def test_equivalent_retry_and_concurrent_equivalent_requests_converge() -> None:
    context = Context()
    request = context.request()

    def run(_):
        return context.service.evaluate(request, expected_version=0, idempotency_key="same")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(run, range(20)))
    assert sum(result.outcome is DispatchEvaluationOutcome.CREATED for result in results) == 1
    assert len({result.decision.dispatch_decision_id for result in results}) == 1
    assert len(context.service.history(request)) == 1
    assert all(result.stream_version == 1 for result in results)


def test_cas_and_conflicting_idempotency_preserve_accepted_state() -> None:
    context = Context()
    request = context.request()
    first = evaluate(context, request)
    with pytest.raises(DispatchDecisionVersionConflict):
        evaluate(context, request, version=0, key="other")
    changed = context.request(effective_at=NOW + timedelta(seconds=1))
    with pytest.raises(DispatchDecisionIdempotencyConflict):
        evaluate(context, changed, version=1, key="offer-1")
    assert context.service.history(request) == (first.decision,)


def test_changed_authoritative_inputs_never_collapse_into_prior_decision() -> None:
    context = Context()
    first = evaluate(context)
    newer = context.request(effective_at=NOW + timedelta(seconds=1))
    second = evaluate(context, newer, version=1, key="offer-2")
    assert second.decision.dispatch_decision_id != first.decision.dispatch_decision_id
    assert len(context.service.history(newer)) == 2


class FailingRepository(InMemoryDispatchDecisionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail = False

    def _commit_state(self, state) -> None:
        if self.fail:
            self.fail = False
            raise DispatchDecisionPersistenceFailure("injected failure")
        super()._commit_state(state)


def test_atomic_failure_leaves_empty_repository_unchanged() -> None:
    repository = FailingRepository()
    context = Context(repository=repository)
    repository.fail = True
    with pytest.raises(DispatchDecisionPersistenceFailure):
        evaluate(context)
    assert context.service.history(context.request()) == ()
    assert context.service.current(context.request()) is None


def test_atomic_failure_preserves_prior_snapshot_and_indexes() -> None:
    repository = FailingRepository()
    context = Context(repository=repository)
    first = evaluate(context)
    repository.fail = True
    changed = context.request(effective_at=NOW + timedelta(seconds=1))
    with pytest.raises(DispatchDecisionPersistenceFailure):
        evaluate(context, changed, version=1, key="offer-2")
    assert context.service.history(context.request()) == (first.decision,)
    assert context.service.current(context.request()) == first.decision
    assert context.service.get(first.decision.dispatch_decision_id, organization_id="org-1") == first.decision


def test_reconstruction_reresolves_authoritative_sources_and_detects_tampering() -> None:
    context = Context()
    created = evaluate(context)
    assert context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1") == created.decision
    context.plans._items[context.plan.plan_id] = replace(context.plan, canonical_content=b"forged")
    with pytest.raises(DispatchDecisionDigestMismatch):
        context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")


def test_reconstruction_fails_when_authoritative_source_disappears() -> None:
    context = Context()
    created = evaluate(context)
    context.leases._items.clear()
    with pytest.raises(DispatchEvidenceMissing):
        context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")


def test_reconstruction_detects_forged_output_divergence_without_mutation() -> None:
    context = Context()
    created = evaluate(context)
    repository = context.service.repository
    record = repository.record(created.decision.dispatch_decision_id)
    assert record is not None
    forged_content = canonical_json({"forged": True}).encode("utf-8")
    forged_digest = namespaced_digest(DECISION_DIGEST_NAMESPACE, forged_content)
    forged = replace(
        record,
        decision=replace(record.decision, canonical_decision_digest=forged_digest),
        canonical_decision_content=forged_content,
    )
    state = repository._state
    repository._state = replace(
        state, by_id={**state.by_id, created.decision.dispatch_decision_id: forged}
    )
    original_history = context.service.history(context.request())
    from app.runtime.dispatch_decision.domain import DispatchDecisionReplayDiverged

    with pytest.raises(DispatchDecisionReplayDiverged):
        context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")
    assert context.service.history(context.request()) == original_history


def test_reconstruction_detects_retained_input_and_output_divergence_without_mutation() -> None:
    context = Context()
    created = evaluate(context)
    record = context.service.repository.record(created.decision.dispatch_decision_id)
    assert record is not None
    original_history = context.service.history(context.request())
    bad = replace(record, canonical_input_content=record.canonical_input_content + b" ")
    state = context.service.repository._state
    context.service.repository._state = replace(state, by_id={**state.by_id, created.decision.dispatch_decision_id: bad})
    with pytest.raises(DispatchDecisionDigestMismatch):
        context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")
    assert context.service.history(context.request()) == original_history


def test_organization_and_workload_isolation_hide_evidence() -> None:
    context = Context()
    created = evaluate(context)
    with pytest.raises(DispatchDecisionNotFound):
        context.service.get(created.decision.dispatch_decision_id, organization_id="org-2")
    with pytest.raises(DispatchDecisionNotFound):
        context.service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-2")
    with pytest.raises(DispatchDecisionInvalid, match="workload"):
        evaluate(context, context.request(workload_context_id="workload-2"))


def test_no_downstream_behavior_or_external_dependencies() -> None:
    from pathlib import Path

    decision = evaluate(Context()).decision
    for forbidden in ("claim_id", "fence", "queue_envelope", "attempt_id"):
        assert not hasattr(decision, forbidden)
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("app/runtime/dispatch_decision").glob("*.py"))
    )
    for forbidden in (
        "work_claim", "queue", "execution_attempt", "monitoring", "completion",
        "retry", "provider", "orchestration", "fastapi", "sqlalchemy", "requests",
    ):
        assert f"from app.runtime.{forbidden}" not in source
