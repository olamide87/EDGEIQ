from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Callable, Generic, Protocol, TypeVar

from app.runtime.dispatch_decision.domain import DispatchDecisionError, DispatchDecisionOutcome
from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.dispatch_decision.serialization import verify_recorded_content
from app.runtime.work_claim.canonical import canonical_json, namespaced_digest
from app.runtime.work_claim.domain import (
    WorkClaimDigestMismatch,
    WorkClaimEvidenceUnavailable,
    WorkClaimInvalid,
    WorkClaimVersionUnsupported,
    required_text,
    utc_time,
)

CLAIMANT_EVIDENCE_NAMESPACE = "edgeiq.work-claim-claimant-evidence.v1"
SUPPORTED_CLAIMANT_EVIDENCE_SCHEMA = "claimant-evidence.v1"
SUPPORTED_CLAIMANT_PRODUCER_VERSION = "claimant-evidence.producer.v1"


@dataclass(frozen=True)
class RetainedClaimantEvidence:
    evidence_id: str
    claimant_id: str
    selected_candidate_id: str
    organization_id: str
    workload_context_id: str
    authentication_boundary: str
    effective_at: datetime
    expires_at: datetime
    schema_version: str
    producer_version: str
    canonical_digest: str
    canonical_content: bytes


def build_claimant_evidence(
    *,
    evidence_id: str,
    claimant_id: str,
    selected_candidate_id: str,
    organization_id: str,
    workload_context_id: str,
    authentication_boundary: str,
    effective_at: datetime,
    expires_at: datetime,
    schema_version: str = SUPPORTED_CLAIMANT_EVIDENCE_SCHEMA,
    producer_version: str = SUPPORTED_CLAIMANT_PRODUCER_VERSION,
) -> RetainedClaimantEvidence:
    effective = utc_time(effective_at, "claimant_effective_at")
    expires = utc_time(expires_at, "claimant_expires_at")
    if expires < effective:
        raise WorkClaimInvalid("Claimant evidence expiry cannot precede its effective time.")
    document = {
        "authentication_boundary": required_text(authentication_boundary, "authentication_boundary"),
        "claimant_id": required_text(claimant_id, "claimant_id"),
        "effective_at": effective,
        "evidence_id": required_text(evidence_id, "evidence_id"),
        "expires_at": expires,
        "organization_id": required_text(organization_id, "organization_id"),
        "producer_version": producer_version,
        "schema_version": schema_version,
        "selected_candidate_id": required_text(selected_candidate_id, "selected_candidate_id"),
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = canonical_json(document).encode("utf-8")
    return RetainedClaimantEvidence(
        **document,
        canonical_digest=namespaced_digest(CLAIMANT_EVIDENCE_NAMESPACE, content),
        canonical_content=content,
    )


def validate_claimant_evidence(value: RetainedClaimantEvidence) -> None:
    if (
        value.schema_version != SUPPORTED_CLAIMANT_EVIDENCE_SCHEMA
        or value.producer_version != SUPPORTED_CLAIMANT_PRODUCER_VERSION
    ):
        raise WorkClaimVersionUnsupported("Unsupported claimant evidence schema or producer version.")
    rebuilt = build_claimant_evidence(
        evidence_id=value.evidence_id,
        claimant_id=value.claimant_id,
        selected_candidate_id=value.selected_candidate_id,
        organization_id=value.organization_id,
        workload_context_id=value.workload_context_id,
        authentication_boundary=value.authentication_boundary,
        effective_at=value.effective_at,
        expires_at=value.expires_at,
        schema_version=value.schema_version,
        producer_version=value.producer_version,
    )
    if rebuilt != value:
        raise WorkClaimDigestMismatch("Retained claimant evidence failed canonical verification.")


def validate_dispatch_record(record: DispatchDecisionRecord) -> None:
    try:
        verify_recorded_content(
            record.decision,
            record.canonical_input_content,
            record.canonical_decision_content,
        )
    except DispatchDecisionError as exc:
        raise WorkClaimDigestMismatch("Retained Dispatch evidence failed canonical verification.") from exc
    if record.decision.outcome is not DispatchDecisionOutcome.APPROVED:
        raise WorkClaimInvalid("Work Claim requires an approved Dispatch Decision.")


T = TypeVar("T")


class ScopedEvidenceSource(Protocol, Generic[T]):
    def get_scoped(
        self,
        artifact_id: str,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> T | None: ...


class InMemoryScopedEvidenceSource(Generic[T]):
    def __init__(
        self,
        identity: Callable[[T], str],
        validator: Callable[[T], None],
        organization: Callable[[T], str],
        workload: Callable[[T], str],
    ) -> None:
        self._identity = identity
        self._validator = validator
        self._organization = organization
        self._workload = workload
        self._items: dict[str, T] = {}
        self._lock = RLock()

    def retain(self, value: T) -> None:
        self._validator(value)
        key = self._identity(value)
        with self._lock:
            prior = self._items.get(key)
            if prior is not None and prior != value:
                raise WorkClaimInvalid("Immutable retained evidence cannot be replaced.")
            self._items[key] = value

    def get_scoped(
        self,
        artifact_id: str,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> T | None:
        with self._lock:
            value = self._items.get(artifact_id)
        if value is None:
            return None
        if self._organization(value) != organization_id or self._workload(value) != workload_context_id:
            return None
        self._validator(value)
        return value


def claimant_source() -> InMemoryScopedEvidenceSource[RetainedClaimantEvidence]:
    return InMemoryScopedEvidenceSource(
        lambda value: value.evidence_id,
        validate_claimant_evidence,
        lambda value: value.organization_id,
        lambda value: value.workload_context_id,
    )


def dispatch_source() -> InMemoryScopedEvidenceSource[DispatchDecisionRecord]:
    return InMemoryScopedEvidenceSource(
        lambda value: value.decision.dispatch_decision_id,
        validate_dispatch_record,
        lambda value: value.decision.organization_id,
        lambda value: value.decision.workload_context_id,
    )


def require_evidence(
    source: ScopedEvidenceSource[T],
    artifact_id: str,
    *,
    organization_id: str,
    workload_context_id: str,
) -> T:
    value = source.get_scoped(
        artifact_id,
        organization_id=organization_id,
        workload_context_id=workload_context_id,
    )
    if value is None:
        raise WorkClaimEvidenceUnavailable("Required Work Claim evidence was not found.")
    return value
