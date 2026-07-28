import hashlib
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Protocol

from app.runtime.execution_plan.domain import (
    ExecutionPlanRequestInvalid,
    ExecutionPlanSchemaVersionUnsupported,
)
from app.runtime.execution_request.serialization import canonical_json


SUPPORTED_VALIDATION_SCHEMA_VERSION = "request-validation.v1"
VALIDATION_DIGEST_NAMESPACE = "edgeiq.request-validation.v1"
VALIDATION_ID_NAMESPACE = "edgeiq.request-validation-id.v1"


class ValidationOutcome(str, Enum):
    VALID = "Valid"
    INVALID = "Invalid"


@dataclass(frozen=True)
class RequestValidationEvidence:
    validation_evidence_id: str
    request_id: str
    canonical_request_digest: str
    organization_id: str
    workload_context_id: str
    validation_policy_version: str
    outcome: ValidationOutcome
    findings: tuple[str, ...]
    history_boundary: str
    schema_version: str
    canonical_digest: str


class RequestValidationEvidenceSource(Protocol):
    def get(
        self, validation_evidence_id: str
    ) -> RequestValidationEvidence | None: ...


def _sha256(namespace: str, content: bytes) -> str:
    return hashlib.sha256(namespace.encode() + b"\n" + content).hexdigest()


def _document(
    *,
    request_id: str,
    canonical_request_digest: str,
    organization_id: str,
    workload_context_id: str,
    validation_policy_version: str,
    outcome: ValidationOutcome,
    findings: tuple[str, ...],
    history_boundary: str,
) -> dict[str, object]:
    return {
        "canonical_request_digest": canonical_request_digest,
        "findings": tuple(sorted(findings)),
        "history_boundary": history_boundary,
        "organization_id": organization_id,
        "outcome": outcome.value,
        "request_id": request_id,
        "schema_version": SUPPORTED_VALIDATION_SCHEMA_VERSION,
        "validation_policy_version": validation_policy_version,
        "workload_context_id": workload_context_id,
    }


def build_request_validation_evidence(
    *,
    request_id: str,
    canonical_request_digest: str,
    organization_id: str,
    workload_context_id: str,
    validation_policy_version: str,
    outcome: ValidationOutcome,
    findings: tuple[str, ...] = (),
    history_boundary: str,
) -> RequestValidationEvidence:
    document = _document(
        request_id=request_id,
        canonical_request_digest=canonical_request_digest,
        organization_id=organization_id,
        workload_context_id=workload_context_id,
        validation_policy_version=validation_policy_version,
        outcome=outcome,
        findings=findings,
        history_boundary=history_boundary,
    )
    content = canonical_json(document).encode()
    digest = _sha256(VALIDATION_DIGEST_NAMESPACE, content)
    evidence_id = _sha256(VALIDATION_ID_NAMESPACE, digest.encode())
    return RequestValidationEvidence(
        validation_evidence_id=evidence_id,
        request_id=request_id,
        canonical_request_digest=canonical_request_digest,
        organization_id=organization_id,
        workload_context_id=workload_context_id,
        validation_policy_version=validation_policy_version,
        outcome=outcome,
        findings=tuple(sorted(findings)),
        history_boundary=history_boundary,
        schema_version=SUPPORTED_VALIDATION_SCHEMA_VERSION,
        canonical_digest=digest,
    )


def validate_request_validation_evidence(
    evidence: RequestValidationEvidence,
) -> None:
    if evidence.schema_version != SUPPORTED_VALIDATION_SCHEMA_VERSION:
        raise ExecutionPlanSchemaVersionUnsupported(
            "Unsupported Request Validation evidence schema."
        )
    try:
        rebuilt = build_request_validation_evidence(
            request_id=evidence.request_id,
            canonical_request_digest=evidence.canonical_request_digest,
            organization_id=evidence.organization_id,
            workload_context_id=evidence.workload_context_id,
            validation_policy_version=evidence.validation_policy_version,
            outcome=evidence.outcome,
            findings=evidence.findings,
            history_boundary=evidence.history_boundary,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionPlanRequestInvalid(
            "Request Validation evidence is malformed."
        ) from exc
    if rebuilt != evidence:
        raise ExecutionPlanRequestInvalid(
            "Request Validation evidence failed canonical verification."
        )


class InMemoryRequestValidationEvidenceRepository:
    """Reference boundary for immutable validation-owner evidence."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_id: dict[str, RequestValidationEvidence] = {}

    def retain(self, evidence: RequestValidationEvidence) -> None:
        validate_request_validation_evidence(evidence)
        with self._lock:
            prior = self._by_id.get(evidence.validation_evidence_id)
            if prior is not None and prior != evidence:
                raise ExecutionPlanRequestInvalid(
                    "Validation evidence identity conflicts with retained evidence."
                )
            self._by_id[evidence.validation_evidence_id] = evidence

    def get(
        self, validation_evidence_id: str
    ) -> RequestValidationEvidence | None:
        with self._lock:
            return self._by_id.get(validation_evidence_id)
