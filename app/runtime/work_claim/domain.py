import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

SUPPORTED_WORK_CLAIM_SCHEMA_VERSION = "work-claim.v1"
SUPPORTED_WORK_CLAIM_COMPONENT_VERSION = "work-claim.service.v1"
SUPPORTED_SERIALIZATION_VERSION = "canonical-json.v1"


class WorkClaimError(RuntimeError):
    code = "WorkClaimInternalFailure"


class WorkClaimInvalid(WorkClaimError):
    code = "WorkClaimInvalid"


class WorkClaimEvidenceUnavailable(WorkClaimInvalid):
    code = "WorkClaimEvidenceUnavailable"


class WorkClaimDigestMismatch(WorkClaimInvalid):
    code = "WorkClaimDigestMismatch"


class WorkClaimScopeMismatch(WorkClaimInvalid):
    code = "WorkClaimScopeMismatch"


class WorkClaimVersionUnsupported(WorkClaimInvalid):
    code = "WorkClaimVersionUnsupported"


class WorkClaimIllegalTransition(WorkClaimInvalid):
    code = "WorkClaimIllegalTransition"


class WorkClaimIdempotencyConflict(WorkClaimError):
    code = "WorkClaimIdempotencyConflict"


class WorkClaimVersionConflict(WorkClaimError):
    code = "WorkClaimVersionConflict"


class WorkClaimNotFound(WorkClaimError):
    code = "WorkClaimNotFound"


class WorkClaimPersistenceFailure(WorkClaimError):
    code = "WorkClaimPersistenceFailure"


class WorkClaimReconstructionFailed(WorkClaimError):
    code = "WorkClaimReconstructionFailed"


class WorkClaimReplayDiverged(WorkClaimReconstructionFailed):
    code = "WorkClaimReplayDiverged"


class WorkClaimOperation(str, Enum):
    CREATE_GENERATION = "CreateGeneration"
    CLAIM = "Claim"
    EXPIRE = "Expire"
    RELEASE = "Release"


class WorkClaimEventType(str, Enum):
    GENERATION_CREATED = "GenerationCreated"
    CLAIM_ACCEPTED = "ClaimAccepted"
    CLAIM_REJECTED = "ClaimRejected"
    CLAIM_EXPIRED = "ClaimExpired"
    CLAIM_RELEASED = "ClaimReleased"


class WorkClaimOutcome(str, Enum):
    GENERATION_CREATED = "GenerationCreated"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    EXPIRED = "Expired"
    RELEASED = "Released"


class WorkClaimEvaluationOutcome(str, Enum):
    CREATED = "Created"
    EXISTING_EQUIVALENT = "ExistingEquivalent"


def required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkClaimInvalid(f"{field_name} is required.")
    return unicodedata.normalize("NFC", value)


def optional_text(value: str | None, field_name: str) -> str | None:
    return None if value is None else required_text(value, field_name)


def sha256_hex(value: str, field_name: str) -> str:
    value = required_text(value, field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise WorkClaimInvalid(f"{field_name} must be lowercase SHA-256 hex.")
    return value


def utc_time(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise WorkClaimInvalid(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, order=True)
class EvidenceReference:
    artifact_id: str
    canonical_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", required_text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "canonical_digest", sha256_hex(self.canonical_digest, "canonical_digest"))


@dataclass(frozen=True)
class WorkClaimRequest:
    operation: WorkClaimOperation
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_id: str
    dispatch_decision_id: str
    dispatch_decision_digest: str
    claimant_evidence_id: str
    claimant_evidence_digest: str
    selected_candidate_id: str
    claim_policy_id: str
    claim_policy_version: str
    claim_policy_digest: str
    evidence_boundary: str
    semantic_at: datetime
    clock_source_id: str
    clock_source_version: str
    configuration_version: str
    expected_lineage_version: int
    idempotency_key: str
    release_reason: str | None = None
    schema_version: str = SUPPORTED_WORK_CLAIM_SCHEMA_VERSION
    component_version: str = SUPPORTED_WORK_CLAIM_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.operation, WorkClaimOperation):
            raise WorkClaimInvalid("A supported Work Claim operation is required.")
        for name in (
            "organization_id", "workload_context_id", "plan_id", "work_item_id",
            "dispatch_decision_id", "claimant_evidence_id", "selected_candidate_id",
            "claim_policy_id", "claim_policy_version", "evidence_boundary",
            "clock_source_id", "clock_source_version", "configuration_version",
            "idempotency_key",
        ):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        for name in (
            "dispatch_decision_digest", "claimant_evidence_digest", "claim_policy_digest",
        ):
            object.__setattr__(self, name, sha256_hex(getattr(self, name), name))
        object.__setattr__(self, "semantic_at", utc_time(self.semantic_at, "semantic_at"))
        object.__setattr__(self, "release_reason", optional_text(self.release_reason, "release_reason"))
        if not isinstance(self.expected_lineage_version, int) or isinstance(self.expected_lineage_version, bool) or self.expected_lineage_version < 0:
            raise WorkClaimInvalid("expected_lineage_version must be a non-negative integer.")
        if self.operation is WorkClaimOperation.RELEASE and self.release_reason is None:
            raise WorkClaimInvalid("release_reason is required for release.")
        if self.operation is not WorkClaimOperation.RELEASE and self.release_reason is not None:
            raise WorkClaimInvalid("release_reason is valid only for release.")
        if self.schema_version != SUPPORTED_WORK_CLAIM_SCHEMA_VERSION:
            raise WorkClaimVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")
        if self.component_version != SUPPORTED_WORK_CLAIM_COMPONENT_VERSION:
            raise WorkClaimVersionUnsupported(f"Unsupported component version: {self.component_version}.")
        if self.serialization_version != SUPPORTED_SERIALIZATION_VERSION:
            raise WorkClaimVersionUnsupported("Unsupported serialization version.")

    @property
    def lineage_key(self) -> tuple[str, str, str, str]:
        return (
            self.organization_id,
            self.workload_context_id,
            self.plan_id,
            self.work_item_id,
        )


@dataclass(frozen=True)
class WorkClaimReconstructionMetadata:
    evidence_boundary: str
    semantic_at: datetime
    clock_source_id: str
    clock_source_version: str
    configuration_version: str
    component_version: str = SUPPORTED_WORK_CLAIM_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION


@dataclass(frozen=True)
class WorkClaimEvent:
    event_id: str
    lineage_id: str
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_id: str
    event_type: WorkClaimEventType
    outcome: WorkClaimOutcome
    reason_codes: tuple[str, ...]
    dispatch_reference: EvidenceReference
    claimant_reference: EvidenceReference
    claimant_id: str
    selected_candidate_id: str
    claim_policy_reference: EvidenceReference
    claim_policy_version: str
    lineage_version: int
    generation: int
    fence: int | None
    semantic_at: datetime
    expires_at: datetime | None
    release_reason: str | None
    causal_event_id: str | None
    canonical_input_digest: str
    canonical_event_digest: str
    idempotency_identity: str
    reconstruction_metadata: WorkClaimReconstructionMetadata
    recorded_at: datetime
    schema_version: str = SUPPORTED_WORK_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "event_id", "lineage_id", "canonical_input_digest", "canonical_event_digest",
            "idempotency_identity",
        ):
            object.__setattr__(self, name, sha256_hex(getattr(self, name), name))
        for name in (
            "organization_id", "workload_context_id", "plan_id", "work_item_id",
            "claimant_id", "selected_candidate_id", "claim_policy_version",
        ):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        if not isinstance(self.event_type, WorkClaimEventType) or not isinstance(self.outcome, WorkClaimOutcome):
            raise WorkClaimInvalid("Valid event type and outcome are required.")
        if not isinstance(self.lineage_version, int) or isinstance(self.lineage_version, bool) or self.lineage_version < 1:
            raise WorkClaimInvalid("lineage_version must be a positive integer.")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise WorkClaimInvalid("generation must be a positive integer.")
        if self.fence is not None and (not isinstance(self.fence, int) or isinstance(self.fence, bool) or self.fence < 1):
            raise WorkClaimInvalid("fence must be a positive integer when present.")
        if self.event_type is WorkClaimEventType.CLAIM_ACCEPTED and self.fence is None:
            raise WorkClaimInvalid("Accepted claims require a fence.")
        if self.event_type is not WorkClaimEventType.CLAIM_ACCEPTED and self.fence is not None:
            raise WorkClaimInvalid("Only accepted claims may contain a fence.")
        reasons = tuple(sorted(required_text(value, "reason_code") for value in self.reason_codes))
        if not reasons or len(reasons) != len(set(reasons)):
            raise WorkClaimInvalid("Reason codes must be non-empty and unique.")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "semantic_at", utc_time(self.semantic_at, "semantic_at"))
        object.__setattr__(self, "expires_at", None if self.expires_at is None else utc_time(self.expires_at, "expires_at"))
        object.__setattr__(self, "release_reason", optional_text(self.release_reason, "release_reason"))
        object.__setattr__(self, "causal_event_id", optional_text(self.causal_event_id, "causal_event_id"))
        object.__setattr__(self, "recorded_at", utc_time(self.recorded_at, "recorded_at"))
        if self.schema_version != SUPPORTED_WORK_CLAIM_SCHEMA_VERSION:
            raise WorkClaimVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")


@dataclass(frozen=True)
class WorkClaimEvaluationResult:
    outcome: WorkClaimEvaluationOutcome
    event: WorkClaimEvent
    lineage_version: int
