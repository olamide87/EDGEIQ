from dataclasses import FrozenInstanceError

import pytest

from app.runtime.execution_request.domain import (
    ExecutionRequestDraft,
    ExecutionRequestInvalid,
    ExecutionRequestSchemaVersionUnsupported,
    ImmutablePayloadReference,
)
from app.runtime.execution_request.serialization import (
    build_execution_request,
    canonical_request_bytes,
    idempotency_identity,
)


def draft(**overrides: object) -> ExecutionRequestDraft:
    values = {
        "organization_id": "org-1",
        "workload_context_id": "workload-1",
        "requested_work_type": "demo.echo",
        "immutable_payload": {"message": "hello", "options": {"count": 2}},
        "request_constraints": {"regions": ["us-central", "us-east"]},
        "provenance": {"correlation_id": "correlation-1", "source": "unit-test"},
    }
    values.update(overrides)
    return ExecutionRequestDraft(**values)  # type: ignore[arg-type]


def identity(key: str = "request-1") -> str:
    return idempotency_identity(
        organization_id="org-1",
        workload_context_id="workload-1",
        submitted_key=key,
    )


def test_same_canonical_input_and_schema_produce_same_digest() -> None:
    first, first_content = build_execution_request(
        draft(), accepted_idempotency_identity=identity()
    )
    second, second_content = build_execution_request(
        draft(), accepted_idempotency_identity=identity()
    )
    assert first.canonical_digest == second.canonical_digest
    assert first.request_id == second.request_id
    assert first_content == second_content


def test_map_insertion_order_does_not_change_digest() -> None:
    first = draft(
        immutable_payload={"a": 1, "b": {"c": 2, "d": 3}},
        provenance={"source": "unit-test", "correlation_id": "correlation-1"},
    )
    second = draft(
        immutable_payload={"b": {"d": 3, "c": 2}, "a": 1},
        provenance={"correlation_id": "correlation-1", "source": "unit-test"},
    )
    first_request, _ = build_execution_request(
        first, accepted_idempotency_identity=identity()
    )
    second_request, _ = build_execution_request(
        second, accepted_idempotency_identity=identity()
    )
    assert first_request.canonical_digest == second_request.canonical_digest


def test_semantically_meaningful_list_order_is_preserved() -> None:
    forward, _ = build_execution_request(
        draft(request_constraints={"steps": ["first", "second"]}),
        accepted_idempotency_identity=identity(),
    )
    reverse, _ = build_execution_request(
        draft(request_constraints={"steps": ["second", "first"]}),
        accepted_idempotency_identity=identity(),
    )
    assert forward.canonical_digest != reverse.canonical_digest


def test_unsupported_schema_version_fails_closed() -> None:
    with pytest.raises(ExecutionRequestSchemaVersionUnsupported):
        draft(request_schema_version="execution-request.v2")


def test_accepted_request_and_nested_content_are_immutable() -> None:
    request, _ = build_execution_request(
        draft(), accepted_idempotency_identity=identity()
    )
    with pytest.raises(FrozenInstanceError):
        request.requested_work_type = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.provenance["source"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.immutable_payload["message"] = "changed"  # type: ignore[index]


def test_payload_and_reference_are_mutually_exclusive() -> None:
    reference = ImmutablePayloadReference(
        reference="artifact:payload-1",
        canonical_digest="a" * 64,
        schema_version="payload.v1",
    )
    with pytest.raises(ExecutionRequestInvalid):
        draft(immutable_payload_reference=reference)
    with pytest.raises(ExecutionRequestInvalid):
        draft(immutable_payload=None, immutable_payload_reference=None)


def test_numeric_and_absent_value_rules_are_explicit() -> None:
    with pytest.raises(ExecutionRequestInvalid):
        draft(immutable_payload={"unsupported_float": 1.5})
    content = canonical_request_bytes(
        draft(), accepted_idempotency_identity=identity()
    )
    assert b'"immutable_payload_reference":null' in content
    assert b'"options":{"count":2}' in content


def test_equivalent_unicode_is_normalized_before_acceptance() -> None:
    composed, composed_content = build_execution_request(
        draft(immutable_payload={"message": "caf\u00e9"}),
        accepted_idempotency_identity=identity(),
    )
    decomposed, decomposed_content = build_execution_request(
        draft(immutable_payload={"message": "cafe\u0301"}),
        accepted_idempotency_identity=identity(),
    )
    assert composed == decomposed
    assert composed_content == decomposed_content
