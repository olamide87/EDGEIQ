from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.dispatch_decision.domain import DispatchRequest, EvidenceReference
from app.runtime.dispatch_decision.evidence import (
    InMemoryEvidenceSource,
    RetainedSelectionCandidate,
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
from app.runtime.dispatch_decision.service import DispatchDecisionService
from app.runtime.work_claim.canonical import canonical_json
from app.runtime.work_claim.domain import (
    WorkClaimDigestMismatch,
    WorkClaimEventType,
    WorkClaimEvidenceUnavailable,
    WorkClaimIdempotencyConflict,
    WorkClaimIllegalTransition,
    WorkClaimNotFound,
    WorkClaimOperation,
    WorkClaimOutcome,
    WorkClaimPersistenceFailure,
    WorkClaimReconstructionFailed,
    WorkClaimReplayDiverged,
    WorkClaimRequest,
    WorkClaimVersionConflict,
    WorkClaimVersionUnsupported,
)
from app.runtime.work_claim.evidence import (
    build_claimant_evidence,
    claimant_source,
    dispatch_source,
)
from app.runtime.work_claim.policy import WORK_CLAIM_POLICY_V1, WorkClaimDerivedState
from app.runtime.work_claim.serialization import lineage_identity
from app.runtime.work_claim.serialization import verify_recorded_content
from app.runtime.work_claim.service import (
    InMemoryWorkClaimRepository,
    WorkClaimService,
    _advance_state,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
SAFE_EVIDENCE_MESSAGE = "Required Work Claim evidence was not found."


class FailingRepository(InMemoryWorkClaimRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def _commit_state(self, state) -> None:
        if self.fail:
            raise OSError("injected publication failure")
        super()._commit_state(state)


class Context:
    def __init__(self, *, repository=None, organization_id="org-1", workload_context_id="workload-1") -> None:
        self.organization_id = organization_id
        self.workload_context_id = workload_context_id
        plans = InMemoryEvidenceSource(lambda value: value.plan_id, validate_plan)
        selections = InMemoryEvidenceSource(lambda value: value.selection_id, validate_selection)
        readiness = InMemoryEvidenceSource(lambda value: value.readiness_id, validate_readiness)
        leases = InMemoryEvidenceSource(lambda value: value.lease_id, validate_lease)
        plan = build_plan_evidence(
            plan_id="plan:1",
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            work_item_ids=("work-item-1",),
        )
        ready = build_readiness_evidence(
            readiness_id="readiness:1",
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            evaluated_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(hours=3),
        )
        selection = build_selection_evidence(
            selection_id="selection:1",
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            plan_reference=EvidenceReference(plan.plan_id, plan.canonical_digest),
            candidates=(
                RetainedSelectionCandidate(
                    "worker-1",
                    (EvidenceReference(ready.readiness_id, ready.canonical_digest),),
                ),
            ),
            evaluation_boundary="selection-history:1",
        )
        lease = build_lease_evidence(
            lease_id="lease:1",
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            plan_id=plan.plan_id,
            work_item_ids=("work-item-1",),
            bounded_permission=True,
            effective_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=3),
            revoked=False,
            causal_authorization_reference=EvidenceReference("authorization:1", "a" * 64),
        )
        for source, value in (
            (plans, plan), (readiness, ready), (selections, selection), (leases, lease)
        ):
            source.retain(value)
        dispatch_service = DispatchDecisionService(
            plans=plans,
            selections=selections,
            readiness=readiness,
            leases=leases,
        )
        dispatch_request = DispatchRequest(
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            plan_id=plan.plan_id,
            plan_digest=plan.canonical_digest,
            work_item_id="work-item-1",
            selection_id=selection.selection_id,
            selection_digest=selection.canonical_digest,
            selected_candidate_id="worker-1",
            lease_id=lease.lease_id,
            lease_digest=lease.canonical_digest,
            dispatch_policy_id=DISPATCH_POLICY_V1.policy_id,
            dispatch_policy_version=DISPATCH_POLICY_V1.policy_version,
            dispatch_policy_digest=DISPATCH_POLICY_V1.canonical_digest,
            evaluation_boundary=selection.evaluation_boundary,
            effective_at=NOW,
            clock_source_id="trusted-clock",
            clock_source_version="clock.v1",
            configuration_version="dispatch-config.v1",
        )
        dispatch_result = dispatch_service.evaluate(
            dispatch_request,
            expected_version=0,
            idempotency_key="offer-1",
        )
        self.dispatch_record = dispatch_service.repository.record(
            dispatch_result.decision.dispatch_decision_id
        )
        assert self.dispatch_record is not None
        self.dispatches = dispatch_source()
        self.dispatches.retain(self.dispatch_record)
        self.claimants = claimant_source()
        self.claimant = build_claimant_evidence(
            evidence_id="claimant-evidence:1",
            claimant_id="claimant-1",
            selected_candidate_id="worker-1",
            organization_id=organization_id,
            workload_context_id=workload_context_id,
            authentication_boundary="authentication:1",
            effective_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
        )
        self.claimants.retain(self.claimant)
        self.repository = repository or InMemoryWorkClaimRepository()
        self.service = WorkClaimService(
            dispatches=self.dispatches,
            claimants=self.claimants,
            repository=self.repository,
        )

    def add_claimant(
        self,
        evidence_id: str,
        *,
        claimant_id: str,
        selected_candidate_id: str = "worker-1",
        organization_id: str | None = None,
        workload_context_id: str | None = None,
    ):
        value = build_claimant_evidence(
            evidence_id=evidence_id,
            claimant_id=claimant_id,
            selected_candidate_id=selected_candidate_id,
            organization_id=organization_id or self.organization_id,
            workload_context_id=workload_context_id or self.workload_context_id,
            authentication_boundary="authentication:1",
            effective_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=2),
        )
        self.claimants.retain(value)
        return value

    def request(self, operation=WorkClaimOperation.CREATE_GENERATION, **changes) -> WorkClaimRequest:
        claimant = changes.pop("claimant", self.claimant)
        values = {
            "operation": operation,
            "organization_id": self.organization_id,
            "workload_context_id": self.workload_context_id,
            "plan_id": "plan:1",
            "work_item_id": "work-item-1",
            "dispatch_decision_id": self.dispatch_record.decision.dispatch_decision_id,
            "dispatch_decision_digest": self.dispatch_record.decision.canonical_decision_digest,
            "claimant_evidence_id": claimant.evidence_id,
            "claimant_evidence_digest": claimant.canonical_digest,
            "selected_candidate_id": "worker-1",
            "claim_policy_id": WORK_CLAIM_POLICY_V1.policy_id,
            "claim_policy_version": WORK_CLAIM_POLICY_V1.policy_version,
            "claim_policy_digest": WORK_CLAIM_POLICY_V1.canonical_digest,
            "evidence_boundary": "selection-history:1",
            "semantic_at": NOW,
            "clock_source_id": "trusted-clock",
            "clock_source_version": "clock.v1",
            "configuration_version": "work-claim-config.v1",
            "expected_lineage_version": 0,
            "idempotency_key": "generation-1",
        }
        values.update(changes)
        return WorkClaimRequest(**values)

    def evaluate(self, operation=WorkClaimOperation.CREATE_GENERATION, **changes):
        return self.service.evaluate(self.request(operation, **changes))

    def generation(self, *, version=0, key="generation-1", semantic_at=NOW):
        return self.evaluate(
            WorkClaimOperation.CREATE_GENERATION,
            expected_lineage_version=version,
            idempotency_key=key,
            semantic_at=semantic_at,
        ).event

    def accept(self, *, version=1, key="claim-1", claimant=None, semantic_at=NOW + timedelta(seconds=1)):
        return self.evaluate(
            WorkClaimOperation.CLAIM,
            expected_lineage_version=version,
            idempotency_key=key,
            claimant=claimant or self.claimant,
            semantic_at=semantic_at,
        ).event


def test_public_input_contains_no_owner_authored_outputs() -> None:
    names = {field.name for field in fields(WorkClaimRequest)}
    for forbidden in (
        "outcome", "reason_codes", "generation", "fence", "lineage_version",
        "event_id", "canonical_event_digest", "current_claim", "claimant_eligible",
        "dispatch_applicable", "expiry_result", "release_result",
    ):
        assert forbidden not in names


def test_lineage_identity_is_canonical_and_excludes_generation_candidate_claimant_dispatch() -> None:
    context = Context()
    request = context.request()
    assert request.lineage_key == ("org-1", "workload-1", "plan:1", "work-item-1")
    assert lineage_identity(request.lineage_key) == lineage_identity(tuple(request.lineage_key))
    assert len(request.lineage_key) == 4


def test_owner_assigns_first_generation_without_advancing_fence() -> None:
    event = Context().generation()
    assert event.event_type is WorkClaimEventType.GENERATION_CREATED
    assert event.generation == 1
    assert event.lineage_version == 1
    assert event.fence is None


def test_valid_acceptance_is_immutable_and_separates_version_generation_fence() -> None:
    context = Context()
    context.generation()
    event = context.accept()
    assert event.outcome is WorkClaimOutcome.ACCEPTED
    assert (event.lineage_version, event.generation, event.fence) == (2, 1, 1)
    with pytest.raises(FrozenInstanceError):
        event.fence = 2  # type: ignore[misc]


def test_valid_retained_rejection_does_not_advance_fence() -> None:
    context = Context()
    mismatched = context.add_claimant(
        "claimant-evidence:other", claimant_id="claimant-2", selected_candidate_id="worker-2"
    )
    context.generation()
    rejected = context.evaluate(
        WorkClaimOperation.CLAIM,
        expected_lineage_version=1,
        idempotency_key="reject-1",
        claimant=mismatched,
        semantic_at=NOW + timedelta(seconds=1),
    ).event
    assert rejected.outcome is WorkClaimOutcome.REJECTED
    assert rejected.reason_codes == ("CLAIMANT_NOT_SELECTED_CANDIDATE",)
    assert rejected.fence is None
    accepted = context.accept(version=2, key="claim-after-rejection", semantic_at=NOW + timedelta(seconds=2))
    assert accepted.fence == 1


def test_one_acceptance_per_generation_is_retained_rejection() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    other = context.add_claimant("claimant-evidence:2", claimant_id="claimant-2")
    rejected = context.evaluate(
        WorkClaimOperation.CLAIM,
        expected_lineage_version=2,
        idempotency_key="claim-2",
        claimant=other,
        semantic_at=NOW + timedelta(seconds=2),
    ).event
    assert rejected.reason_codes == ("ACTIVE_CLAIM_EXISTS",)
    assert rejected.fence is None
    assert accepted.fence == 1


def test_later_generation_requires_release_or_expiry_and_receives_new_fence() -> None:
    context = Context()
    context.generation()
    first = context.accept()
    with pytest.raises(WorkClaimIllegalTransition, match="expiry or release"):
        context.generation(
            version=2,
            key="generation-too-early",
            semantic_at=NOW + timedelta(seconds=2),
        )
    released = context.evaluate(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=2,
        idempotency_key="release-1",
        semantic_at=NOW + timedelta(minutes=1),
        release_reason="voluntary",
    ).event
    assert released.fence is None
    second_generation = context.generation(
        version=3, key="generation-2", semantic_at=NOW + timedelta(minutes=2)
    )
    second = context.accept(
        version=4, key="claim-generation-2", semantic_at=NOW + timedelta(minutes=2, seconds=1)
    )
    assert second_generation.generation == 2
    assert second_generation.fence is None
    assert second.generation == 2
    assert second.fence == 2 > first.fence


def test_expiry_appends_and_preserves_prior_acceptance() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    assert accepted.expires_at is not None
    expired = context.evaluate(
        WorkClaimOperation.EXPIRE,
        expected_lineage_version=2,
        idempotency_key="expire-1",
        semantic_at=accepted.expires_at,
    ).event
    assert expired.outcome is WorkClaimOutcome.EXPIRED
    assert expired.fence is None
    assert context.service.get(
        accepted.event_id, organization_id="org-1", workload_context_id="workload-1"
    ) == accepted


def test_release_appends_and_requires_current_claimant() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    other = context.add_claimant("claimant-evidence:2", claimant_id="claimant-2")
    with pytest.raises(WorkClaimIllegalTransition, match="current claimant"):
        context.evaluate(
            WorkClaimOperation.RELEASE,
            expected_lineage_version=2,
            idempotency_key="bad-release",
            claimant=other,
            semantic_at=NOW + timedelta(minutes=1),
            release_reason="invalid",
        )
    released = context.evaluate(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=2,
        idempotency_key="release-1",
        semantic_at=NOW + timedelta(minutes=1),
        release_reason="voluntary",
    ).event
    assert released.outcome is WorkClaimOutcome.RELEASED
    assert released.causal_event_id == accepted.event_id


def test_release_accepts_new_retained_authentication_evidence_for_same_claimant() -> None:
    context = Context()
    context.generation()
    context.accept()
    renewed = context.add_claimant(
        "claimant-evidence:renewed",
        claimant_id="claimant-1",
    )
    released = context.evaluate(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=2,
        idempotency_key="release-renewed",
        claimant=renewed,
        semantic_at=NOW + timedelta(minutes=1),
        release_reason="voluntary",
    ).event
    assert released.claimant_id == "claimant-1"
    assert released.claimant_reference.artifact_id == renewed.evidence_id


def test_equivalent_retry_returns_existing_and_conflicting_reuse_fails() -> None:
    context = Context()
    request = context.request()
    first = context.service.evaluate(request)
    second = context.service.evaluate(request)
    assert second.event is first.event
    assert len(context.repository.history(request.lineage_key)) == 1
    with pytest.raises(WorkClaimIdempotencyConflict):
        context.service.evaluate(replace(request, semantic_at=NOW + timedelta(seconds=1)))
    assert len(context.repository.history(request.lineage_key)) == 1


def test_stale_expected_version_appends_nothing() -> None:
    context = Context()
    context.generation()
    with pytest.raises(WorkClaimVersionConflict):
        context.evaluate(
            WorkClaimOperation.CLAIM,
            expected_lineage_version=0,
            idempotency_key="stale-claim",
            semantic_at=NOW + timedelta(seconds=1),
        )
    assert len(context.repository.history(context.request().lineage_key)) == 1


def _race(callables):
    with ThreadPoolExecutor(max_workers=len(callables)) as pool:
        futures = [pool.submit(call) for call in callables]
    return [future.exception() or future.result() for future in futures]


def test_competing_claimants_serialize_through_one_cas_boundary() -> None:
    context = Context()
    context.generation()
    other = context.add_claimant("claimant-evidence:2", claimant_id="claimant-2")
    requests = (
        context.request(
            WorkClaimOperation.CLAIM, expected_lineage_version=1, idempotency_key="race-1",
            semantic_at=NOW + timedelta(seconds=1),
        ),
        context.request(
            WorkClaimOperation.CLAIM, expected_lineage_version=1, idempotency_key="race-2",
            claimant=other, semantic_at=NOW + timedelta(seconds=1),
        ),
    )
    results = _race([lambda request=request: context.service.evaluate(request) for request in requests])
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, WorkClaimVersionConflict) for value in results) == 1
    assert len(context.repository.history(requests[0].lineage_key)) == 2


@pytest.mark.parametrize("left", [WorkClaimOperation.RELEASE, WorkClaimOperation.EXPIRE])
def test_claim_versus_terminal_transition_has_one_successor(left) -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    semantic = accepted.expires_at if left is WorkClaimOperation.EXPIRE else NOW + timedelta(minutes=1)
    kwargs = {"release_reason": "voluntary"} if left is WorkClaimOperation.RELEASE else {}
    terminal = context.request(
        left, expected_lineage_version=2, idempotency_key=f"{left.value}-race",
        semantic_at=semantic, **kwargs,
    )
    claim = context.request(
        WorkClaimOperation.CLAIM, expected_lineage_version=2, idempotency_key="late-claim",
        semantic_at=semantic,
    )
    results = _race([lambda: context.service.evaluate(terminal), lambda: context.service.evaluate(claim)])
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert len(context.repository.history(claim.lineage_key)) == 3


def test_release_versus_expiry_has_one_successor() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    release = context.request(
        WorkClaimOperation.RELEASE, expected_lineage_version=2, idempotency_key="release-race",
        semantic_at=accepted.expires_at, release_reason="voluntary",
    )
    expiry = context.request(
        WorkClaimOperation.EXPIRE, expected_lineage_version=2, idempotency_key="expiry-race",
        semantic_at=accepted.expires_at,
    )
    results = _race([lambda: context.service.evaluate(release), lambda: context.service.evaluate(expiry)])
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, WorkClaimVersionConflict) for value in results) == 1


def test_competing_next_generation_creation_has_one_successor() -> None:
    context = Context()
    context.generation()
    context.accept()
    context.evaluate(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=2,
        idempotency_key="release-1",
        semantic_at=NOW + timedelta(minutes=1),
        release_reason="voluntary",
    )
    requests = (
        context.request(
            WorkClaimOperation.CREATE_GENERATION, expected_lineage_version=3,
            idempotency_key="generation-race-1", semantic_at=NOW + timedelta(minutes=2),
        ),
        context.request(
            WorkClaimOperation.CREATE_GENERATION, expected_lineage_version=3,
            idempotency_key="generation-race-2", semantic_at=NOW + timedelta(minutes=2),
        ),
    )
    results = _race([lambda request=request: context.service.evaluate(request) for request in requests])
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, WorkClaimVersionConflict) for value in results) == 1


def test_later_generation_creation_racing_with_late_lifecycle_write_is_serialized() -> None:
    context = Context()
    context.generation()
    context.accept()
    context.evaluate(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=2,
        idempotency_key="release-1",
        semantic_at=NOW + timedelta(minutes=1),
        release_reason="voluntary",
    )
    generation = context.request(
        WorkClaimOperation.CREATE_GENERATION,
        expected_lineage_version=3,
        idempotency_key="generation-2",
        semantic_at=NOW + timedelta(minutes=2),
    )
    late_release = context.request(
        WorkClaimOperation.RELEASE,
        expected_lineage_version=3,
        idempotency_key="late-release",
        semantic_at=NOW + timedelta(minutes=2),
        release_reason="late",
    )
    results = _race(
        [lambda: context.service.evaluate(generation), lambda: context.service.evaluate(late_release)]
    )
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert len(context.repository.history(generation.lineage_key)) == 4


def test_atomic_publication_failure_exposes_no_empty_state() -> None:
    repository = FailingRepository()
    context = Context(repository=repository)
    request = context.request()
    with pytest.raises(WorkClaimPersistenceFailure):
        context.service.evaluate(request)
    assert repository.history(request.lineage_key) == ()
    assert repository.current(request.lineage_key) is None


def test_atomic_publication_failure_preserves_prior_state() -> None:
    repository = FailingRepository()
    repository.fail = False
    context = Context(repository=repository)
    generation = context.generation()
    repository.fail = True
    with pytest.raises(WorkClaimPersistenceFailure):
        context.accept()
    assert repository.current(context.request().lineage_key) == generation
    assert len(repository.history(context.request().lineage_key)) == 1


def test_canonical_serialization_is_utf8_normalized_and_order_independent() -> None:
    left = canonical_json({"b": [2, 1], "a": "e\u0301"}).encode("utf-8")
    right = canonical_json({"a": "é", "b": [2, 1]}).encode("utf-8")
    assert left == right
    assert b"\\u" not in left


def test_reconstruction_uses_authoritative_sources_and_is_deterministic() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    rebuilt = context.service.reconstruct(
        accepted.event_id, organization_id="org-1", workload_context_id="workload-1"
    )
    assert rebuilt == accepted
    assert rebuilt.canonical_event_digest == accepted.canonical_event_digest


def test_history_is_append_only_and_returns_immutable_records() -> None:
    context = Context()
    generation = context.generation()
    accepted = context.accept()
    history = context.service.history(
        context.request().lineage_key,
        organization_id="org-1",
        workload_context_id="workload-1",
    )
    assert history == (generation, accepted)
    with pytest.raises(FrozenInstanceError):
        history[0].generation = 9  # type: ignore[misc]


def test_digest_and_authoritative_evidence_tampering_fail_closed() -> None:
    context = Context()
    generation = context.generation()
    record = context.repository.record(generation.event_id)
    assert record is not None
    context.claimants._items[context.claimant.evidence_id] = replace(
        context.claimant, canonical_digest="f" * 64
    )
    with pytest.raises(WorkClaimDigestMismatch):
        context.service.reconstruct(
            generation.event_id, organization_id="org-1", workload_context_id="workload-1"
        )


def test_retained_event_digest_mismatch_fails_closed() -> None:
    context = Context()
    generation = context.generation()
    record = context.repository.record(generation.event_id)
    assert record is not None
    with pytest.raises(WorkClaimDigestMismatch):
        verify_recorded_content(
            record.event,
            record.canonical_input_content,
            record.canonical_event_content + b"tampered",
        )


def test_reconstruction_divergence_fails_without_mutation(monkeypatch) -> None:
    context = Context()
    generation = context.generation()
    original_history = context.repository.history(context.request().lineage_key)
    import app.runtime.work_claim.service as service_module

    original_builder = service_module.build_work_claim_event

    def divergent_builder(*args, **kwargs):
        event, input_content, event_content = original_builder(*args, **kwargs)
        return replace(event, reason_codes=("DIVERGED",)), input_content, event_content

    monkeypatch.setattr(service_module, "build_work_claim_event", divergent_builder)
    with pytest.raises(WorkClaimReplayDiverged):
        context.service.reconstruct(
            generation.event_id,
            organization_id="org-1",
            workload_context_id="workload-1",
        )
    assert context.repository.history(context.request().lineage_key) == original_history


def test_reconstruction_detects_lineage_generation_and_fence_divergence() -> None:
    context = Context()
    generation = context.generation()
    accepted = context.accept()
    state = _advance_state(WorkClaimDerivedState(), generation)
    with pytest.raises(WorkClaimReconstructionFailed, match="version"):
        _advance_state(state, replace(accepted, lineage_version=4))
    with pytest.raises(WorkClaimReconstructionFailed, match="fence"):
        _advance_state(state, replace(accepted, fence=3))
    with pytest.raises(WorkClaimReconstructionFailed, match="generation"):
        _advance_state(state, replace(accepted, generation=2))
    accepted_state = _advance_state(state, accepted)
    with pytest.raises(WorkClaimReconstructionFailed, match="multiple accepted"):
        _advance_state(
            accepted_state,
            replace(accepted, lineage_version=3, fence=2, event_id="b" * 64),
        )


def test_reconstruction_detects_skipped_generation_and_generation_before_termination() -> None:
    context = Context()
    first = context.generation()
    state = _advance_state(WorkClaimDerivedState(), first)
    with pytest.raises(WorkClaimReconstructionFailed, match="generation"):
        _advance_state(state, replace(first, lineage_version=2, generation=3))
    with pytest.raises(WorkClaimReconstructionFailed, match="termination"):
        _advance_state(state, replace(first, lineage_version=2, generation=2))


def test_absent_and_foreign_dispatch_evidence_are_indistinguishable() -> None:
    context = Context()
    absent = context.request(dispatch_decision_id="dispatch:absent")
    foreign = Context(organization_id="org-2")
    context.dispatches.retain(foreign.dispatch_record)
    foreign_request = context.request(
        dispatch_decision_id=foreign.dispatch_record.decision.dispatch_decision_id,
        dispatch_decision_digest=foreign.dispatch_record.decision.canonical_decision_digest,
    )
    for request in (absent, foreign_request):
        with pytest.raises(WorkClaimEvidenceUnavailable, match=f"^{SAFE_EVIDENCE_MESSAGE}$"):
            context.service.evaluate(request)
    assert context.repository.history(context.request().lineage_key) == ()


def test_absent_and_foreign_claimant_evidence_are_indistinguishable() -> None:
    context = Context()
    absent = context.request(
        claimant_evidence_id="claimant:absent", claimant_evidence_digest="b" * 64
    )
    foreign = context.add_claimant(
        "claimant:foreign", claimant_id="foreign", organization_id="org-2"
    )
    foreign_request = context.request(claimant=foreign)
    for request in (absent, foreign_request):
        with pytest.raises(WorkClaimEvidenceUnavailable, match=f"^{SAFE_EVIDENCE_MESSAGE}$"):
            context.service.evaluate(request)
    assert context.repository.history(context.request().lineage_key) == ()


def test_organization_and_workload_isolation_hide_existing_events() -> None:
    context = Context()
    event = context.generation()
    with pytest.raises(WorkClaimNotFound):
        context.service.get(event.event_id, organization_id="org-2", workload_context_id="workload-1")
    with pytest.raises(WorkClaimNotFound):
        context.service.get(event.event_id, organization_id="org-1", workload_context_id="workload-2")


def test_unsupported_policy_and_invalid_dispatch_fail_without_domain_outcome() -> None:
    context = Context()
    with pytest.raises(WorkClaimVersionUnsupported):
        context.evaluate(claim_policy_version="unsupported")
    with pytest.raises(WorkClaimDigestMismatch):
        context.evaluate(dispatch_decision_digest="f" * 64)
    assert context.repository.history(context.request().lineage_key) == ()


def test_no_downstream_runtime_behavior_or_api_is_exposed() -> None:
    context = Context()
    context.generation()
    accepted = context.accept()
    assert accepted.outcome is WorkClaimOutcome.ACCEPTED
    public = set(dir(context.service))
    for forbidden in (
        "execute", "invoke_worker", "publish_queue", "monitor", "complete", "retry",
        "schedule", "orchestrate", "create_attempt",
    ):
        assert forbidden not in public
