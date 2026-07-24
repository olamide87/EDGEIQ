from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.worker_selection.domain import (
    SelectionReplayDiverged,
    WorkerReadinessEvidence,
    WorkerSelectionRequest,
)
from app.runtime.worker_selection.ports import WorkerSelectionHistoryRecord
from app.runtime.worker_selection.service import WorkerSelectionService
from app.runtime.worker_selection.serialization import canonical_hash


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def selection_request(score: str = "0.5") -> WorkerSelectionRequest:
    evidence = WorkerReadinessEvidence(
        worker_id="00000000-0000-0000-0000-000000000001",
        reference="readiness:1",
        canonical_hash="readiness-hash",
        organization_id="org-1",
        workload_context_id="workload-1",
        evaluated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        ready=True,
        capabilities=("cpu",),
        scores={"CAPABILITY_FIT": score},
        evidence_references=("capabilities:1",),
    )
    return WorkerSelectionRequest(
        organization_id="org-1",
        workload_context_id="workload-1",
        execution_plan_reference="plan:1",
        workload_requirements_reference="requirements:1",
        policy_constraints_reference="policy:1",
        required_capabilities=("cpu",),
        readiness=(evidence,),
        evaluation_boundary=NOW,
        history_boundary="history:1",
    )


def test_replay_reproduces_selection_without_live_lookup() -> None:
    service = WorkerSelectionService()
    accepted = service.evaluate(
        selection_request(), expected_version=0, idempotency_key="request-1"
    )
    assert service.replay(accepted.selection_id) == accepted


def test_replay_detects_retained_history_divergence() -> None:
    service = WorkerSelectionService()
    accepted = service.evaluate(
        selection_request(), expected_version=0, idempotency_key="request-1"
    )
    record = service.history_store.record(accepted.selection_id)
    assert record is not None
    changed = selection_request("0.9")
    service.history_store._by_id[accepted.selection_id] = WorkerSelectionHistoryRecord(
        request=changed,
        selection=record.selection,
        idempotency_key=record.idempotency_key,
        canonical_input_hash=canonical_hash(
            changed, namespace="worker-selection-service-input"
        ),
    )
    with pytest.raises(SelectionReplayDiverged):
        service.replay(accepted.selection_id)
