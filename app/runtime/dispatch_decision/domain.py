import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

SUPPORTED_DISPATCH_SCHEMA_VERSION = "dispatch-decision.v1"
SUPPORTED_DISPATCH_COMPONENT_VERSION = "dispatch-decision.evaluator.v1"
SUPPORTED_SERIALIZATION_VERSION = "canonical-json.v1"


class DispatchDecisionError(RuntimeError):
    code = "DispatchDecisionInternalFailure"


class DispatchDecisionInvalid(DispatchDecisionError):
    code = "DispatchDecisionInvalid"


class DispatchEvidenceMissing(DispatchDecisionInvalid):
    code = "DispatchEvidenceMissing"


class DispatchDecisionDigestMismatch(DispatchDecisionInvalid):
    code = "DispatchDecisionDigestMismatch"


class DispatchDecisionOrganizationMismatch(DispatchDecisionInvalid):
    code = "DispatchDecisionOrganizationMismatch"


class DispatchDecisionVersionUnsupported(DispatchDecisionInvalid):
    code = "DispatchDecisionVersionUnsupported"


class DispatchDecisionIdempotencyConflict(DispatchDecisionError):
    code = "DispatchDecisionIdempotencyConflict"


class DispatchDecisionVersionConflict(DispatchDecisionError):
    code = "DispatchDecisionVersionConflict"


class DispatchDecisionNotFound(DispatchDecisionError):
    code = "DispatchDecisionNotFound"


class DispatchDecisionPersistenceFailure(DispatchDecisionError):
    code = "DispatchDecisionPersistenceFailure"


class DispatchDecisionReconstructionFailed(DispatchDecisionError):
    code = "DispatchDecisionReconstructionFailed"


class DispatchDecisionReplayDiverged(DispatchDecisionReconstructionFailed):
    code = "DispatchDecisionReplayDiverged"


class DispatchDecisionOutcome(str, Enum):
    APPROVED = "Approved"
    DENIED = "Denied"


class DispatchEvaluationOutcome(str, Enum):
    CREATED = "Created"
    EXISTING_EQUIVALENT = "ExistingEquivalent"


def required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DispatchDecisionInvalid(f"{field_name} is required.")
    return unicodedata.normalize("NFC", value)


def sha256_hex(value: str, field_name: str) -> str:
    value = required_text(value, field_name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DispatchDecisionInvalid(f"{field_name} must be lowercase SHA-256 hex.")
    return value


def utc_time(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DispatchDecisionInvalid(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DispatchRequest:
    organization_id: str
    workload_context_id: str
    plan_id: str
    plan_digest: str
    work_item_id: str
    selection_id: str
    selection_digest: str
    selected_candidate_id: str
    lease_id: str
    lease_digest: str
    dispatch_policy_id: str
    dispatch_policy_version: str
    dispatch_policy_digest: str
    evaluation_boundary: str
    effective_at: datetime
    clock_source_id: str
    clock_source_version: str
    configuration_version: str
    schema_version: str = SUPPORTED_DISPATCH_SCHEMA_VERSION
    component_version: str = SUPPORTED_DISPATCH_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION

    def __post_init__(self) -> None:
        for name in (
            "organization_id", "workload_context_id", "plan_id", "work_item_id",
            "selection_id", "selected_candidate_id", "lease_id", "dispatch_policy_id",
            "dispatch_policy_version", "evaluation_boundary", "clock_source_id",
            "clock_source_version", "configuration_version",
        ):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        for name in ("plan_digest", "selection_digest", "lease_digest", "dispatch_policy_digest"):
            object.__setattr__(self, name, sha256_hex(getattr(self, name), name))
        object.__setattr__(self, "effective_at", utc_time(self.effective_at, "effective_at"))
        if self.schema_version != SUPPORTED_DISPATCH_SCHEMA_VERSION:
            raise DispatchDecisionVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")
        if self.component_version != SUPPORTED_DISPATCH_COMPONENT_VERSION:
            raise DispatchDecisionVersionUnsupported(f"Unsupported component version: {self.component_version}.")
        if self.serialization_version != SUPPORTED_SERIALIZATION_VERSION:
            raise DispatchDecisionVersionUnsupported("Unsupported serialization version.")

    @property
    def stream_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.organization_id,
            self.workload_context_id,
            self.plan_id,
            self.work_item_id,
            self.selected_candidate_id,
        )


@dataclass(frozen=True, order=True)
class EvidenceReference:
    artifact_id: str
    canonical_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", required_text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "canonical_digest", sha256_hex(self.canonical_digest, "canonical_digest"))


@dataclass(frozen=True)
class DispatchReconstructionMetadata:
    history_boundary: str
    effective_at: datetime
    clock_source_id: str
    clock_source_version: str
    configuration_version: str
    component_version: str = SUPPORTED_DISPATCH_COMPONENT_VERSION
    serialization_version: str = SUPPORTED_SERIALIZATION_VERSION


@dataclass(frozen=True)
class DispatchDecision:
    dispatch_decision_id: str
    organization_id: str
    workload_context_id: str
    plan_reference: EvidenceReference
    work_item_id: str
    selection_reference: EvidenceReference
    selected_candidate_id: str
    readiness_references: tuple[EvidenceReference, ...]
    lease_reference: EvidenceReference
    causal_authorization_reference: EvidenceReference
    dispatch_policy_reference: EvidenceReference
    dispatch_policy_version: str
    outcome: DispatchDecisionOutcome
    reason_codes: tuple[str, ...]
    canonical_input_digest: str
    canonical_decision_digest: str
    stream_version: int
    idempotency_identity: str
    reconstruction_metadata: DispatchReconstructionMetadata
    recorded_at: datetime
    schema_version: str = SUPPORTED_DISPATCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("dispatch_decision_id", "canonical_input_digest", "canonical_decision_digest", "idempotency_identity"):
            object.__setattr__(self, name, sha256_hex(getattr(self, name), name))
        if not isinstance(self.outcome, DispatchDecisionOutcome):
            raise DispatchDecisionInvalid("A valid dispatch outcome is required.")
        if not isinstance(self.stream_version, int) or isinstance(self.stream_version, bool) or self.stream_version < 1:
            raise DispatchDecisionInvalid("stream_version must be a positive integer.")
        reasons = tuple(sorted(required_text(value, "reason_code") for value in self.reason_codes))
        if not reasons or len(reasons) != len(set(reasons)):
            raise DispatchDecisionInvalid("Reason codes must be non-empty and unique.")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "readiness_references", tuple(sorted(self.readiness_references)))
        object.__setattr__(self, "recorded_at", utc_time(self.recorded_at, "recorded_at"))
        if self.schema_version != SUPPORTED_DISPATCH_SCHEMA_VERSION:
            raise DispatchDecisionVersionUnsupported(f"Unsupported schema version: {self.schema_version}.")


@dataclass(frozen=True)
class DispatchEvaluationResult:
    outcome: DispatchEvaluationOutcome
    decision: DispatchDecision
    stream_version: int
