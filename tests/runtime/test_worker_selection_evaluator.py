from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.worker_selection.domain import (
    SelectionArtifactVersionUnsupported,
    SelectionOutcome,
    WorkerReadinessEvidence,
    WorkerSelectionRequest,
)
from app.runtime.worker_selection.evaluator import WorkerSelectionEvaluator


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


def readiness(worker: int, **overrides: object) -> WorkerReadinessEvidence:
    values = {
        "worker_id": f"00000000-0000-0000-0000-{worker:012d}",
        "reference": f"readiness:{worker}",
        "canonical_hash": f"hash-{worker}",
        "organization_id": "org-1",
        "workload_context_id": "workload-1",
        "evaluated_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "ready": True,
        "capabilities": ("cpu", "gpu"),
        "hard_policy_pass": True,
        "scores": {},
        "evidence_references": (f"evidence:{worker}",),
    }
    values.update(overrides)
    return WorkerReadinessEvidence(**values)  # type: ignore[arg-type]


def request(*workers: WorkerReadinessEvidence, **overrides: object) -> WorkerSelectionRequest:
    values = {
        "organization_id": "org-1",
        "workload_context_id": "workload-1",
        "execution_plan_reference": "plan:1",
        "workload_requirements_reference": "requirements:1",
        "policy_constraints_reference": "policy:1",
        "required_capabilities": ("cpu",),
        "readiness": workers,
        "evaluation_boundary": NOW,
        "history_boundary": "history:10",
    }
    values.update(overrides)
    return WorkerSelectionRequest(**values)  # type: ignore[arg-type]


def test_deterministic_ranking_and_hashes_ignore_input_order() -> None:
    newer_high_id = readiness(2, scores={"CAPABILITY_FIT": "0.500000"})
    older_low_id = readiness(
        1,
        evaluated_at=NOW - timedelta(minutes=1),
        scores={"CAPABILITY_FIT": "0.500000"},
    )
    evaluator = WorkerSelectionEvaluator()
    first = evaluator.evaluate(request(newer_high_id, older_low_id))
    second = evaluator.evaluate(request(older_low_id, newer_high_id))
    assert first == second
    assert [item.worker_id for item in first.candidates] == [
        older_low_id.worker_id,
        newer_high_id.worker_id,
    ]
    assert first.outcome is SelectionOutcome.CANDIDATE_FOUND
    assert first.canonical_hash == second.canonical_hash


def test_uuid_breaks_equal_score_and_equal_readiness_time_ties() -> None:
    result = WorkerSelectionEvaluator().evaluate(request(readiness(2), readiness(1)))
    assert [candidate.worker_id for candidate in result.candidates] == [
        readiness(1).worker_id,
        readiness(2).worker_id,
    ]


def test_fixed_point_round_half_even_and_missing_optional_evidence() -> None:
    result = WorkerSelectionEvaluator().evaluate(
        request(readiness(1, scores={"CAPABILITY_FIT": "0.1234565"}))
    )
    candidate = result.candidates[0]
    assert candidate.score == "4.938240"
    assert candidate.score_components[0].normalized_value == "0.123456"
    assert "LATENCY_OBJECTIVE_EVIDENCE_MISSING" in candidate.reason_codes


@pytest.mark.parametrize(
    ("workers", "outcome"),
    [
        ((readiness(1, ready=False),), SelectionOutcome.NO_ELIGIBLE_WORKERS),
        ((readiness(1, hard_policy_pass=False),), SelectionOutcome.POLICY_FILTERED),
        ((readiness(1, hard_policy_pass=None),), SelectionOutcome.EVIDENCE_UNAVAILABLE),
        ((readiness(1, evidence_consistent=False),), SelectionOutcome.INDETERMINATE),
        (
            (readiness(1, capabilities=("gpu",)),),
            SelectionOutcome.EVIDENCE_UNAVAILABLE,
        ),
    ],
)
def test_stable_empty_selection_outcomes(
    workers: tuple[WorkerReadinessEvidence, ...], outcome: SelectionOutcome
) -> None:
    assert WorkerSelectionEvaluator().evaluate(request(*workers)).outcome is outcome


def test_exclusions_are_retained_in_worker_uuid_order() -> None:
    result = WorkerSelectionEvaluator().evaluate(
        request(readiness(2, ready=False), readiness(1))
    )
    assert result.outcome is SelectionOutcome.CANDIDATE_FOUND
    assert result.excluded_workers[0].worker_id == readiness(2).worker_id


def test_unknown_policy_version_fails_closed() -> None:
    with pytest.raises(SelectionArtifactVersionUnsupported):
        WorkerSelectionEvaluator().evaluate(
            request(readiness(1), scoring_policy_version="unknown")
        )
