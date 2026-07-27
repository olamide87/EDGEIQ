from dataclasses import replace

import pytest

from app.runtime.execution_request.domain import (
    ExecutionRequestDigestMismatch,
    ExecutionRequestNotFound,
    ExecutionRequestReconstructionFailed,
    ExecutionRequestSchemaVersionUnsupported,
    ImmutablePayloadReference,
)
from app.runtime.execution_request.ports import ExecutionRequestRecord
from app.runtime.execution_request.serialization import reconstruct_execution_request
from app.runtime.execution_request.service import (
    ExecutionRequestService,
    InMemoryExecutionRequestRepository,
)
from tests.runtime.test_execution_request_domain import draft


def accepted_service() -> tuple[ExecutionRequestService, str]:
    service = ExecutionRequestService()
    result = service.admit(draft(), idempotency_key="request-1")
    return service, result.request.request_id


def test_reconstruction_reproduces_accepted_request() -> None:
    service, request_id = accepted_service()
    assert service.reconstruct(
        request_id, organization_id="org-1"
    ) == service.get(request_id, organization_id="org-1")


def test_reconstruction_without_canonical_content_fails_closed() -> None:
    with pytest.raises(ExecutionRequestReconstructionFailed):
        reconstruct_execution_request(None, expected_digest="a" * 64)


def test_digest_mismatch_fails_closed() -> None:
    service, request_id = accepted_service()
    record = service.repository.record(request_id)
    assert record is not None
    with pytest.raises(ExecutionRequestDigestMismatch):
        reconstruct_execution_request(
            record.canonical_content + b" ",
            expected_digest=record.request.canonical_digest,
        )


def test_unsupported_retained_schema_fails_closed() -> None:
    service, request_id = accepted_service()
    record = service.repository.record(request_id)
    assert record is not None
    changed = record.canonical_content.replace(
        b"execution-request.v1", b"execution-request.v2"
    )
    import hashlib

    digest = hashlib.sha256(
        b"edgeiq.execution-request.v1\n" + changed
    ).hexdigest()
    with pytest.raises(ExecutionRequestSchemaVersionUnsupported):
        reconstruct_execution_request(changed, expected_digest=digest)


def test_malformed_payload_reference_fails_closed() -> None:
    service = ExecutionRequestService()
    result = service.admit(
        draft(
            immutable_payload=None,
            immutable_payload_reference=ImmutablePayloadReference(
                reference="artifact:payload-1",
                canonical_digest="a" * 64,
                schema_version="payload.v1",
            ),
        ),
        idempotency_key="request-1",
    )
    record = service.repository.record(result.request.request_id)
    assert record is not None
    changed = record.canonical_content.replace(
        b'"reference":"artifact:payload-1",', b""
    )
    import hashlib

    digest = hashlib.sha256(
        b"edgeiq.execution-request.v1\n" + changed
    ).hexdigest()
    with pytest.raises(ExecutionRequestReconstructionFailed):
        reconstruct_execution_request(changed, expected_digest=digest)


def test_retained_request_and_content_divergence_fails_closed() -> None:
    repository = InMemoryExecutionRequestRepository()
    service = ExecutionRequestService(repository)
    accepted = service.admit(draft(), idempotency_key="request-1").request
    record = repository.record(accepted.request_id)
    assert record is not None
    repository._by_id[accepted.request_id] = ExecutionRequestRecord(
        request=replace(accepted, requested_work_type="changed"),
        canonical_content=record.canonical_content,
    )
    with pytest.raises(ExecutionRequestDigestMismatch):
        service.reconstruct(accepted.request_id, organization_id="org-1")


def test_cross_organization_reconstruction_fails_as_not_found() -> None:
    service, request_id = accepted_service()
    with pytest.raises(ExecutionRequestNotFound):
        service.reconstruct(request_id, organization_id="org-2")
