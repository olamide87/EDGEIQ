import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from app.runtime.dispatch_decision.domain import (
    ArtifactReference,
    DispatchDecisionDigestMismatch,
    DispatchDecisionIdempotencyConflict,
    DispatchDecisionInvalid,
    DispatchDecisionNotFound,
    DispatchDecisionOutcome,
    DispatchDecisionReplayDiverged,
    DispatchDecisionVersionConflict,
    DispatchEvaluationInput,
    DispatchEvaluationOutcome,
    DispatchPolicy,
)
from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.dispatch_decision.serialization import (
    DECISION_DIGEST_NAMESPACE,
    canonical_json,
)
from app.runtime.dispatch_decision.service import DispatchDecisionService


NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def reference(label: str, *, organization_id: str = "org-1") -> ArtifactReference:
    return ArtifactReference(
        artifact_id=f"{label}:1",
        canonical_digest=digest(label),
        organization_id=organization_id,
        workload_context_id="workload-1",
        history_boundary=f"{label}-history:1",
    )


def evaluation_input(**overrides: object) -> DispatchEvaluationInput:
    values: dict[str, object] = {
        "organization_id": "org-1",
        "workload_context_id": "workload-1",
        "plan": reference("plan"),
        "work_item_id": "work-item-1",
        "selection": reference("selection"),
        "selected_candidate_id": "worker-1",
        "readiness_references": (reference("readiness"),),
        "lease": reference("lease"),
        "causal_authorization_reference": reference("authorization"),
        "policy": DispatchPolicy("dispatch-policy", "dispatch-policy.v1", digest("policy-v1")),
        "evaluation_boundary": "dispatch-history:0",
        "effective_at": NOW,
        "clock_source_id": "trusted-clock",
        "clock_source_version": "clock.v1",
        "configuration_version": "dispatch-config.v1",
    }
    values.update(overrides)
    return DispatchEvaluationInput(**values)  # type: ignore[arg-type]


def test_valid_approval_is_immutable_and_canonical() -> None:
    service = DispatchDecisionService()
    result = service.evaluate(evaluation_input(), expected_version=0, idempotency_key="offer-1")
    assert result.outcome is DispatchEvaluationOutcome.CREATED
    assert result.decision.outcome is DispatchDecisionOutcome.APPROVED
    assert result.decision.reason_codes == ("OFFER_APPROVED",)
    assert len(result.decision.dispatch_decision_id) == 64
    assert len(result.decision.canonical_input_digest) == 64
    assert len(result.decision.canonical_decision_digest) == 64
    with pytest.raises(FrozenInstanceError):
        result.decision.outcome = DispatchDecisionOutcome.DENIED  # type: ignore[misc]


def test_valid_denial_is_deterministic_and_creates_no_authority() -> None:
    result = DispatchDecisionService().evaluate(
        evaluation_input(lease_expired=True), expected_version=0, idempotency_key="offer-1"
    )
    assert result.decision.outcome is DispatchDecisionOutcome.DENIED
    assert result.decision.reason_codes == ("LEASE_EXPIRED",)
    assert not hasattr(result.decision, "claim_id")
    assert not hasattr(result.decision, "queue_envelope")


def test_canonical_replay_and_repository_replay_are_identical() -> None:
    service = DispatchDecisionService()
    created = service.evaluate(evaluation_input(), expected_version=0, idempotency_key="offer-1")
    replayed = service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")
    assert replayed == created.decision
    assert service.current(evaluation_input()) == created.decision


def test_digest_mismatch_fails_closed() -> None:
    service = DispatchDecisionService()
    created = service.evaluate(evaluation_input(), expected_version=0, idempotency_key="offer-1")
    record = service.repository.record(created.decision.dispatch_decision_id)
    assert record is not None
    service.repository._by_id[created.decision.dispatch_decision_id] = replace(
        record, canonical_input_content=record.canonical_input_content + b" "
    )
    with pytest.raises(DispatchDecisionDigestMismatch):
        service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")


def test_reconstruction_divergence_fails_closed() -> None:
    service = DispatchDecisionService()
    created = service.evaluate(evaluation_input(), expected_version=0, idempotency_key="offer-1")
    record = service.repository.record(created.decision.dispatch_decision_id)
    assert record is not None
    forged_content = canonical_json({"forged": True}).encode()
    forged_digest = hashlib.sha256(
        DECISION_DIGEST_NAMESPACE.encode() + b"\n" + forged_content
    ).hexdigest()
    forged = replace(
        record,
        decision=replace(record.decision, canonical_decision_digest=forged_digest),
        canonical_decision_content=forged_content,
    )
    service.repository._by_id[created.decision.dispatch_decision_id] = forged
    with pytest.raises(DispatchDecisionReplayDiverged):
        service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-1")


def test_stale_expected_version_fails_without_append() -> None:
    service = DispatchDecisionService()
    value = evaluation_input()
    service.evaluate(value, expected_version=0, idempotency_key="offer-1")
    with pytest.raises(DispatchDecisionVersionConflict):
        service.evaluate(value, expected_version=0, idempotency_key="offer-2")
    assert len(service.history(value)) == 1


def test_competing_cas_writers_have_one_winner() -> None:
    service = DispatchDecisionService()
    value = evaluation_input()

    def evaluate(key: str) -> str:
        try:
            service.evaluate(value, expected_version=0, idempotency_key=key)
            return "accepted"
        except DispatchDecisionVersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(evaluate, ("offer-a", "offer-b")))
    assert sorted(results) == ["accepted", "conflict"]
    assert len(service.history(value)) == 1


def test_equivalent_idempotent_retry_returns_existing_without_append() -> None:
    service = DispatchDecisionService()
    value = evaluation_input()
    first = service.evaluate(value, expected_version=0, idempotency_key="offer-1")
    second = service.evaluate(value, expected_version=0, idempotency_key="offer-1")
    assert second.outcome is DispatchEvaluationOutcome.EXISTING_EQUIVALENT
    assert second.decision == first.decision
    assert len(service.history(value)) == 1


def test_conflicting_idempotency_fails_without_replacement() -> None:
    service = DispatchDecisionService()
    value = evaluation_input()
    first = service.evaluate(value, expected_version=0, idempotency_key="offer-1")
    changed = evaluation_input(lease_expired=True)
    with pytest.raises(DispatchDecisionIdempotencyConflict):
        service.evaluate(changed, expected_version=1, idempotency_key="offer-1")
    assert service.current(value) == first.decision


def test_append_only_history_preserves_superseded_decisions() -> None:
    service = DispatchDecisionService()
    value = evaluation_input()
    approved = service.evaluate(value, expected_version=0, idempotency_key="offer-1")
    denied_input = evaluation_input(
        lease_expired=True,
        policy=DispatchPolicy("dispatch-policy", "dispatch-policy.v2", digest("policy-v2")),
        evaluation_boundary="dispatch-history:1",
    )
    denied = service.evaluate(denied_input, expected_version=1, idempotency_key="offer-2")
    history = service.history(value)
    assert history == (approved.decision, denied.decision)
    assert history[0].outcome is DispatchDecisionOutcome.APPROVED
    assert service.current(value) == denied.decision


def test_organization_isolation_hides_decision_existence() -> None:
    service = DispatchDecisionService()
    created = service.evaluate(evaluation_input(), expected_version=0, idempotency_key="offer-1")
    with pytest.raises(DispatchDecisionNotFound):
        service.get(created.decision.dispatch_decision_id, organization_id="org-2")
    with pytest.raises(DispatchDecisionNotFound):
        service.reconstruct(created.decision.dispatch_decision_id, organization_id="org-2")


def test_cross_scope_and_malformed_evidence_fail_closed() -> None:
    with pytest.raises(DispatchDecisionInvalid):
        reference("plan", organization_id="")
    with pytest.raises(DispatchDecisionInvalid):
        ArtifactReference("plan:1", "not-a-digest", "org-1", "workload-1", "history:1")
    with pytest.raises(Exception) as error:
        evaluation_input(lease=reference("lease", organization_id="org-2"))
    assert "organization" in str(error.value).lower()


def test_package_has_no_downstream_effect_imports() -> None:
    from pathlib import Path

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("app/runtime/dispatch_decision").glob("*.py"))
    )
    for forbidden in (
        "work_claim", "queue", "execution_attempt", "monitoring", "completion",
        "retry", "provider", "orchestration", "fastapi", "sqlalchemy",
    ):
        assert f"from app.runtime.{forbidden}" not in source
