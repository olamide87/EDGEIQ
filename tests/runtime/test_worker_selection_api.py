from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runtime.worker_selection.service import WorkerSelectionService
from app.worker_selection_api import get_worker_selection_service


NOW = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def selection_client(client: TestClient) -> TestClient:
    service = WorkerSelectionService()
    app.dependency_overrides[get_worker_selection_service] = lambda: service
    yield client
    app.dependency_overrides.pop(get_worker_selection_service, None)


def payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "organizationId": "org-1",
        "workloadContextId": "workload-1",
        "executionPlanReference": "plan:1",
        "workloadRequirementsReference": "requirements:1",
        "policyConstraintsReference": "policy:1",
        "requiredCapabilities": ["cpu"],
        "evaluationBoundary": NOW.isoformat(),
        "historyBoundary": "history:1",
        "expectedVersion": 0,
        "readiness": [
            {
                "workerId": "00000000-0000-0000-0000-000000000001",
                "reference": "readiness:1",
                "canonicalHash": "hash-1",
                "organizationId": "org-1",
                "workloadContextId": "workload-1",
                "evaluatedAt": NOW.isoformat(),
                "expiresAt": (NOW + timedelta(hours=1)).isoformat(),
                "ready": True,
                "capabilities": ["cpu"],
                "scores": {"CAPABILITY_FIT": "0.5"},
                "evidenceReferences": ["capabilities:1"],
            }
        ],
    }
    values.update(overrides)
    return values


def test_evaluate_and_read_selection_history(selection_client: TestClient) -> None:
    created = selection_client.post(
        "/worker-selection/evaluate",
        json=payload(),
        headers={"Idempotency-Key": "request-1"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["outcome"] == "CandidateFound"
    assert body["candidates"][0]["rank"] == 1
    selection_id = body["selectionId"]

    read = selection_client.get(
        f"/worker-selection/{selection_id}",
        headers={"Organization-Id": "org-1"},
    )
    assert read.status_code == 200
    assert read.json()["canonicalHash"] == body["canonicalHash"]

    history = selection_client.get(
        f"/worker-selection/{selection_id}/history",
        headers={"Organization-Id": "org-1"},
    )
    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [1]

    current = selection_client.get(
        "/worker-selection",
        params={"workloadId": "workload-1"},
        headers={"Organization-Id": "org-1"},
    )
    assert current.json()["selectionId"] == selection_id


def test_read_fails_closed_across_organization_scope(
    selection_client: TestClient,
) -> None:
    created = selection_client.post(
        "/worker-selection/evaluate",
        json=payload(),
        headers={"Idempotency-Key": "request-1"},
    )
    selection_id = created.json()["selectionId"]
    response = selection_client.get(
        f"/worker-selection/{selection_id}",
        headers={"Organization-Id": "org-2"},
    )
    assert response.status_code == 404


def test_api_maps_version_and_idempotency_conflicts(
    selection_client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "request-1"}
    assert selection_client.post(
        "/worker-selection/evaluate", json=payload(), headers=headers
    ).status_code == 201
    mismatch = payload(readiness=payload()["readiness"])
    mismatch["requiredCapabilities"] = ["cpu", "gpu"]
    conflict = selection_client.post(
        "/worker-selection/evaluate", json=mismatch, headers=headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "SelectionIdempotencyConflict"

    stale = selection_client.post(
        "/worker-selection/evaluate",
        json=payload(),
        headers={"Idempotency-Key": "request-2"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "SelectionVersionConflict"


@pytest.mark.parametrize(
    "route",
    ["/dispatch", "/claim", "/execute", "/start", "/retry", "/invoke", "/schedule"],
)
def test_forbidden_operational_routes_do_not_exist(
    selection_client: TestClient, route: str
) -> None:
    assert selection_client.post(route).status_code == 404


def test_missing_idempotency_key_is_rejected(selection_client: TestClient) -> None:
    response = selection_client.post("/worker-selection/evaluate", json=payload())
    assert response.status_code == 422
