import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

SUPPORTED_EXECUTION_LEASE_SCHEMA_VERSION = "execution-lease.v1"
SUPPORTED_EXECUTION_LEASE_COMPONENT_VERSION = "execution-lease.service.v1"
SUPPORTED_SERIALIZATION_VERSION = "canonical-json.v1"
SUPPORTED_PERMISSION_FAMILY = "work-item-execution.v1"


class ExecutionLeaseError(RuntimeError):
    code = "ExecutionLeaseInternalFailure"


class ExecutionLeaseInvalid(ExecutionLeaseError):
    code = "ExecutionLeaseInvalid"


class ExecutionLeaseEvidenceUnavailable(ExecutionLeaseInvalid):
    code = "ExecutionLeaseEvidenceUnavailable"


class ExecutionLeaseDigestMismatch(ExecutionLeaseInvalid):
    code = "ExecutionLeaseDigestMismatch"


class ExecutionLeaseVersionUnsupported(ExecutionLeaseInvalid):
    code = "ExecutionLeaseVersionUnsupported"


class ExecutionLeaseIllegalTransition(ExecutionLeaseInvalid):
    code = "ExecutionLeaseIllegalTransition"


class ExecutionLeaseIdempotencyConflict(ExecutionLeaseError):
    code = "ExecutionLeaseIdempotencyConflict"


class ExecutionLeaseVersionConflict(ExecutionLeaseError):
    code = "ExecutionLeaseVersionConflict"


class ExecutionLeaseNotFound(ExecutionLeaseError):
    code = "ExecutionLeaseNotFound"


class ExecutionLeasePersistenceFailure(ExecutionLeaseError):
    code = "ExecutionLeasePersistenceFailure"


class ExecutionLeaseReconstructionFailed(ExecutionLeaseError):
    code = "ExecutionLeaseReconstructionFailed"


class ExecutionLeaseReplayDiverged(ExecutionLeaseReconstructionFailed):
    code = "ExecutionLeaseReplayDiverged"


class LeaseOperation(str, Enum):
    GRANT = "Grant"
    RENEW = "Renew"
    REVOKE = "Revoke"
    SUPERSEDE = "Supersede"


class LeaseEventType(str, Enum):
    GRANTED = "LeaseGranted"
    RENEWED = "LeaseRenewed"
    REVOKED = "LeaseRevoked"
    SUPERSEDED = "LeaseSuperseded"


class LeasePermission(str, Enum):
    OFFER_WORK_ITEM = "OFFER_WORK_ITEM"
    INITIATE_WORK_ITEM_EXECUTION = "INITIATE_WORK_ITEM_EXECUTION"


class LeaseEvaluationOutcome(str, Enum):
    CREATED = "Created"
    EXISTING_EQUIVALENT = "ExistingEquivalent"


def required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionLeaseInvalid(f"{field_name} is required.")
    return unicodedata.normalize("NFC", value)


def optional_text(value: str | None, field_name: str) -> str | None:
    return None if value is None else required_text(value, field_name)


def sha256_hex(value: str, field_name: str) -> str:
    value = required_text(value, field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ExecutionLeaseInvalid(f"{field_name} must be lowercase SHA-256 hex.")
    return value


def utc_time(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionLeaseInvalid(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, order=True)
class EvidenceReference:
    artifact_id: str
    canonical_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", required_text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "canonical_digest", sha256_hex(self.canonical_digest, "canonical_digest"))


@dataclass(frozen=True)
class ExecutionLeaseRequest:
    operation: LeaseOperation
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_id: str
    permission_family: str
    requested_permissions: tuple[LeasePermission, ...]
    authorization_evidence_id: str | None
    authorization_evidence_digest: str | None
    authorization_history_boundary: str | None
    prior_event_id: str | None
    revocation_evidence_id: str | None
    revocation_evidence_digest: str | None
    effective_at: datetime
    expires_at: datetime | None
    evaluation_at: datetime
    clock_source_id: str
    clock_source_version: str
    lease_policy_id: str
    lease_policy_version: str
    lease_policy_digest: str
    configuration_version: str
    expected_lineage_version: int
    idempotency_key: str
    schema_version: str = SUPPORTED_EXECUTION_LEASE_SCHEMA_VERSION
    component_version: str = SUPPORTED_EXECUTION_LEASE_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.operation, LeaseOperation):
            raise ExecutionLeaseInvalid("A supported Execution Lease operation is required.")
        for name in (
            "organization_id", "workload_context_id", "plan_id", "work_item_id",
            "permission_family", "clock_source_id", "clock_source_version",
            "lease_policy_id", "lease_policy_version", "configuration_version",
            "idempotency_key",
        ):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        if self.permission_family != SUPPORTED_PERMISSION_FAMILY:
            raise ExecutionLeaseVersionUnsupported("Unsupported Execution Lease permission family.")
        if any(not isinstance(item, LeasePermission) for item in self.requested_permissions):
            raise ExecutionLeaseInvalid("Unknown lease permissions fail closed.")
        permissions = tuple(sorted(self.requested_permissions, key=lambda item: item.value))
        if len(permissions) != len(set(permissions)):
            raise ExecutionLeaseInvalid("Lease permissions must be unique.")
        object.__setattr__(self, "requested_permissions", permissions)
        for name in (
            "authorization_evidence_id", "authorization_history_boundary", "prior_event_id",
            "revocation_evidence_id",
        ):
            object.__setattr__(self, name, optional_text(getattr(self, name), name))
        for name in ("authorization_evidence_digest", "revocation_evidence_digest"):
            value = getattr(self, name)
            object.__setattr__(self, name, None if value is None else sha256_hex(value, name))
        object.__setattr__(self, "lease_policy_digest", sha256_hex(self.lease_policy_digest, "lease_policy_digest"))
        object.__setattr__(self, "effective_at", utc_time(self.effective_at, "effective_at"))
        object.__setattr__(self, "evaluation_at", utc_time(self.evaluation_at, "evaluation_at"))
        object.__setattr__(self, "expires_at", None if self.expires_at is None else utc_time(self.expires_at, "expires_at"))
        if not isinstance(self.expected_lineage_version, int) or isinstance(self.expected_lineage_version, bool) or self.expected_lineage_version < 0:
            raise ExecutionLeaseInvalid("expected_lineage_version must be a non-negative integer.")
        authority = (self.authorization_evidence_id, self.authorization_evidence_digest, self.authorization_history_boundary)
        if self.operation is LeaseOperation.REVOKE:
            if any(authority) or self.requested_permissions or self.expires_at is not None:
                raise ExecutionLeaseInvalid("Revocation accepts no authorization grant input, permissions, or expiry.")
            if not self.prior_event_id or not self.revocation_evidence_id or not self.revocation_evidence_digest:
                raise ExecutionLeaseInvalid("Revocation requires prior-event and retained directive references.")
        else:
            if not all(authority) or not self.requested_permissions or self.expires_at is None:
                raise ExecutionLeaseInvalid("Grant, renewal, and supersession require complete authorization and bounded permission input.")
            if self.revocation_evidence_id is not None or self.revocation_evidence_digest is not None:
                raise ExecutionLeaseInvalid("Revocation evidence is valid only for revocation.")
            if self.expires_at <= self.effective_at:
                raise ExecutionLeaseInvalid("Lease expiry must follow its effective time.")
            if self.operation is LeaseOperation.GRANT and self.prior_event_id is not None:
                raise ExecutionLeaseInvalid("Initial grant has no caller-authored prior event.")
            if self.operation is not LeaseOperation.GRANT and self.prior_event_id is None:
                raise ExecutionLeaseInvalid("Lifecycle continuation requires an exact prior event reference.")
        if self.schema_version != SUPPORTED_EXECUTION_LEASE_SCHEMA_VERSION:
            raise ExecutionLeaseVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")
        if self.component_version != SUPPORTED_EXECUTION_LEASE_COMPONENT_VERSION:
            raise ExecutionLeaseVersionUnsupported(f"Unsupported component version: {self.component_version}.")
        if self.serialization_version != SUPPORTED_SERIALIZATION_VERSION:
            raise ExecutionLeaseVersionUnsupported("Unsupported serialization version.")

    @property
    def lineage_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.organization_id,
            self.workload_context_id,
            self.plan_id,
            self.work_item_id,
            self.permission_family,
        )


@dataclass(frozen=True)
class LeaseReconstructionMetadata:
    authorization_history_boundary: str | None
    evaluation_at: datetime
    clock_source_id: str
    clock_source_version: str
    configuration_version: str
    component_version: str = SUPPORTED_EXECUTION_LEASE_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorization_history_boundary", optional_text(self.authorization_history_boundary, "authorization_history_boundary"))
        object.__setattr__(self, "evaluation_at", utc_time(self.evaluation_at, "evaluation_at"))
        for name in ("clock_source_id", "clock_source_version", "configuration_version"):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        if self.component_version != SUPPORTED_EXECUTION_LEASE_COMPONENT_VERSION or self.serialization_version != SUPPORTED_SERIALIZATION_VERSION:
            raise ExecutionLeaseVersionUnsupported("Unsupported reconstruction metadata version.")


@dataclass(frozen=True)
class ExecutionLeaseEvent:
    event_id: str
    lease_id: str
    lineage_id: str
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_id: str
    permission_family: str
    event_type: LeaseEventType
    permissions: tuple[LeasePermission, ...]
    authorization_reference: EvidenceReference | None
    revocation_reference: EvidenceReference | None
    policy_reference: EvidenceReference
    policy_version: str
    generation: int
    lineage_version: int
    prior_event_id: str | None
    superseded_lease_id: str | None
    effective_at: datetime
    expires_at: datetime | None
    canonical_input_digest: str
    canonical_event_digest: str
    idempotency_identity: str
    reconstruction_metadata: LeaseReconstructionMetadata
    recorded_at: datetime
    schema_version: str = SUPPORTED_EXECUTION_LEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("event_id", "lease_id", "lineage_id", "canonical_input_digest", "canonical_event_digest", "idempotency_identity"):
            object.__setattr__(self, name, sha256_hex(getattr(self, name), name))
        for name in ("organization_id", "workload_context_id", "plan_id", "work_item_id", "permission_family", "policy_version"):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        if self.permission_family != SUPPORTED_PERMISSION_FAMILY:
            raise ExecutionLeaseVersionUnsupported("Unsupported Execution Lease permission family.")
        if not isinstance(self.event_type, LeaseEventType):
            raise ExecutionLeaseInvalid("A valid lease event type is required.")
        if any(not isinstance(item, LeasePermission) for item in self.permissions):
            raise ExecutionLeaseInvalid("Event permissions must be canonical and unique.")
        permissions = tuple(sorted(self.permissions, key=lambda item: item.value))
        if len(permissions) != len(set(permissions)):
            raise ExecutionLeaseInvalid("Event permissions must be canonical and unique.")
        object.__setattr__(self, "permissions", permissions)
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise ExecutionLeaseInvalid("generation must be a positive integer.")
        if not isinstance(self.lineage_version, int) or isinstance(self.lineage_version, bool) or self.lineage_version < 1:
            raise ExecutionLeaseInvalid("lineage_version must be a positive integer.")
        object.__setattr__(self, "prior_event_id", optional_text(self.prior_event_id, "prior_event_id"))
        object.__setattr__(self, "superseded_lease_id", optional_text(self.superseded_lease_id, "superseded_lease_id"))
        object.__setattr__(self, "effective_at", utc_time(self.effective_at, "effective_at"))
        object.__setattr__(self, "expires_at", None if self.expires_at is None else utc_time(self.expires_at, "expires_at"))
        object.__setattr__(self, "recorded_at", utc_time(self.recorded_at, "recorded_at"))
        if self.event_type is LeaseEventType.REVOKED:
            if permissions or self.authorization_reference is not None or self.revocation_reference is None or self.expires_at is not None:
                raise ExecutionLeaseInvalid("Revocation event evidence is malformed.")
        elif not permissions or self.authorization_reference is None or self.revocation_reference is not None or self.expires_at is None or self.expires_at <= self.effective_at:
            raise ExecutionLeaseInvalid("Lease authority event evidence is malformed.")
        if self.event_type is LeaseEventType.GRANTED and self.prior_event_id is not None:
            raise ExecutionLeaseInvalid("Initial grant cannot reference a prior event.")
        if self.event_type is not LeaseEventType.GRANTED and self.prior_event_id is None:
            raise ExecutionLeaseInvalid("Lifecycle event requires prior-event causality.")
        if self.event_type is LeaseEventType.SUPERSEDED and self.superseded_lease_id is None:
            raise ExecutionLeaseInvalid("Supersession requires the prior lease identity.")
        if self.event_type is not LeaseEventType.SUPERSEDED and self.superseded_lease_id is not None:
            raise ExecutionLeaseInvalid("Only supersession may identify a superseded lease.")
        if self.schema_version != SUPPORTED_EXECUTION_LEASE_SCHEMA_VERSION:
            raise ExecutionLeaseVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")

    def applicable_at(self, evaluation_at: datetime) -> bool:
        evaluated = utc_time(evaluation_at, "evaluation_at")
        return self.event_type in (LeaseEventType.GRANTED, LeaseEventType.RENEWED, LeaseEventType.SUPERSEDED) and self.expires_at is not None and self.effective_at <= evaluated < self.expires_at


@dataclass(frozen=True)
class ExecutionLeaseEvaluationResult:
    outcome: LeaseEvaluationOutcome
    event: ExecutionLeaseEvent
    lineage_version: int
