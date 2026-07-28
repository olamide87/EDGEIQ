import hashlib
import socket
from dataclasses import replace

import pytest

from app.runtime.execution_plan.domain import (
    ExecutionPlanDigestMismatch,
    ExecutionPlanNotFound,
    ExecutionPlanReplayDiverged,
    ExecutionPlanReconstructionFailed,
)
from app.runtime.execution_plan.ports import ExecutionPlanRecord
from app.runtime.execution_plan.serialization import PLAN_DIGEST_NAMESPACE
from app.runtime.execution_plan.service import ExecutionPlanService
from tests.runtime.test_execution_plan_domain import (
    accepted_context,
    planning_input,
)


class StaticRepository:
    def __init__(self, record: ExecutionPlanRecord) -> None:
        self.retained = record

    def append(self, record, *, expected_version):
        raise AssertionError

    def get(self, plan_id):
        return self.retained.plan if plan_id == self.retained.plan.plan_id else None

    def record(self, plan_id):
        return self.retained if plan_id == self.retained.plan.plan_id else None

    def history(self, organization_id, workload_context_id, request_id):
        return (self.retained,)

    def current(self, organization_id, workload_context_id, request_id):
        return self.retained.plan


def accepted_plan():
    requests, request, validations, evidence = accepted_context()
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
    )
    result = service.derive(
        planning_input(request, evidence),
        expected_version=0,
        idempotency_key="plan-1",
    )
    record = service.repository.record(result.plan.plan_id)
    assert record is not None
    return requests, validations, service, record


def test_reconstruction_reruns_registered_planning_rule(monkeypatch) -> None:
    _, _, service, record = accepted_plan()
    import app.runtime.execution_plan.serialization as serialization

    original_lookup = serialization.planning_rule
    calls = []

    def observed_lookup(version):
        rule = original_lookup(version)

        def observed(*args):
            calls.append(args)
            return rule(*args)

        return observed

    monkeypatch.setattr(serialization, "planning_rule", observed_lookup)
    assert service.reconstruct(
        record.plan.plan_id, organization_id="org-1"
    ) == record.plan
    assert len(calls) == 1


def test_tampered_retained_output_is_detected() -> None:
    requests, validations, _, record = accepted_plan()
    changed = record.canonical_plan_content.replace(
        b'"operation":"demo.echo"', b'"operation":"demo.fake"'
    )
    digest = hashlib.sha256(
        PLAN_DIGEST_NAMESPACE.encode() + b"\n" + changed
    ).hexdigest()
    forged = replace(
        record,
        plan=replace(record.plan, canonical_plan_digest=digest),
        canonical_plan_content=changed,
    )
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
        repository=StaticRepository(forged),
    )
    with pytest.raises(ExecutionPlanReplayDiverged):
        service.reconstruct(record.plan.plan_id, organization_id="org-1")


def test_invalid_input_digest_and_cross_organization_fail_closed() -> None:
    _, _, service, record = accepted_plan()
    forged = replace(
        record,
        canonical_input_content=record.canonical_input_content + b" ",
    )
    requests, _, validations, _ = accepted_context()
    forged_service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
        repository=StaticRepository(forged),
    )
    with pytest.raises(ExecutionPlanDigestMismatch):
        forged_service.reconstruct(record.plan.plan_id, organization_id="org-1")
    with pytest.raises(ExecutionPlanNotFound):
        service.reconstruct(record.plan.plan_id, organization_id="org-2")


def test_missing_canonical_input_fails_closed() -> None:
    requests, validations, _, record = accepted_plan()
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
        repository=StaticRepository(
            replace(record, canonical_input_content=None)
        ),
    )
    with pytest.raises(ExecutionPlanDigestMismatch):
        service.reconstruct(record.plan.plan_id, organization_id="org-1")


def test_history_version_gap_fails_closed() -> None:
    requests, validations, _, record = accepted_plan()
    gapped = replace(record, stream_version=2)
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
        repository=StaticRepository(gapped),
    )
    with pytest.raises(ExecutionPlanReconstructionFailed):
        service.reconstruct(record.plan.plan_id, organization_id="org-1")


def test_derivation_and_reconstruction_have_no_external_effect(monkeypatch) -> None:
    requests, request, validations, evidence = accepted_context()

    def forbidden(*args, **kwargs):
        raise AssertionError("live runtime state is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    service = ExecutionPlanService(
        accepted_requests=requests.repository,
        validation_evidence=validations,
    )
    result = service.derive(
        planning_input(request, evidence),
        expected_version=0,
        idempotency_key="plan-1",
    )
    assert service.reconstruct(
        result.plan.plan_id, organization_id="org-1"
    ) == result.plan


def test_plan_package_has_no_downstream_runtime_imports() -> None:
    from pathlib import Path

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("app/runtime/execution_plan").glob("*.py"))
    )
    for forbidden in (
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
    ):
        assert f"from app.runtime.{forbidden}" not in source
