import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


SUPPORTED_REQUEST_SCHEMA_VERSION = "execution-request.v1"


class ExecutionRequestError(RuntimeError):
    code = "ExecutionRequestInternalFailure"


class ExecutionRequestInvalid(ExecutionRequestError):
    code = "ExecutionRequestInvalid"


class ExecutionRequestSchemaVersionUnsupported(ExecutionRequestError):
    code = "ExecutionRequestSchemaVersionUnsupported"


class ExecutionRequestIdempotencyConflict(ExecutionRequestError):
    code = "ExecutionRequestIdempotencyConflict"


class ExecutionRequestNotFound(ExecutionRequestError):
    code = "ExecutionRequestNotFound"


class ExecutionRequestReconstructionFailed(ExecutionRequestError):
    code = "ExecutionRequestReconstructionFailed"


class ExecutionRequestDigestMismatch(ExecutionRequestReconstructionFailed):
    code = "ExecutionRequestDigestMismatch"


class AdmissionOutcome(str, Enum):
    CREATED = "Created"
    EXISTING_EQUIVALENT = "ExistingEquivalent"


def _immutable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ExecutionRequestInvalid("Canonical map keys must be strings.")
        normalized_items = [
            (unicodedata.normalize("NFC", key), _immutable_value(item))
            for key, item in value.items()
        ]
        if len({key for key, _ in normalized_items}) != len(normalized_items):
            raise ExecutionRequestInvalid(
                "Canonical map keys must remain unique after Unicode normalization."
            )
        return MappingProxyType(
            {key: item for key, item in sorted(normalized_items)}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_immutable_value(item) for item in value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (int, bool)):
        return value
    raise ExecutionRequestInvalid(
        f"Unsupported canonical value: {type(value).__name__}."
    )


def immutable_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    frozen = _immutable_value(values or {})
    assert isinstance(frozen, Mapping)
    return frozen


@dataclass(frozen=True)
class ImmutablePayloadReference:
    reference: str
    canonical_digest: str
    schema_version: str

    def __post_init__(self) -> None:
        if not self.reference or not self.canonical_digest or not self.schema_version:
            raise ExecutionRequestInvalid(
                "Payload references require reference, canonical digest, and schema version."
            )
        if len(self.canonical_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.canonical_digest
        ):
            raise ExecutionRequestInvalid(
                "Payload reference canonical digest must be lowercase SHA-256 hex."
            )
        object.__setattr__(self, "reference", _immutable_value(self.reference))
        object.__setattr__(
            self, "schema_version", _immutable_value(self.schema_version)
        )


@dataclass(frozen=True)
class ExecutionRequestDraft:
    organization_id: str
    workload_context_id: str
    requested_work_type: str
    immutable_payload: Any | None = None
    immutable_payload_reference: ImmutablePayloadReference | None = None
    request_constraints: Mapping[str, Any] = field(default_factory=immutable_mapping)
    provenance: Mapping[str, Any] = field(default_factory=immutable_mapping)
    request_schema_version: str = SUPPORTED_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "organization_id",
            "workload_context_id",
            "requested_work_type",
            "request_schema_version",
        ):
            if not getattr(self, name):
                raise ExecutionRequestInvalid(f"{name} is required.")
            object.__setattr__(self, name, _immutable_value(getattr(self, name)))
        if self.request_schema_version != SUPPORTED_REQUEST_SCHEMA_VERSION:
            raise ExecutionRequestSchemaVersionUnsupported(
                f"Unsupported request schema version: {self.request_schema_version}."
            )
        has_payload = self.immutable_payload is not None
        has_reference = self.immutable_payload_reference is not None
        if has_payload == has_reference:
            raise ExecutionRequestInvalid(
                "Exactly one immutable payload or immutable payload reference is required."
            )
        if has_payload:
            object.__setattr__(
                self, "immutable_payload", _immutable_value(self.immutable_payload)
            )
        object.__setattr__(
            self, "request_constraints", immutable_mapping(self.request_constraints)
        )
        object.__setattr__(self, "provenance", immutable_mapping(self.provenance))
        if not self.provenance:
            raise ExecutionRequestInvalid("Request provenance is required.")


@dataclass(frozen=True)
class ExecutionRequest:
    request_id: str
    organization_id: str
    workload_context_id: str
    request_schema_version: str
    requested_work_type: str
    immutable_payload: Any | None
    immutable_payload_reference: ImmutablePayloadReference | None
    request_constraints: Mapping[str, Any]
    provenance: Mapping[str, Any]
    idempotency_identity: str
    canonical_digest: str

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "organization_id",
            "workload_context_id",
            "request_schema_version",
            "requested_work_type",
            "idempotency_identity",
            "canonical_digest",
        ):
            if not getattr(self, name):
                raise ExecutionRequestInvalid(f"{name} is required.")
        if self.request_schema_version != SUPPORTED_REQUEST_SCHEMA_VERSION:
            raise ExecutionRequestSchemaVersionUnsupported(
                f"Unsupported request schema version: {self.request_schema_version}."
            )
        for name in ("request_id", "idempotency_identity", "canonical_digest"):
            value = getattr(self, name)
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ExecutionRequestInvalid(
                    f"{name} must be lowercase SHA-256 hex."
                )
        has_payload = self.immutable_payload is not None
        has_reference = self.immutable_payload_reference is not None
        if has_payload == has_reference:
            raise ExecutionRequestInvalid(
                "Exactly one immutable payload or immutable payload reference is required."
            )
        object.__setattr__(
            self, "request_constraints", immutable_mapping(self.request_constraints)
        )
        object.__setattr__(self, "provenance", immutable_mapping(self.provenance))
        if not self.provenance:
            raise ExecutionRequestInvalid("Request provenance is required.")
        if self.immutable_payload is not None:
            object.__setattr__(
                self, "immutable_payload", _immutable_value(self.immutable_payload)
            )


@dataclass(frozen=True)
class AdmissionResult:
    outcome: AdmissionOutcome
    request: ExecutionRequest
