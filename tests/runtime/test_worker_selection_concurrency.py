from concurrent.futures import ThreadPoolExecutor

import pytest

from app.runtime.worker_selection.domain import (
    SelectionIdempotencyConflict,
    SelectionVersionConflict,
)
from app.runtime.worker_selection.service import WorkerSelectionService
from tests.runtime.test_worker_selection_replay import selection_request


def test_identical_idempotent_evaluation_returns_accepted_record() -> None:
    service = WorkerSelectionService()
    first = service.evaluate(
        selection_request(), expected_version=0, idempotency_key="same"
    )
    second = service.evaluate(
        selection_request(), expected_version=0, idempotency_key="same"
    )
    assert second == first
    assert len(service.history("org-1", "workload-1")) == 1


def test_idempotency_content_mismatch_fails_closed() -> None:
    service = WorkerSelectionService()
    service.evaluate(selection_request(), expected_version=0, idempotency_key="same")
    with pytest.raises(SelectionIdempotencyConflict):
        service.evaluate(
            selection_request("0.9"), expected_version=0, idempotency_key="same"
        )


def test_stale_expected_version_appends_nothing() -> None:
    service = WorkerSelectionService()
    service.evaluate(selection_request(), expected_version=0, idempotency_key="one")
    with pytest.raises(SelectionVersionConflict):
        service.evaluate(selection_request(), expected_version=0, idempotency_key="two")
    assert len(service.history("org-1", "workload-1")) == 1


def test_same_canonical_input_with_new_key_does_not_duplicate_history() -> None:
    service = WorkerSelectionService()
    first = service.evaluate(
        selection_request(), expected_version=0, idempotency_key="one"
    )
    second = service.evaluate(
        selection_request(), expected_version=1, idempotency_key="two"
    )
    assert second == first
    assert len(service.history("org-1", "workload-1")) == 1


def test_equal_time_race_has_one_cas_winner() -> None:
    service = WorkerSelectionService()

    def evaluate(key: str) -> str:
        try:
            service.evaluate(
                selection_request(), expected_version=0, idempotency_key=key
            )
            return "accepted"
        except SelectionVersionConflict:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(evaluate, ("one", "two")))
    assert sorted(outcomes) == ["accepted", "stale"]
    assert len(service.history("org-1", "workload-1")) == 1
