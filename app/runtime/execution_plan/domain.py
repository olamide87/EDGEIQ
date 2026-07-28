import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SUPPORTED_PLAN_SCHEMA_VERSION = "execution-plan.v1"
SUPPORTED_PLANNING_RULE_VERSION = "execution-plan.rule.v1"
SUPPORTED_PLANNER_VERSION = "execution-plan.planner.v1"


class ExecutionPlanError(RuntimeError):
    code = "ExecutionPlanInternalFailure"


class ExecutionPlanInvalid(ExecutionPlanError):
    code = "ExecutionPlanInvalid"


class ExecutionPlanRequestInvalid(ExecutionPlanInvalid):
    code = "ExecutionPlanRequestInvalid"


class ExecutionPlanRequestDigestInvalid(ExecutionPlanRequestInvalid):
    code = "ExecutionPlanRequestDigestInvalid"


class ExecutionPlanSchemaVersionUnsupported(ExecutionPlanInvalid):
    code = "ExecutionPlanSchemaVersionUnsupported"


class ExecutionPlanRuleVersionUnsupported(ExecutionPlanInvalid):
    code = "ExecutionPlanRuleVersionUnsupported"


class ExecutionPlanDigestMismatch(ExecutionPlanInvalid):
    code = "ExecutionPlanDigestMismatch"


class ExecutionPlanIdentityMismatch(ExecutionPlanInvalid):
    code = "ExecutionPlanIdentityMismatch"


class ExecutionPlanPolicyConfigurationMismatch(ExecutionPlanInvalid):
    code = "ExecutionPlanPolicyConfigurationMismatch"


class ExecutionPlanOrganizationMismatch(ExecutionPlanInvalid):
    code = "ExecutionPlanOrganizationMismatch"


class ExecutionPlanIdempotencyConflict(ExecutionPlanError):
    code = "ExecutionPlanIdempotencyConflict"


class ExecutionPlanVersionConflict(ExecutionPlanError):
    code = "ExecutionPlanVersionConflict"


class ExecutionPlanNotFound(ExecutionPlanError):
    code = "ExecutionPlanNotFound"


class ExecutionPlanReconstructionFailed(ExecutionPlanError):
    code = "ExecutionPlanReconstructionFailed"


class ExecutionPlanReplayDiverged(ExecutionPlanReconstructionFailed):
    code = "ExecutionPlanReplayDiverged"


class ExecutionPlanPersistenceFailure(ExecutionPlanError):
    code = "ExecutionPlanPersistenceFailure"


class PlanDerivationOutcome(str, Enum):
    CREATED = "Created"
    EXISTING_EQUIVALENT = "ExistingEquivalent"


def _immutable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ExecutionPlanInvalid("Canonical map keys must be strings.")
        normalized_items = [
            (unicodedata.normalize("NFC", key), _immutable_value(item))
            for key, item in value.items()
        ]
        if len({key for key, _ in normalized_items}) != len(normalized_items):
            raise ExecutionPlanInvalid(
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
    raise ExecutionPlanInvalid(
        f"Unsupported canonical value: {type(value).__name__}."
    )


def immutable_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    if values is not None and not isinstance(values, Mapping):
        raise ExecutionPlanInvalid("Canonical mapping values must be objects.")
    frozen = _immutable_value(values or {})
    if not isinstance(frozen, Mapping):
        raise ExecutionPlanInvalid("Canonical mapping values must be objects.")
    return frozen


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionPlanInvalid(f"{field_name} is required.")
    return unicodedata.normalize("NFC", value)


def _sha256_hex(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ExecutionPlanInvalid(
            f"{field_name} must be lowercase SHA-256 hex."
        )
    return value


def _unique_sorted(
    values: tuple[str, ...], field_name: str
) -> tuple[str, ...]:
    try:
        normalized = tuple(
            sorted(_required_text(value, field_name) for value in values)
        )
    except TypeError as exc:
        raise ExecutionPlanInvalid(
            f"{field_name} must be an iterable of canonical strings."
        ) from exc
    if len(normalized) != len(set(normalized)):
        raise ExecutionPlanInvalid(f"{field_name} must not contain duplicates.")
    return normalized


@dataclass(frozen=True)
class PlanStep:
    sequence: int
    step_id: str
    operation: str
    inputs: Mapping[str, Any] = field(default_factory=immutable_mapping)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ExecutionPlanInvalid(
                "Plan step sequence must be a non-negative integer."
            )
        object.__setattr__(
            self, "step_id", _required_text(self.step_id, "step_id")
        )
        object.__setattr__(
            self, "operation", _required_text(self.operation, "operation")
        )
        object.__setattr__(self, "inputs", immutable_mapping(self.inputs))


@dataclass(frozen=True, order=True)
class PlanDependency:
    predecessor_step_id: str
    successor_step_id: str

    def __post_init__(self) -> None:
        predecessor = _required_text(
            self.predecessor_step_id, "predecessor_step_id"
        )
        successor = _required_text(
            self.successor_step_id, "successor_step_id"
        )
        if predecessor == successor:
            raise ExecutionPlanInvalid(
                "A plan step cannot depend on itself."
            )
        object.__setattr__(self, "predecessor_step_id", predecessor)
        object.__setattr__(self, "successor_step_id", successor)


@dataclass(frozen=True)
class PlanReconstructionMetadata:
    history_boundary: str
    planner_version: str = SUPPORTED_PLANNER_VERSION
    serialization_version: str = "canonical-json.v1"
    input_artifact_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history_boundary",
            _required_text(self.history_boundary, "history_boundary"),
        )
        if self.planner_version != SUPPORTED_PLANNER_VERSION:
            raise ExecutionPlanSchemaVersionUnsupported(
                f"Unsupported planner version: {self.planner_version}."
            )
        if self.serialization_version != "canonical-json.v1":
            raise ExecutionPlanSchemaVersionUnsupported(
                "Unsupported canonical serialization version."
            )
        try:
            hashes = tuple(
                sorted(
                    _sha256_hex(value, "input_artifact_hash")
                    for value in self.input_artifact_hashes
                )
            )
        except TypeError as exc:
            raise ExecutionPlanInvalid(
                "input_artifact_hashes must be an iterable of digests."
            ) from exc
        if len(hashes) != len(set(hashes)):
            raise ExecutionPlanInvalid(
                "input_artifact_hashes must not contain duplicates."
            )
        object.__setattr__(self, "input_artifact_hashes", hashes)


@dataclass(frozen=True)
class PlanningPolicy:
    policy_version: str
    required_capabilities: tuple[str, ...] = ()
    resource_requirements: Mapping[str, Any] = field(
        default_factory=immutable_mapping
    )
    plan_constraint_defaults: Mapping[str, Any] = field(
        default_factory=immutable_mapping
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_version",
            _required_text(self.policy_version, "policy_version"),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _unique_sorted(
                self.required_capabilities, "required_capabilities"
            ),
        )
        object.__setattr__(
            self,
            "resource_requirements",
            immutable_mapping(self.resource_requirements),
        )
        object.__setattr__(
            self,
            "plan_constraint_defaults",
            immutable_mapping(self.plan_constraint_defaults),
        )


@dataclass(frozen=True)
class PlanningConfiguration:
    configuration_version: str
    work_step_id: str = "work"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "configuration_version",
            _required_text(
                self.configuration_version, "configuration_version"
            ),
        )
        object.__setattr__(
            self,
            "work_step_id",
            _required_text(self.work_step_id, "work_step_id"),
        )


@dataclass(frozen=True)
class ExecutionPlanningInput:
    organization_id: str
    workload_context_id: str
    request_id: str
    validation_evidence_id: str
    policy: PlanningPolicy
    configuration: PlanningConfiguration
    plan_schema_version: str = SUPPORTED_PLAN_SCHEMA_VERSION
    planning_rule_version: str = SUPPORTED_PLANNING_RULE_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "organization_id",
            "workload_context_id",
            "validation_evidence_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self, "request_id", _sha256_hex(self.request_id, "request_id")
        )
        if not isinstance(self.policy, PlanningPolicy):
            raise ExecutionPlanInvalid("A versioned planning policy is required.")
        if not isinstance(self.configuration, PlanningConfiguration):
            raise ExecutionPlanInvalid(
                "A versioned planning configuration is required."
            )
        if self.plan_schema_version != SUPPORTED_PLAN_SCHEMA_VERSION:
            raise ExecutionPlanSchemaVersionUnsupported(
                f"Unsupported plan schema version: {self.plan_schema_version}."
            )
        if self.planning_rule_version != SUPPORTED_PLANNING_RULE_VERSION:
            raise ExecutionPlanRuleVersionUnsupported(
                "Unsupported planning-rule version: "
                f"{self.planning_rule_version}."
            )


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    plan_schema_version: str
    request_id: str
    request_schema_version: str
    canonical_request_digest: str
    organization_id: str
    workload_context_id: str
    planning_rule_version: str
    planning_configuration_digest: str
    policy_version_or_digest: str
    canonical_input_digest: str
    canonical_plan_digest: str
    structured_planned_work: tuple[PlanStep, ...]
    capability_requirements: tuple[str, ...]
    resource_requirements: Mapping[str, Any]
    declared_dependencies: tuple[PlanDependency, ...]
    normalized_plan_constraints: Mapping[str, Any]
    derivation_evidence: tuple[str, ...]
    reconstruction_metadata: PlanReconstructionMetadata

    def __post_init__(self) -> None:
        for field_name in (
            "plan_id",
            "canonical_request_digest",
            "planning_configuration_digest",
            "canonical_input_digest",
            "canonical_plan_digest",
        ):
            _sha256_hex(getattr(self, field_name), field_name)
        for field_name in (
            "request_id",
            "request_schema_version",
            "organization_id",
            "workload_context_id",
            "policy_version_or_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        _sha256_hex(self.request_id, "request_id")
        if self.plan_schema_version != SUPPORTED_PLAN_SCHEMA_VERSION:
            raise ExecutionPlanSchemaVersionUnsupported(
                f"Unsupported plan schema version: {self.plan_schema_version}."
            )
        if self.planning_rule_version != SUPPORTED_PLANNING_RULE_VERSION:
            raise ExecutionPlanRuleVersionUnsupported(
                "Unsupported planning-rule version: "
                f"{self.planning_rule_version}."
            )
        steps = tuple(self.structured_planned_work)
        if not steps or any(not isinstance(step, PlanStep) for step in steps):
            raise ExecutionPlanInvalid(
                "Structured planned work must contain PlanStep values."
            )
        object.__setattr__(self, "structured_planned_work", steps)
        object.__setattr__(
            self,
            "capability_requirements",
            _unique_sorted(
                self.capability_requirements, "capability_requirements"
            ),
        )
        object.__setattr__(
            self,
            "resource_requirements",
            immutable_mapping(self.resource_requirements),
        )
        if any(
            not isinstance(dependency, PlanDependency)
            for dependency in self.declared_dependencies
        ):
            raise ExecutionPlanInvalid(
                "Declared dependencies must contain PlanDependency values."
            )
        object.__setattr__(
            self,
            "declared_dependencies",
            tuple(sorted(self.declared_dependencies)),
        )
        object.__setattr__(
            self,
            "normalized_plan_constraints",
            immutable_mapping(self.normalized_plan_constraints),
        )
        object.__setattr__(
            self,
            "derivation_evidence",
            _unique_sorted(self.derivation_evidence, "derivation_evidence"),
        )
        if not isinstance(
            self.reconstruction_metadata, PlanReconstructionMetadata
        ):
            raise ExecutionPlanInvalid(
                "Plan reconstruction metadata is required."
            )


@dataclass(frozen=True)
class PlanDerivationResult:
    outcome: PlanDerivationOutcome
    plan: ExecutionPlan
    stream_version: int
