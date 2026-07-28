import json
import socket
from dataclasses import replace

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanDigestMismatch,
    ExecutionPlanNotFound,
    ExecutionPlanPolicyConfigurationMismatch,
    ExecutionPlanReconstructionFailed,
    ExecutionPlanReplayDiverged,
    ExecutionPlanSchemaVersionUnsupported,
)
from app.runtime.execution_plan.ports import ExecutionPlanRecord
from app.runtime.execution_plan.service import ExecutionPlanService
from app.runtime.execution_request.service import ExecutionRequestService
from tests.runtime.test_execution_plan_domain import (
    accepted_request,
    plan_draft,
)


class StaticPlanRepository:
    def __init__(self, record: ExecutionPlanRecord) -> None:
        self.retained_record = record

    def append(self, record, *, expected_version: int):
        raise AssertionError("Append is not used in reconstruction tests.")

    def get(self, plan_id: str):
        if plan_id == self.retained_record.plan.plan_id:
            return self.retained_record.plan
        return None

    def record(self, plan_id: str):
        if plan_id == self.retained_record.plan.plan_id:
            return self.retained_record
        return None

    def history(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ):
        return (self.retained_record,)

    def current(
        self,
        organization_id: str,
        workload_context_id: str,
        request_id: str,
    ):
        return self.retained_record.plan


def accepted_plan() -> tuple[
    ExecutionRequestService, ExecutionPlanService, ExecutionPlanRecord
]:
    request_service, request = accepted_request()
    service = ExecutionPlanService(
        accepted_requests=request_service.repository
    )
    result = service.derive(
        plan_draft(request),
        expected_version=0,
        idempotency_key="plan-1",
    )
    record = service.repository.record(result.plan.plan_id)
    assert record is not None
    return request_service, service, record


def test_valid_history_reconstructs_exact_plan() -> None:
    _, service, record = accepted_plan()
    assert service.reconstruct(
        record.plan.plan_id, organization_id="org-1"
    ) == record.plan


def test_cross_organization_reconstruction_is_not_disclosed() -> None:
    _, service, record = accepted_plan()
    with pytest.raises(ExecutionPlanNotFound):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-2"
        )


def test_missing_canonical_input_fails_closed() -> None:
    request_service, _, record = accepted_plan()
    forged = replace(record, canonical_input_content=None)  # type: ignore[arg-type]
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(ExecutionPlanReconstructionFailed):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )


def test_invalid_retained_plan_digest_fails_closed() -> None:
    request_service, _, record = accepted_plan()
    forged = replace(
        record,
        canonical_plan_content=record.canonical_plan_content + b" ",
    )
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(ExecutionPlanDigestMismatch):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )


def test_unsupported_retained_schema_fails_closed() -> None:
    request_service, _, record = accepted_plan()
    document = json.loads(record.canonical_input_content)
    document["plan_schema_version"] = "execution-plan.v2"
    changed = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    forged = replace(record, canonical_input_content=changed)
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(
        (ExecutionPlanDigestMismatch, ExecutionPlanSchemaVersionUnsupported)
    ):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )


def test_replay_divergence_fails_without_mutation() -> None:
    request_service, _, record = accepted_plan()
    changed = record.canonical_plan_content.replace(
        b'"operation":"demo.prepare"',
        b'"operation":"demo.changed"',
    )
    import hashlib

    digest = hashlib.sha256(
        b"edgeiq.execution-plan.v1\n" + changed
    ).hexdigest()
    forged = replace(
        record,
        plan=replace(record.plan, canonical_plan_digest=digest),
        canonical_plan_content=changed,
    )
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(ExecutionPlanReplayDiverged):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )
    assert service.repository.record(record.plan.plan_id) == forged


def test_reconstruction_performs_no_external_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service, record = accepted_plan()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("External access is forbidden during reconstruction.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert service.reconstruct(
        record.plan.plan_id, organization_id="org-1"
    ) == record.plan


def test_plan_package_has_no_downstream_runtime_imports() -> None:
    from pathlib import Path

    root = Path("app/runtime/execution_plan")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*.py"))
    )
    forbidden_imports = (
        "worker_selection",
        "worker_readiness",
        "dispatch",
        "work_claim",
        "execution_lease",
        "queue",
        "monitoring",
        "completion",
        "retry",
        "provider",
        "orchestration",
    )
    for forbidden in forbidden_imports:
        assert f"import {forbidden}" not in source
        assert f"from app.runtime.{forbidden}" not in source


def test_policy_configuration_divergence_fails_closed() -> None:
    request_service, _, record = accepted_plan()
    document = json.loads(record.canonical_plan_content)
    document["policy_version_or_digest"] = "planning-policy.v2"
    changed = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    import hashlib

    digest = hashlib.sha256(
        b"edgeiq.execution-plan.v1\n" + changed
    ).hexdigest()
    forged = replace(
        record,
        plan=replace(record.plan, canonical_plan_digest=digest),
        canonical_plan_content=changed,
    )
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(ExecutionPlanPolicyConfigurationMismatch):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )


def test_history_version_gap_fails_closed() -> None:
    request_service, _, record = accepted_plan()
    forged = replace(record, stream_version=2)
    service = ExecutionPlanService(
        accepted_requests=request_service.repository,
        repository=StaticPlanRepository(forged),
    )
    with pytest.raises(ExecutionPlanReconstructionFailed):
        service.reconstruct(
            record.plan.plan_id, organization_id="org-1"
        )
