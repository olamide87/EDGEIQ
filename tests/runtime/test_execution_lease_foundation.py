from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.execution_lease.canonical import canonical_json
from app.runtime.execution_lease.domain import (
    ExecutionLeaseDigestMismatch,
    ExecutionLeaseEvidenceUnavailable,
    ExecutionLeaseIdempotencyConflict,
    ExecutionLeaseIllegalTransition,
    ExecutionLeaseInvalid,
    ExecutionLeaseNotFound,
    ExecutionLeasePersistenceFailure,
    ExecutionLeaseReconstructionFailed,
    ExecutionLeaseReplayDiverged,
    ExecutionLeaseRequest,
    ExecutionLeaseVersionConflict,
    ExecutionLeaseVersionUnsupported,
    LeaseEvaluationOutcome,
    LeaseEventType,
    LeaseOperation,
    LeasePermission,
)
from app.runtime.execution_lease.evidence import (
    authorization_source,
    build_authorization_evidence,
    build_opaque_revocation_evidence,
    revocation_source,
)
from app.runtime.execution_lease.policy import EXECUTION_LEASE_POLICY_V1
from app.runtime.execution_lease.serialization import (
    lease_identity,
    lineage_identity,
    verify_recorded_content,
)
from app.runtime.execution_lease.service import (
    InMemoryExecutionLeaseRepository,
    LeaseDerivedState,
    ExecutionLeaseService,
    _advance_state,
)

NOW = datetime(2026, 8, 19, 12, tzinfo=timezone.utc)
SAFE_EVIDENCE_MESSAGE = "Required Execution Lease evidence was not found."


class FailingRepository(InMemoryExecutionLeaseRepository):
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
        self.authorizations = authorization_source()
        self.revocations = revocation_source()
        self.authorization = self.add_authorization("authorization:1")
        self.repository = repository or InMemoryExecutionLeaseRepository()
        self.service = ExecutionLeaseService(
            authorizations=self.authorizations,
            revocations=self.revocations,
            repository=self.repository,
        )

    def add_authorization(
        self,
        identity,
        *,
        organization_id=None,
        workload_context_id=None,
        permissions=(LeasePermission.OFFER_WORK_ITEM, LeasePermission.INITIATE_WORK_ITEM_EXECUTION),
        approved=True,
        plan_id="plan:1",
        work_item_id="work-item:1",
        effective_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=4),
        history_boundary=None,
    ):
        evidence = build_authorization_evidence(
            authorization_id=identity,
            organization_id=organization_id or self.organization_id,
            workload_context_id=workload_context_id or self.workload_context_id,
            principal_id="principal:1",
            plan_id=plan_id,
            work_item_id=work_item_id,
            permission_ceiling=permissions,
            approved=approved,
            evaluated_at=NOW - timedelta(minutes=1),
            effective_at=effective_at,
            expires_at=expires_at,
            history_boundary=history_boundary or f"history:{identity}",
        )
        self.authorizations.retain(evidence)
        return evidence

    def add_revocation(self, prior, identity="revocation:1", *, effective_at=NOW + timedelta(hours=1), organization_id=None, workload_context_id=None):
        evidence = build_opaque_revocation_evidence(
            evidence_id=identity,
            organization_id=organization_id or self.organization_id,
            workload_context_id=workload_context_id or self.workload_context_id,
            plan_id="plan:1",
            work_item_id="work-item:1",
            permission_family="work-item-execution.v1",
            target_lease_id=prior.lease_id,
            target_event_id=prior.event_id,
            effective_at=effective_at,
        )
        self.revocations.retain(evidence)
        return evidence

    def request(self, operation=LeaseOperation.GRANT, **changes):
        authorization = changes.pop("authorization", self.authorization)
        values = {
            "operation": operation,
            "organization_id": self.organization_id,
            "workload_context_id": self.workload_context_id,
            "plan_id": "plan:1",
            "work_item_id": "work-item:1",
            "permission_family": "work-item-execution.v1",
            "requested_permissions": (LeasePermission.OFFER_WORK_ITEM,),
            "authorization_evidence_id": authorization.authorization_id,
            "authorization_evidence_digest": authorization.canonical_digest,
            "authorization_history_boundary": authorization.history_boundary,
            "prior_event_id": None,
            "revocation_evidence_id": None,
            "revocation_evidence_digest": None,
            "effective_at": NOW,
            "expires_at": NOW + timedelta(hours=2),
            "evaluation_at": NOW,
            "clock_source_id": "trusted-clock",
            "clock_source_version": "clock.v1",
            "lease_policy_id": EXECUTION_LEASE_POLICY_V1.policy_id,
            "lease_policy_version": EXECUTION_LEASE_POLICY_V1.policy_version,
            "lease_policy_digest": EXECUTION_LEASE_POLICY_V1.canonical_digest,
            "configuration_version": "execution-lease-config.v1",
            "expected_lineage_version": 0,
            "idempotency_key": "grant-1",
        }
        values.update(changes)
        return ExecutionLeaseRequest(**values)

    def grant(self, **changes):
        return self.service.evaluate(self.request(**changes)).event

    def renew(self, prior, *, authorization=None, **changes):
        authorization = authorization or self.add_authorization(f"authorization:renew:{prior.lineage_version}")
        values = {
            "authorization": authorization,
            "prior_event_id": prior.event_id,
            "expected_lineage_version": prior.lineage_version,
            "idempotency_key": f"renew-{prior.lineage_version}",
            "effective_at": NOW + timedelta(minutes=prior.lineage_version),
            "expires_at": NOW + timedelta(hours=3),
            "evaluation_at": NOW + timedelta(minutes=prior.lineage_version),
        }
        values.update(changes)
        return self.service.evaluate(self.request(LeaseOperation.RENEW, **values)).event

    def supersede(self, prior, **changes):
        authorization = changes.pop("authorization", self.add_authorization(f"authorization:supersede:{prior.lineage_version}"))
        values = {
            "authorization": authorization,
            "prior_event_id": prior.event_id,
            "expected_lineage_version": prior.lineage_version,
            "idempotency_key": f"supersede-{prior.lineage_version}",
            "effective_at": NOW + timedelta(minutes=prior.lineage_version),
            "expires_at": NOW + timedelta(hours=3),
            "evaluation_at": NOW + timedelta(minutes=prior.lineage_version),
        }
        values.update(changes)
        return self.service.evaluate(self.request(LeaseOperation.SUPERSEDE, **values)).event

    def revoke(self, prior, **changes):
        directive = changes.pop("directive", self.add_revocation(prior, effective_at=NOW + timedelta(minutes=prior.lineage_version)))
        values = {
            "authorization_evidence_id": None,
            "authorization_evidence_digest": None,
            "authorization_history_boundary": None,
            "requested_permissions": (),
            "prior_event_id": prior.event_id,
            "revocation_evidence_id": directive.evidence_id,
            "revocation_evidence_digest": directive.canonical_digest,
            "effective_at": directive.effective_at,
            "expires_at": None,
            "evaluation_at": directive.effective_at,
            "expected_lineage_version": prior.lineage_version,
            "idempotency_key": f"revoke-{prior.lineage_version}",
        }
        values.update(changes)
        return self.service.evaluate(self.request(LeaseOperation.REVOKE, **values)).event


def test_valid_initial_grant_assigns_owner_generation_and_version() -> None:
    context = Context()
    event = context.grant()
    assert event.event_type is LeaseEventType.GRANTED
    assert event.generation == 1
    assert event.lineage_version == 1
    assert event.lease_id == lease_identity(event.lineage_id, 1)


def test_lineage_key_contains_permission_family_but_not_generation() -> None:
    context = Context()
    request = context.request()
    assert request.lineage_key == ("org-1", "workload-1", "plan:1", "work-item:1", "work-item-execution.v1")
    assert lineage_identity(request.lineage_key) == lineage_identity(context.request().lineage_key)
    changed_key = (*request.lineage_key[:-1], "different-family.v1")
    assert lineage_identity(changed_key) != lineage_identity(request.lineage_key)


def test_permission_family_is_closed_and_versioned() -> None:
    context = Context()
    with pytest.raises(ExecutionLeaseVersionUnsupported, match="permission family"):
        context.request(permission_family="invented-family.v1")


def test_public_input_has_no_owner_authored_results() -> None:
    names = set(ExecutionLeaseRequest.__dataclass_fields__)
    for forbidden in ("generation", "lineage_version", "event_id", "lease_id", "canonical_digest", "applicable", "active"):
        assert forbidden not in names


def test_permission_sorting_is_canonical_and_duplicates_fail() -> None:
    context = Context()
    request = context.request(requested_permissions=(LeasePermission.INITIATE_WORK_ITEM_EXECUTION, LeasePermission.OFFER_WORK_ITEM))
    assert request.requested_permissions == (LeasePermission.INITIATE_WORK_ITEM_EXECUTION, LeasePermission.OFFER_WORK_ITEM)
    with pytest.raises(ExecutionLeaseInvalid, match="unique"):
        context.request(requested_permissions=(LeasePermission.OFFER_WORK_ITEM, LeasePermission.OFFER_WORK_ITEM))


def test_unknown_permission_fails_closed() -> None:
    context = Context()
    with pytest.raises(ExecutionLeaseInvalid, match="Unknown"):
        context.request(requested_permissions=("EXECUTE_ANYTHING",))


def test_authorization_permission_ceiling_and_scope_narrowing() -> None:
    context = Context()
    narrow = context.add_authorization("authorization:narrow", permissions=(LeasePermission.OFFER_WORK_ITEM,))
    context.grant(authorization=narrow)
    other = Context()
    with pytest.raises(ExecutionLeaseInvalid, match="exceed"):
        other.grant(requested_permissions=(LeasePermission.INITIATE_WORK_ITEM_EXECUTION,), authorization=other.add_authorization("authorization:offer", permissions=(LeasePermission.OFFER_WORK_ITEM,)))


@pytest.mark.parametrize("field,value", [("plan_id", "plan:other"), ("work_item_id", "work-item:other")])
def test_authorization_scope_mismatch_fails(field, value) -> None:
    context = Context()
    with pytest.raises(ExecutionLeaseInvalid, match="scope"):
        context.grant(**{field: value})


def test_denied_and_expired_authorization_fail() -> None:
    context = Context()
    denied = context.add_authorization("authorization:denied", approved=False)
    with pytest.raises(ExecutionLeaseInvalid, match="affirmative"):
        context.grant(authorization=denied)
    expired = context.add_authorization("authorization:expired", expires_at=NOW)
    with pytest.raises(ExecutionLeaseInvalid, match="not applicable"):
        context.grant(authorization=expired)


def test_renewal_uses_fresh_authorization_same_generation_new_version() -> None:
    context = Context()
    granted = context.grant()
    renewed = context.renew(granted)
    assert renewed.event_type is LeaseEventType.RENEWED
    assert renewed.generation == granted.generation == 1
    assert renewed.lease_id == granted.lease_id
    assert renewed.lineage_version == 2
    assert renewed.authorization_reference != granted.authorization_reference


def test_renewal_rejects_reused_authorization_evidence() -> None:
    context = Context()
    granted = context.grant()
    with pytest.raises(ExecutionLeaseInvalid, match="fresh"):
        context.renew(granted, authorization=context.authorization)


def test_renewal_cannot_broaden_old_or_fresh_authority() -> None:
    context = Context()
    granted = context.grant()
    with pytest.raises(ExecutionLeaseInvalid, match="broaden"):
        context.renew(granted, requested_permissions=(LeasePermission.OFFER_WORK_ITEM, LeasePermission.INITIATE_WORK_ITEM_EXECUTION))


def test_renewal_cannot_backdate_authority() -> None:
    context = Context()
    granted = context.grant(effective_at=NOW + timedelta(minutes=10), evaluation_at=NOW)
    with pytest.raises(ExecutionLeaseInvalid, match="backdate"):
        context.renew(granted, effective_at=NOW + timedelta(minutes=5), evaluation_at=NOW + timedelta(minutes=10))


def test_supersession_assigns_next_generation_and_preserves_lineage() -> None:
    context = Context()
    granted = context.grant()
    superseded = context.supersede(granted)
    assert superseded.event_type is LeaseEventType.SUPERSEDED
    assert superseded.generation == 2
    assert superseded.lineage_id == granted.lineage_id
    assert superseded.lease_id != granted.lease_id
    assert superseded.superseded_lease_id == granted.lease_id
    assert context.renew(superseded).generation == 2


def test_generation_is_monotonic_across_repeated_active_supersession() -> None:
    context = Context()
    first = context.grant()
    second = context.supersede(first)
    third = context.supersede(second)
    assert (first.generation, second.generation, third.generation) == (1, 2, 3)
    assert (first.lineage_version, second.lineage_version, third.lineage_version) == (1, 2, 3)


def test_self_consistent_opaque_revocation_cannot_create_authority() -> None:
    context = Context()
    granted = context.grant()
    before = context.repository._state
    with pytest.raises(ExecutionLeaseIllegalTransition, match="authority remains unresolved"):
        context.revoke(granted)
    assert context.repository._state is before
    assert context.service.reconstruct(
        granted.event_id, organization_id="org-1", workload_context_id="workload-1"
    ) == granted


def test_revocation_scope_and_digest_fail_closed() -> None:
    context = Context()
    granted = context.grant()
    wrong = build_opaque_revocation_evidence(
        evidence_id="revocation:wrong", organization_id="org-1", workload_context_id="workload-1",
        plan_id="plan:other", work_item_id="work-item:1", permission_family="work-item-execution.v1",
        target_lease_id=granted.lease_id, target_event_id=granted.event_id, effective_at=NOW,
    )
    context.revocations.retain(wrong)
    before = context.repository._state
    with pytest.raises(ExecutionLeaseInvalid, match="scope"):
        context.revoke(granted, directive=wrong)
    assert context.repository._state is before

    valid = context.add_revocation(granted, "revocation:corrupt", effective_at=NOW)
    context.revocations._items[valid.evidence_id] = replace(valid, canonical_digest="f" * 64)
    with pytest.raises(ExecutionLeaseDigestMismatch, match="canonical verification"):
        context.revoke(granted, directive=replace(valid, canonical_digest="f" * 64))
    assert context.repository._state is before


def test_half_open_applicability_and_wall_clock_independence() -> None:
    context = Context()
    event = context.grant()
    key = context.request().lineage_key
    assert context.service.applicable(key, organization_id="org-1", workload_context_id="workload-1", evaluation_at=event.effective_at)
    assert context.service.applicable(key, organization_id="org-1", workload_context_id="workload-1", evaluation_at=event.expires_at - timedelta(microseconds=1))
    assert not context.service.applicable(key, organization_id="org-1", workload_context_id="workload-1", evaluation_at=event.expires_at)


def test_equivalent_retry_converges_and_conflicting_reuse_fails() -> None:
    context = Context()
    request = context.request()
    first = context.service.evaluate(request)
    state_after_first = context.repository._state
    second = context.service.evaluate(request)
    assert second.outcome is LeaseEvaluationOutcome.EXISTING_EQUIVALENT
    assert second.event is first.event
    assert context.repository._state is state_after_first
    assert len(state_after_first.streams) == len(state_after_first.by_id) == len(state_after_first.idempotency) == len(state_after_first.current) == 1
    with pytest.raises(ExecutionLeaseIdempotencyConflict):
        context.service.evaluate(replace(request, expires_at=NOW + timedelta(hours=1)))
    assert len(context.repository.history(request.lineage_key)) == 1


def test_conflicting_idempotency_covers_every_authoritative_dimension() -> None:
    context = Context()
    granted = context.grant()
    authorization = context.add_authorization("authorization:renew:idempotency")
    request = context.request(
        LeaseOperation.RENEW,
        authorization=authorization,
        prior_event_id=granted.event_id,
        expected_lineage_version=1,
        idempotency_key="renew-idempotency",
        effective_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=3),
        evaluation_at=NOW + timedelta(minutes=1),
    )
    context.service.evaluate(request)
    other = context.add_authorization("authorization:renew:other")
    variants = (
        replace(request, authorization_evidence_id=other.authorization_id, authorization_evidence_digest=other.canonical_digest, authorization_history_boundary=other.history_boundary),
        replace(request, authorization_evidence_digest="f" * 64),
        replace(request, requested_permissions=(LeasePermission.INITIATE_WORK_ITEM_EXECUTION,)),
        replace(request, effective_at=request.effective_at + timedelta(seconds=1)),
        replace(request, expires_at=request.expires_at - timedelta(seconds=1)),
        replace(request, prior_event_id="different-causal-event"),
        replace(request, lease_policy_version="unsupported-policy-version"),
        replace(request, authorization_history_boundary="different-history-boundary"),
        replace(request, configuration_version="different-config.v1"),
    )
    committed = context.repository._state
    for variant in variants:
        with pytest.raises(ExecutionLeaseIdempotencyConflict):
            context.service.evaluate(variant)
        assert context.repository._state is committed


def test_stale_expected_version_appends_nothing() -> None:
    context = Context()
    granted = context.grant()
    request = context.request(LeaseOperation.RENEW, authorization=context.add_authorization("authorization:fresh"), prior_event_id=granted.event_id, expected_lineage_version=0, idempotency_key="stale")
    with pytest.raises(ExecutionLeaseVersionConflict):
        context.service.evaluate(request)
    assert len(context.repository.history(request.lineage_key)) == 1


def _race(*calls):
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
    return [future.exception() or future.result() for future in futures]


def test_concurrent_initial_grant_has_one_successor() -> None:
    context = Context()
    left, right = context.request(idempotency_key="left"), context.request(idempotency_key="right")
    results = _race(lambda: context.service.evaluate(left), lambda: context.service.evaluate(right))
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, ExecutionLeaseVersionConflict) for value in results) == 1
    state = context.repository._state
    assert len(state.streams[left.lineage_key]) == 1
    assert len(state.by_id) == len(state.current) == len(state.idempotency) == 1
    winner = next(value.event for value in results if not isinstance(value, Exception))
    assert state.current[left.lineage_key] is winner
    assert state.by_id[winner.event_id].event is winner
    assert winner.generation == winner.lineage_version == 1


def test_equivalent_concurrent_retry_converges() -> None:
    context = Context()
    request = context.request()
    results = _race(lambda: context.service.evaluate(request), lambda: context.service.evaluate(request))
    assert results[0].event is results[1].event
    assert len(context.repository.history(request.lineage_key)) == 1


@pytest.mark.parametrize("right_operation", [LeaseOperation.RENEW, LeaseOperation.SUPERSEDE])
def test_concurrent_lifecycle_operations_have_one_successor(right_operation) -> None:
    context = Context()
    granted = context.grant()
    fresh1 = context.add_authorization("authorization:race:1")
    left = context.request(LeaseOperation.RENEW, authorization=fresh1, prior_event_id=granted.event_id, expected_lineage_version=1, idempotency_key="race-left", effective_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(hours=3), evaluation_at=NOW + timedelta(minutes=1))
    fresh2 = context.add_authorization("authorization:race:2")
    right = context.request(right_operation, authorization=fresh2, prior_event_id=granted.event_id, expected_lineage_version=1, idempotency_key="race-right", effective_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(hours=3), evaluation_at=NOW + timedelta(minutes=1))
    results = _race(lambda: context.service.evaluate(left), lambda: context.service.evaluate(right))
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, ExecutionLeaseVersionConflict) for value in results) == 1
    state = context.repository._state
    history = state.streams[left.lineage_key]
    assert len(history) == 2
    assert history[0].event is granted
    successor = next(value.event for value in results if not isinstance(value, Exception))
    assert history[1].event is successor
    assert state.current[left.lineage_key] is successor
    assert len(state.by_id) == 2 and len(state.idempotency) == 2
    assert successor.lineage_version == 2
    assert successor.generation in (1, 2)


def test_atomic_publication_failure_exposes_no_empty_state() -> None:
    repository = FailingRepository()
    context = Context(repository=repository)
    request = context.request()
    before = repository._state
    with pytest.raises(ExecutionLeasePersistenceFailure):
        context.service.evaluate(request)
    assert repository._state is before
    assert dict(before.streams) == {}
    assert dict(before.by_id) == {}
    assert dict(before.idempotency) == {}
    assert dict(before.current) == {}
    assert repository.history(request.lineage_key) == ()
    assert repository.current(request.lineage_key) is None


def test_atomic_publication_failure_preserves_prior_state() -> None:
    repository = FailingRepository()
    repository.fail = False
    context = Context(repository=repository)
    granted = context.grant()
    before = repository._state
    repository.fail = True
    with pytest.raises(ExecutionLeasePersistenceFailure):
        context.renew(granted)
    assert repository._state is before
    assert len(before.streams[context.request().lineage_key]) == 1
    assert len(before.by_id) == len(before.idempotency) == len(before.current) == 1
    assert before.current[context.request().lineage_key] is granted


def test_history_is_append_only_and_events_are_immutable() -> None:
    context = Context()
    granted = context.grant()
    renewed = context.renew(granted)
    history = context.service.history(context.request().lineage_key, organization_id="org-1", workload_context_id="workload-1")
    assert history == (granted, renewed)
    with pytest.raises(FrozenInstanceError):
        history[0].generation = 9  # type: ignore[misc]


def test_canonical_serialization_is_utf8_normalized_and_order_independent() -> None:
    left = canonical_json({"b": [2, 1], "a": "e\u0301"}).encode("utf-8")
    right = canonical_json({"a": "é", "b": [2, 1]}).encode("utf-8")
    assert left == right
    assert b"\\u" not in left


def test_deterministic_identities_and_reconstruction() -> None:
    context = Context()
    granted = context.grant()
    rebuilt = context.service.reconstruct(granted.event_id, organization_id="org-1", workload_context_id="workload-1")
    assert rebuilt == granted
    assert rebuilt.event_id == granted.event_id
    assert rebuilt.canonical_event_digest == granted.canonical_event_digest


def test_recorded_digest_mismatch_fails_closed() -> None:
    context = Context()
    event = context.grant()
    record = context.repository.record(event.event_id)
    assert record is not None
    with pytest.raises(ExecutionLeaseDigestMismatch):
        verify_recorded_content(event, record.canonical_input_content, record.canonical_event_content + b"tampered")


def test_authoritative_evidence_tampering_fails_reconstruction() -> None:
    context = Context()
    event = context.grant()
    context.authorizations._items[context.authorization.authorization_id] = replace(context.authorization, canonical_digest="f" * 64)
    with pytest.raises(ExecutionLeaseDigestMismatch):
        context.service.reconstruct(event.event_id, organization_id="org-1", workload_context_id="workload-1")


def test_reconstruction_divergence_fails_without_mutation(monkeypatch) -> None:
    context = Context()
    event = context.grant()
    history = context.repository.history(context.request().lineage_key)
    import app.runtime.execution_lease.service as service_module
    original = service_module.build_execution_lease_event

    def divergent(*args, **kwargs):
        rebuilt, input_content, event_content = original(*args, **kwargs)
        return replace(rebuilt, recorded_at=rebuilt.recorded_at + timedelta(seconds=1)), input_content, event_content

    monkeypatch.setattr(service_module, "build_execution_lease_event", divergent)
    with pytest.raises(ExecutionLeaseReplayDiverged):
        context.service.reconstruct(event.event_id, organization_id="org-1", workload_context_id="workload-1")
    assert context.repository.history(context.request().lineage_key) == history


def test_reconstruction_detects_version_generation_and_transition_divergence() -> None:
    context = Context()
    granted = context.grant()
    state = _advance_state(LeaseDerivedState(), granted)
    renewed = context.renew(granted)
    with pytest.raises(ExecutionLeaseReconstructionFailed, match="version"):
        _advance_state(state, replace(renewed, lineage_version=4))
    with pytest.raises(ExecutionLeaseReconstructionFailed, match="generation"):
        _advance_state(state, replace(renewed, generation=2))
    with pytest.raises(ExecutionLeaseReconstructionFailed, match="causality"):
        _advance_state(state, replace(renewed, prior_event_id="wrong"))


def test_absent_and_foreign_authorization_are_indistinguishable() -> None:
    context = Context()
    absent = context.request(authorization_evidence_id="authorization:absent", authorization_evidence_digest="b" * 64)
    foreign_org = context.add_authorization("authorization:foreign-org", organization_id="org-2")
    foreign_workload = context.add_authorization("authorization:foreign-workload", workload_context_id="workload-2")
    requests = (absent, context.request(authorization=foreign_org), context.request(authorization=foreign_workload))
    before = context.repository._state
    for request in requests:
        with pytest.raises(ExecutionLeaseEvidenceUnavailable, match=f"^{SAFE_EVIDENCE_MESSAGE}$") as caught:
            context.service.evaluate(request)
        assert caught.value.code == "ExecutionLeaseEvidenceUnavailable"
        assert context.repository._state is before


def test_absent_and_foreign_revocation_are_indistinguishable() -> None:
    context = Context()
    granted = context.grant()
    foreign_org = context.add_revocation(granted, "revocation:foreign-org", organization_id="org-2", effective_at=NOW + timedelta(minutes=1))
    foreign_workload = context.add_revocation(granted, "revocation:foreign-workload", workload_context_id="workload-2", effective_at=NOW + timedelta(minutes=1))
    requests = (
        context.request(LeaseOperation.REVOKE, authorization_evidence_id=None, authorization_evidence_digest=None, authorization_history_boundary=None, requested_permissions=(), prior_event_id=granted.event_id, revocation_evidence_id="revocation:absent", revocation_evidence_digest="b" * 64, effective_at=NOW + timedelta(minutes=1), expires_at=None, evaluation_at=NOW + timedelta(minutes=1), expected_lineage_version=1, idempotency_key="absent"),
        context.request(LeaseOperation.REVOKE, authorization_evidence_id=None, authorization_evidence_digest=None, authorization_history_boundary=None, requested_permissions=(), prior_event_id=granted.event_id, revocation_evidence_id=foreign_org.evidence_id, revocation_evidence_digest=foreign_org.canonical_digest, effective_at=foreign_org.effective_at, expires_at=None, evaluation_at=foreign_org.effective_at, expected_lineage_version=1, idempotency_key="foreign-org"),
        context.request(LeaseOperation.REVOKE, authorization_evidence_id=None, authorization_evidence_digest=None, authorization_history_boundary=None, requested_permissions=(), prior_event_id=granted.event_id, revocation_evidence_id=foreign_workload.evidence_id, revocation_evidence_digest=foreign_workload.canonical_digest, effective_at=foreign_workload.effective_at, expires_at=None, evaluation_at=foreign_workload.effective_at, expected_lineage_version=1, idempotency_key="foreign-workload"),
    )
    before = context.repository._state
    for request in requests:
        with pytest.raises(ExecutionLeaseEvidenceUnavailable, match=f"^{SAFE_EVIDENCE_MESSAGE}$") as caught:
            context.service.evaluate(request)
        assert caught.value.code == "ExecutionLeaseEvidenceUnavailable"
        assert context.repository._state is before


def test_organization_and_workload_isolation_hide_events() -> None:
    context = Context()
    event = context.grant()
    for organization, workload in (("org-2", "workload-1"), ("org-1", "workload-2")):
        with pytest.raises(ExecutionLeaseNotFound):
            context.service.get(event.event_id, organization_id=organization, workload_context_id=workload)


def test_unsupported_policy_and_versions_fail_closed() -> None:
    context = Context()
    with pytest.raises(ExecutionLeaseVersionUnsupported):
        context.grant(lease_policy_version="unsupported")
    with pytest.raises(ExecutionLeaseVersionUnsupported):
        context.request(schema_version="unsupported")


def test_lease_possession_has_no_downstream_behavior() -> None:
    context = Context()
    event = context.grant()
    assert event.permissions == (LeasePermission.OFFER_WORK_ITEM,)
    public = set(dir(context.service))
    for forbidden in ("dispatch", "execute", "create_attempt", "publish_queue", "invoke_provider", "monitor", "complete", "retry", "schedule", "orchestrate"):
        assert forbidden not in public
