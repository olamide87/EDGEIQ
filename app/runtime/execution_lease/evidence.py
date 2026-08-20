from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Callable, Generic, Protocol, TypeVar

from app.runtime.execution_lease.canonical import canonical_json, namespaced_digest
from app.runtime.execution_lease.domain import (
    ExecutionLeaseDigestMismatch,
    ExecutionLeaseEvidenceUnavailable,
    ExecutionLeaseInvalid,
    ExecutionLeaseVersionUnsupported,
    LeasePermission,
    required_text,
    sha256_hex,
    utc_time,
)

AUTHORIZATION_NAMESPACE = "edgeiq.authorization-checkpoint-evidence.v1"
REVOCATION_NAMESPACE = "edgeiq.opaque-retained-revocation-evidence.v1"
SUPPORTED_AUTHORIZATION_SCHEMA = "authorization-checkpoint-evidence.v1"
SUPPORTED_AUTHORIZATION_COMPONENT = "authorization-checkpoint.service.v1"
SUPPORTED_REVOCATION_SCHEMA = "opaque-retained-revocation-evidence.v1"
SUPPORTED_REVOCATION_COMPONENT = "retained-evidence-port.v1"


@dataclass(frozen=True)
class RetainedAuthorizationEvidence:
    authorization_id: str
    organization_id: str
    workload_context_id: str
    principal_id: str
    plan_id: str
    work_item_id: str
    permission_ceiling: tuple[LeasePermission, ...]
    approved: bool
    evaluated_at: datetime
    effective_at: datetime
    expires_at: datetime
    history_boundary: str
    policy_id: str
    policy_version: str
    policy_digest: str
    decision_version: int
    clock_source_id: str
    clock_source_version: str
    correlation_id: str
    causation_id: str
    schema_version: str
    component_version: str
    serialization_version: str
    configuration_version: str
    canonical_digest: str
    canonical_content: bytes


@dataclass(frozen=True)
class OpaqueRetainedRevocationEvidence:
    """Integrity/scope envelope only; it carries no issuer or revocation authority."""

    evidence_id: str
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_id: str
    permission_family: str
    target_lease_id: str
    target_event_id: str
    effective_at: datetime
    schema_version: str
    component_version: str
    serialization_version: str
    canonical_digest: str
    canonical_content: bytes


def build_authorization_evidence(
    *, authorization_id: str, organization_id: str, workload_context_id: str,
    principal_id: str, plan_id: str, work_item_id: str,
    permission_ceiling: tuple[LeasePermission, ...], approved: bool,
    evaluated_at: datetime, effective_at: datetime, expires_at: datetime,
    history_boundary: str, policy_id: str = "authorization-policy",
    policy_version: str = "authorization-policy.v1", policy_digest: str = "a" * 64,
    decision_version: int = 1, clock_source_id: str = "trusted-clock",
    clock_source_version: str = "clock.v1", correlation_id: str = "correlation:1",
    causation_id: str = "causation:1",
    schema_version: str = SUPPORTED_AUTHORIZATION_SCHEMA,
    component_version: str = SUPPORTED_AUTHORIZATION_COMPONENT,
    serialization_version: str = "canonical-json.v1",
    configuration_version: str = "authorization-config.v1",
) -> RetainedAuthorizationEvidence:
    if any(not isinstance(item, LeasePermission) for item in permission_ceiling):
        raise ExecutionLeaseInvalid("Authorization permission ceiling must be non-empty and unique.")
    permissions = tuple(sorted(permission_ceiling, key=lambda item: item.value))
    if not permissions or len(permissions) != len(set(permissions)):
        raise ExecutionLeaseInvalid("Authorization permission ceiling must be non-empty and unique.")
    effective = utc_time(effective_at, "authorization_effective_at")
    expires = utc_time(expires_at, "authorization_expires_at")
    evaluated = utc_time(evaluated_at, "authorization_evaluated_at")
    if expires <= effective:
        raise ExecutionLeaseInvalid("Authorization expiry must follow its effective time.")
    if not isinstance(approved, bool):
        raise ExecutionLeaseInvalid("Authorization approval must be boolean.")
    if not isinstance(decision_version, int) or isinstance(decision_version, bool) or decision_version < 1:
        raise ExecutionLeaseInvalid("Authorization decision version must be a positive integer.")
    document = {
        "approved": approved,
        "authorization_id": required_text(authorization_id, "authorization_id"),
        "component_version": component_version,
        "configuration_version": required_text(configuration_version, "configuration_version"),
        "causation_id": required_text(causation_id, "causation_id"),
        "clock_source_id": required_text(clock_source_id, "clock_source_id"),
        "clock_source_version": required_text(clock_source_version, "clock_source_version"),
        "correlation_id": required_text(correlation_id, "correlation_id"),
        "decision_version": decision_version,
        "effective_at": effective,
        "evaluated_at": evaluated,
        "expires_at": expires,
        "history_boundary": required_text(history_boundary, "history_boundary"),
        "organization_id": required_text(organization_id, "organization_id"),
        "permission_ceiling": permissions,
        "plan_id": required_text(plan_id, "plan_id"),
        "policy_digest": sha256_hex(policy_digest, "policy_digest"),
        "policy_id": required_text(policy_id, "policy_id"),
        "policy_version": required_text(policy_version, "policy_version"),
        "principal_id": required_text(principal_id, "principal_id"),
        "schema_version": schema_version,
        "serialization_version": serialization_version,
        "work_item_id": required_text(work_item_id, "work_item_id"),
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = canonical_json(document).encode("utf-8")
    return RetainedAuthorizationEvidence(**document, canonical_digest=namespaced_digest(AUTHORIZATION_NAMESPACE, content), canonical_content=content)


def build_opaque_revocation_evidence(
    *, evidence_id: str, organization_id: str, workload_context_id: str,
    plan_id: str, work_item_id: str, permission_family: str,
    target_lease_id: str, target_event_id: str, effective_at: datetime,
    schema_version: str = SUPPORTED_REVOCATION_SCHEMA,
    component_version: str = SUPPORTED_REVOCATION_COMPONENT,
    serialization_version: str = "canonical-json.v1",
) -> OpaqueRetainedRevocationEvidence:
    document = {
        "component_version": component_version,
        "evidence_id": required_text(evidence_id, "evidence_id"),
        "effective_at": utc_time(effective_at, "revocation_effective_at"),
        "organization_id": required_text(organization_id, "organization_id"),
        "permission_family": required_text(permission_family, "permission_family"),
        "plan_id": required_text(plan_id, "plan_id"),
        "schema_version": schema_version,
        "serialization_version": serialization_version,
        "target_event_id": required_text(target_event_id, "target_event_id"),
        "target_lease_id": required_text(target_lease_id, "target_lease_id"),
        "work_item_id": required_text(work_item_id, "work_item_id"),
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = canonical_json(document).encode("utf-8")
    return OpaqueRetainedRevocationEvidence(**document, canonical_digest=namespaced_digest(REVOCATION_NAMESPACE, content), canonical_content=content)


def validate_authorization(value: RetainedAuthorizationEvidence) -> None:
    if value.schema_version != SUPPORTED_AUTHORIZATION_SCHEMA or value.component_version != SUPPORTED_AUTHORIZATION_COMPONENT or value.serialization_version != "canonical-json.v1":
        raise ExecutionLeaseVersionUnsupported("Unsupported Authorization Checkpoint evidence version.")
    rebuilt = build_authorization_evidence(
        authorization_id=value.authorization_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, principal_id=value.principal_id,
        plan_id=value.plan_id, work_item_id=value.work_item_id,
        permission_ceiling=value.permission_ceiling, approved=value.approved,
        evaluated_at=value.evaluated_at, effective_at=value.effective_at, expires_at=value.expires_at,
        history_boundary=value.history_boundary, policy_id=value.policy_id,
        policy_version=value.policy_version, policy_digest=value.policy_digest,
        decision_version=value.decision_version, clock_source_id=value.clock_source_id,
        clock_source_version=value.clock_source_version, correlation_id=value.correlation_id,
        causation_id=value.causation_id,
        schema_version=value.schema_version, component_version=value.component_version,
        serialization_version=value.serialization_version, configuration_version=value.configuration_version,
    )
    if rebuilt != value:
        raise ExecutionLeaseDigestMismatch("Retained Authorization Checkpoint evidence failed canonical verification.")


def validate_opaque_revocation(value: OpaqueRetainedRevocationEvidence) -> None:
    if value.schema_version != SUPPORTED_REVOCATION_SCHEMA or value.component_version != SUPPORTED_REVOCATION_COMPONENT or value.serialization_version != "canonical-json.v1":
        raise ExecutionLeaseVersionUnsupported("Unsupported revocation evidence version.")
    rebuilt = build_opaque_revocation_evidence(
        evidence_id=value.evidence_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, plan_id=value.plan_id,
        work_item_id=value.work_item_id, permission_family=value.permission_family,
        target_lease_id=value.target_lease_id, target_event_id=value.target_event_id,
        effective_at=value.effective_at, schema_version=value.schema_version,
        component_version=value.component_version, serialization_version=value.serialization_version,
    )
    if rebuilt != value:
        raise ExecutionLeaseDigestMismatch("Retained revocation evidence failed canonical verification.")


T = TypeVar("T")


class ScopedEvidenceSource(Protocol, Generic[T]):
    def get_scoped(self, artifact_id: str, *, organization_id: str, workload_context_id: str) -> T | None: ...


class InMemoryScopedEvidenceSource(Generic[T]):
    def __init__(self, identity: Callable[[T], str], validator: Callable[[T], None], organization: Callable[[T], str], workload: Callable[[T], str]) -> None:
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
                raise ExecutionLeaseInvalid("Immutable retained evidence cannot be replaced.")
            self._items[key] = value

    def get_scoped(self, artifact_id: str, *, organization_id: str, workload_context_id: str) -> T | None:
        with self._lock:
            value = self._items.get(artifact_id)
        if value is None or self._organization(value) != organization_id or self._workload(value) != workload_context_id:
            return None
        self._validator(value)
        return value


def authorization_source() -> InMemoryScopedEvidenceSource[RetainedAuthorizationEvidence]:
    return InMemoryScopedEvidenceSource(lambda value: value.authorization_id, validate_authorization, lambda value: value.organization_id, lambda value: value.workload_context_id)


def revocation_source() -> InMemoryScopedEvidenceSource[OpaqueRetainedRevocationEvidence]:
    return InMemoryScopedEvidenceSource(lambda value: value.evidence_id, validate_opaque_revocation, lambda value: value.organization_id, lambda value: value.workload_context_id)


def require_evidence(source: ScopedEvidenceSource[T], artifact_id: str, *, organization_id: str, workload_context_id: str) -> T:
    value = source.get_scoped(artifact_id, organization_id=organization_id, workload_context_id=workload_context_id)
    if value is None:
        raise ExecutionLeaseEvidenceUnavailable("Required Execution Lease evidence was not found.")
    return value
