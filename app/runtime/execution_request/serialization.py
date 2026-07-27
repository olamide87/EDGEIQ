import hashlib
import json
import unicodedata
from types import MappingProxyType
from typing import Any, Mapping

from app.runtime.execution_request.domain import (
    ExecutionRequest,
    ExecutionRequestDigestMismatch,
    ExecutionRequestDraft,
    ExecutionRequestInvalid,
    ExecutionRequestReconstructionFailed,
    ExecutionRequestSchemaVersionUnsupported,
    ImmutablePayloadReference,
    SUPPORTED_REQUEST_SCHEMA_VERSION,
)


SERIALIZATION_VERSION = "canonical-json.v1"
REQUEST_DIGEST_NAMESPACE = "edgeiq.execution-request.v1"
REQUEST_ID_NAMESPACE = "edgeiq.execution-request-id.v1"
IDEMPOTENCY_NAMESPACE = "edgeiq.execution-request-idempotency.v1"


def _canonical_value(value: Any) -> Any:
    if isinstance(value, ImmutablePayloadReference):
        return {
            "canonical_digest": _canonical_value(value.canonical_digest),
            "reference": _canonical_value(value.reference),
            "schema_version": _canonical_value(value.schema_version),
        }
    if isinstance(value, (dict, MappingProxyType, Mapping)):
        if any(not isinstance(key, str) for key in value):
            raise ExecutionRequestInvalid("Canonical map keys must be strings.")
        normalized = [
            (unicodedata.normalize("NFC", key), _canonical_value(item))
            for key, item in value.items()
        ]
        if len({key for key, _ in normalized}) != len(normalized):
            raise ExecutionRequestInvalid(
                "Canonical map keys must remain unique after Unicode normalization."
            )
        return {key: item for key, item in sorted(normalized)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    raise ExecutionRequestInvalid(
        f"Unsupported canonical value: {type(value).__name__}."
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode("utf-8") + b"\n" + content).hexdigest()


def idempotency_identity(
    *,
    organization_id: str,
    workload_context_id: str,
    submitted_key: str,
) -> str:
    if not submitted_key:
        raise ExecutionRequestInvalid("An idempotency key is required.")
    scoped = canonical_json(
        {
            "operation": "admit-execution-request",
            "organization_id": organization_id,
            "submitted_key": submitted_key,
            "workload_context_id": workload_context_id,
        }
    ).encode("utf-8")
    return _sha256(IDEMPOTENCY_NAMESPACE, scoped)


def canonical_request_document(
    draft: ExecutionRequestDraft, *, accepted_idempotency_identity: str
) -> dict[str, Any]:
    return {
        "idempotency_identity": accepted_idempotency_identity,
        "immutable_payload": draft.immutable_payload,
        "immutable_payload_reference": draft.immutable_payload_reference,
        "organization_id": draft.organization_id,
        "provenance": draft.provenance,
        "request_constraints": draft.request_constraints,
        "request_schema_version": draft.request_schema_version,
        "requested_work_type": draft.requested_work_type,
        "serialization_version": SERIALIZATION_VERSION,
        "workload_context_id": draft.workload_context_id,
    }


def canonical_request_bytes(
    draft: ExecutionRequestDraft, *, accepted_idempotency_identity: str
) -> bytes:
    return canonical_json(
        canonical_request_document(
            draft, accepted_idempotency_identity=accepted_idempotency_identity
        )
    ).encode("utf-8")


def build_execution_request(
    draft: ExecutionRequestDraft, *, accepted_idempotency_identity: str
) -> tuple[ExecutionRequest, bytes]:
    content = canonical_request_bytes(
        draft, accepted_idempotency_identity=accepted_idempotency_identity
    )
    digest = _sha256(REQUEST_DIGEST_NAMESPACE, content)
    request_id = _sha256(REQUEST_ID_NAMESPACE, digest.encode("ascii"))
    return (
        ExecutionRequest(
            request_id=request_id,
            organization_id=draft.organization_id,
            workload_context_id=draft.workload_context_id,
            request_schema_version=draft.request_schema_version,
            requested_work_type=draft.requested_work_type,
            immutable_payload=draft.immutable_payload,
            immutable_payload_reference=draft.immutable_payload_reference,
            request_constraints=draft.request_constraints,
            provenance=draft.provenance,
            idempotency_identity=accepted_idempotency_identity,
            canonical_digest=digest,
        ),
        content,
    )


def reconstruct_execution_request(
    canonical_content: bytes | None, *, expected_digest: str
) -> ExecutionRequest:
    if not canonical_content:
        raise ExecutionRequestReconstructionFailed(
            "Canonical request content is required."
        )
    actual_digest = _sha256(REQUEST_DIGEST_NAMESPACE, canonical_content)
    if actual_digest != expected_digest:
        raise ExecutionRequestDigestMismatch(
            "Stored and recomputed canonical request digests differ."
        )
    try:
        document = json.loads(canonical_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionRequestReconstructionFailed(
            "Canonical request content is malformed."
        ) from exc
    if not isinstance(document, dict):
        raise ExecutionRequestReconstructionFailed(
            "Canonical request content must be an object."
        )
    if document.get("serialization_version") != SERIALIZATION_VERSION:
        raise ExecutionRequestSchemaVersionUnsupported(
            "Unsupported canonical serialization version."
        )
    if document.get("request_schema_version") != SUPPORTED_REQUEST_SCHEMA_VERSION:
        raise ExecutionRequestSchemaVersionUnsupported(
            "Unsupported request schema version."
        )
    if canonical_json(document).encode("utf-8") != canonical_content:
        raise ExecutionRequestReconstructionFailed(
            "Stored request content is not canonical."
        )
    reference_document = document.get("immutable_payload_reference")
    try:
        reference = (
            ImmutablePayloadReference(
                reference=reference_document["reference"],
                canonical_digest=reference_document["canonical_digest"],
                schema_version=reference_document["schema_version"],
            )
            if reference_document is not None
            else None
        )
        draft = ExecutionRequestDraft(
            organization_id=document["organization_id"],
            workload_context_id=document["workload_context_id"],
            requested_work_type=document["requested_work_type"],
            immutable_payload=document.get("immutable_payload"),
            immutable_payload_reference=reference,
            request_constraints=document["request_constraints"],
            provenance=document["provenance"],
            request_schema_version=document["request_schema_version"],
        )
        accepted_identity = document["idempotency_identity"]
        if not isinstance(accepted_identity, str) or not accepted_identity:
            raise ExecutionRequestInvalid("Accepted idempotency identity is required.")
    except (KeyError, TypeError, ExecutionRequestInvalid) as exc:
        raise ExecutionRequestReconstructionFailed(
            "Canonical request evidence is incomplete or invalid."
        ) from exc
    reconstructed, reconstructed_content = build_execution_request(
        draft, accepted_idempotency_identity=accepted_identity
    )
    if reconstructed_content != canonical_content:
        raise ExecutionRequestReconstructionFailed(
            "Reconstructed canonical request content diverged."
        )
    return reconstructed
