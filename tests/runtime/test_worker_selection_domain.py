from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.worker_selection.domain import (
    SelectionRequestInvalid,
    WorkerReadinessEvidence,
)
from app.runtime.worker_selection.serialization import canonical_json


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def readiness(**overrides: object) -> WorkerReadinessEvidence:
    values = {
        "worker_id": "00000000-0000-0000-0000-000000000001",
        "reference": "readiness:1",
        "canonical_hash": "hash-1",
        "organization_id": "org-1",
        "workload_context_id": "workload-1",
        "evaluated_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "ready": True,
        "capabilities": ("gpu", "cpu"),
        "scores": {"LATENCY_OBJECTIVE": "0.5"},
    }
    values.update(overrides)
    return WorkerReadinessEvidence(**values)  # type: ignore[arg-type]


def test_domain_records_are_immutable_and_normalize_ordering() -> None:
    evidence = readiness()
    assert evidence.capabilities == ("cpu", "gpu")
    with pytest.raises(FrozenInstanceError):
        evidence.ready = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        evidence.scores["COST_PREFERENCE"] = "1"  # type: ignore[index]


def test_domain_rejects_noncanonical_worker_uuid_and_naive_time() -> None:
    with pytest.raises(SelectionRequestInvalid):
        readiness(worker_id="00000000-0000-0000-0000-00000000000A")
    with pytest.raises(SelectionRequestInvalid):
        readiness(evaluated_at=datetime(2026, 7, 23, 12))


def test_canonical_serialization_sorts_maps_and_uses_explicit_precision() -> None:
    first = readiness(scores={"LATENCY_OBJECTIVE": "0.5", "COST_PREFERENCE": "0.2"})
    second = readiness(scores={"COST_PREFERENCE": "0.2", "LATENCY_OBJECTIVE": "0.5"})
    assert canonical_json(first) == canonical_json(second)
    assert "2026-07-23T12:00:00.000000Z" in canonical_json(first)
