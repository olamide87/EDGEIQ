from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class SelectionOutcome(str, Enum):
    CANDIDATE_FOUND = "CandidateFound"
    NO_ELIGIBLE_WORKERS = "NoEligibleWorkers"
    POLICY_FILTERED = "PolicyFiltered"
    EVIDENCE_UNAVAILABLE = "EvidenceUnavailable"
    INDETERMINATE = "Indeterminate"


class SelectionError(RuntimeError):
    code = "SelectionInternalFailure"


class SelectionRequestInvalid(SelectionError):
    code = "SelectionRequestInvalid"


class SelectionArtifactVersionUnsupported(SelectionError):
    code = "SelectionArtifactVersionUnsupported"


class SelectionIdempotencyConflict(SelectionError):
    code = "SelectionIdempotencyConflict"


class SelectionVersionConflict(SelectionError):
    code = "SelectionVersionConflict"


class SelectionReplayFailed(SelectionError):
    code = "SelectionReplayFailed"


class SelectionReplayDiverged(SelectionReplayFailed):
    code = "SelectionReplayDiverged"


def canonical_uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise SelectionRequestInvalid(f"Invalid UUID: {value!r}") from exc
    if value != canonical:
        raise SelectionRequestInvalid("UUIDs must use canonical lowercase hyphenated form.")
    return canonical


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise SelectionRequestInvalid("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def immutable_mapping(values: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted((values or {}).items())))


@dataclass(frozen=True)
class WorkerReadinessEvidence:
    worker_id: str
    reference: str
    canonical_hash: str
    organization_id: str
    workload_context_id: str
    evaluated_at: datetime
    expires_at: datetime
    ready: bool
    capabilities: tuple[str, ...] = ()
    hard_policy_pass: bool | None = True
    evidence_consistent: bool = True
    scores: Mapping[str, str] = field(default_factory=immutable_mapping)
    evidence_references: tuple[str, ...] = ()
    schema_version: str = "worker-readiness.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_id", canonical_uuid(self.worker_id))
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        object.__setattr__(self, "expires_at", as_utc(self.expires_at))
        object.__setattr__(self, "capabilities", tuple(sorted(self.capabilities)))
        object.__setattr__(
            self, "evidence_references", tuple(sorted(self.evidence_references))
        )
        object.__setattr__(self, "scores", immutable_mapping(self.scores))


@dataclass(frozen=True)
class WorkerSelectionRequest:
    organization_id: str
    workload_context_id: str
    execution_plan_reference: str
    workload_requirements_reference: str
    policy_constraints_reference: str
    required_capabilities: tuple[str, ...]
    readiness: tuple[WorkerReadinessEvidence, ...]
    evaluation_boundary: datetime
    history_boundary: str
    preference_evidence_references: tuple[str, ...] = ()
    scoring_policy_version: str = "worker-selection.scoring.v1"
    evaluator_version: str = "worker-selection.evaluator.v1"
    schema_version: str = "worker-selection.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_boundary", as_utc(self.evaluation_boundary))
        object.__setattr__(
            self, "required_capabilities", tuple(sorted(self.required_capabilities))
        )
        object.__setattr__(
            self,
            "readiness",
            tuple(sorted(self.readiness, key=lambda item: item.worker_id)),
        )
        object.__setattr__(
            self,
            "preference_evidence_references",
            tuple(sorted(self.preference_evidence_references)),
        )


@dataclass(frozen=True)
class ScoreComponent:
    component_code: str
    raw_value: str | None
    normalized_value: str
    weight: int
    weighted_score: str
    reason_code: str
    evidence_references: tuple[str, ...]


@dataclass(frozen=True)
class WorkerSelectionCandidate:
    worker_id: str
    readiness_reference: str
    score: str
    rank: int
    score_components: tuple[ScoreComponent, ...]
    explanation: str
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    readiness_evaluated_at: datetime
    canonical_hash: str
    evaluation_timestamp: datetime


@dataclass(frozen=True)
class WorkerSelectionExclusion:
    worker_id: str
    readiness_reference: str
    reason_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    canonical_hash: str


@dataclass(frozen=True)
class ReplayMetadata:
    history_boundary: str
    input_artifact_hashes: tuple[str, ...]
    scoring_policy_hash: str
    evaluator_version: str
    canonical_configuration_hash: str
    candidate_ordering_rule_version: str
    serialization_version: str
    replay_input_hash: str
    replay_output_hash: str


@dataclass(frozen=True)
class WorkerSelection:
    selection_id: str
    organization_id: str
    workload_context_id: str
    version: int
    outcome: SelectionOutcome
    candidates: tuple[WorkerSelectionCandidate, ...]
    excluded_workers: tuple[WorkerSelectionExclusion, ...]
    input_evidence_references: tuple[str, ...]
    scoring_policy_version: str
    evaluator_version: str
    schema_version: str
    replay_metadata: ReplayMetadata
    canonical_hash: str
    evaluated_at: datetime
    recorded_at: datetime | None = None
