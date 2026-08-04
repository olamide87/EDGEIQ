from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Callable, Generic, Protocol, TypeVar

from app.runtime.dispatch_decision.canonical import canonical_json, namespaced_digest
from app.runtime.dispatch_decision.domain import (
    DispatchDecisionDigestMismatch,
    DispatchDecisionInvalid,
    DispatchDecisionVersionUnsupported,
    DispatchEvidenceMissing,
    EvidenceReference,
    required_text,
    utc_time,
)

PLAN_EVIDENCE_NAMESPACE = "edgeiq.dispatch-plan-evidence.v1"
SELECTION_EVIDENCE_NAMESPACE = "edgeiq.dispatch-selection-evidence.v1"
READINESS_EVIDENCE_NAMESPACE = "edgeiq.dispatch-readiness-evidence.v1"
LEASE_EVIDENCE_NAMESPACE = "edgeiq.dispatch-lease-evidence.v1"

SUPPORTED_PLAN_EVIDENCE_SCHEMA = "execution-plan.v1"
SUPPORTED_PLANNING_RULE = "execution-plan.rule.v1"
SUPPORTED_SELECTION_EVIDENCE_SCHEMA = "worker-selection.v1"
SUPPORTED_SELECTION_POLICY = "worker-selection.scoring.v1"
SUPPORTED_READINESS_EVIDENCE_SCHEMA = "worker-readiness.v1"
SUPPORTED_LEASE_EVIDENCE_SCHEMA = "execution-lease.v1"
SUPPORTED_LEASE_POLICY = "execution-lease.policy.v1"


@dataclass(frozen=True)
class RetainedPlanEvidence:
    plan_id: str
    organization_id: str
    workload_context_id: str
    work_item_ids: tuple[str, ...]
    schema_version: str
    planning_rule_version: str
    canonical_digest: str
    canonical_content: bytes


@dataclass(frozen=True)
class RetainedReadinessEvidence:
    readiness_id: str
    organization_id: str
    workload_context_id: str
    evaluated_at: datetime
    expires_at: datetime
    superseded: bool
    schema_version: str
    canonical_digest: str
    canonical_content: bytes


@dataclass(frozen=True, order=True)
class RetainedSelectionCandidate:
    candidate_id: str
    readiness_references: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", required_text(self.candidate_id, "candidate_id"))
        references = tuple(sorted(self.readiness_references))
        if not references or len(references) != len(set(references)):
            raise DispatchDecisionInvalid("Selection candidate readiness references must be non-empty and unique.")
        object.__setattr__(self, "readiness_references", references)


@dataclass(frozen=True)
class RetainedSelectionEvidence:
    selection_id: str
    organization_id: str
    workload_context_id: str
    plan_reference: EvidenceReference
    candidates: tuple[RetainedSelectionCandidate, ...]
    evaluation_boundary: str
    schema_version: str
    selection_policy_version: str
    canonical_digest: str
    canonical_content: bytes


@dataclass(frozen=True)
class RetainedLeaseEvidence:
    lease_id: str
    organization_id: str
    workload_context_id: str
    plan_id: str
    work_item_ids: tuple[str, ...]
    bounded_permission: bool
    effective_at: datetime
    expires_at: datetime
    revoked: bool
    causal_authorization_reference: EvidenceReference
    schema_version: str
    lease_policy_version: str
    canonical_digest: str
    canonical_content: bytes


def _content(document: dict[str, object]) -> bytes:
    return canonical_json(document).encode("utf-8")


def build_plan_evidence(
    *, plan_id: str, organization_id: str, workload_context_id: str,
    work_item_ids: tuple[str, ...], schema_version: str = SUPPORTED_PLAN_EVIDENCE_SCHEMA,
    planning_rule_version: str = SUPPORTED_PLANNING_RULE,
) -> RetainedPlanEvidence:
    items = tuple(sorted(required_text(item, "work_item_id") for item in work_item_ids))
    if not items or len(items) != len(set(items)):
        raise DispatchDecisionInvalid("Plan work items must be non-empty and unique.")
    document = {
        "organization_id": required_text(organization_id, "organization_id"),
        "plan_id": required_text(plan_id, "plan_id"),
        "planning_rule_version": planning_rule_version,
        "schema_version": schema_version,
        "work_item_ids": items,
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = _content(document)
    return RetainedPlanEvidence(**document, canonical_digest=namespaced_digest(PLAN_EVIDENCE_NAMESPACE, content), canonical_content=content)


def build_readiness_evidence(
    *, readiness_id: str, organization_id: str, workload_context_id: str,
    evaluated_at: datetime, expires_at: datetime, superseded: bool = False,
    schema_version: str = SUPPORTED_READINESS_EVIDENCE_SCHEMA,
) -> RetainedReadinessEvidence:
    evaluated = utc_time(evaluated_at, "evaluated_at")
    expires = utc_time(expires_at, "expires_at")
    if expires < evaluated:
        raise DispatchDecisionInvalid("Readiness expiry cannot precede evaluation.")
    document = {
        "evaluated_at": evaluated,
        "expires_at": expires,
        "organization_id": required_text(organization_id, "organization_id"),
        "readiness_id": required_text(readiness_id, "readiness_id"),
        "schema_version": schema_version,
        "superseded": superseded,
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = _content(document)
    return RetainedReadinessEvidence(**document, canonical_digest=namespaced_digest(READINESS_EVIDENCE_NAMESPACE, content), canonical_content=content)


def build_selection_evidence(
    *, selection_id: str, organization_id: str, workload_context_id: str,
    plan_reference: EvidenceReference, candidates: tuple[RetainedSelectionCandidate, ...],
    evaluation_boundary: str, schema_version: str = SUPPORTED_SELECTION_EVIDENCE_SCHEMA,
    selection_policy_version: str = SUPPORTED_SELECTION_POLICY,
) -> RetainedSelectionEvidence:
    ordered = tuple(sorted(candidates))
    if not ordered or len({candidate.candidate_id for candidate in ordered}) != len(ordered):
        raise DispatchDecisionInvalid("Selection candidates must be non-empty and unique.")
    document = {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "readiness_references": [
                    {"artifact_id": ref.artifact_id, "canonical_digest": ref.canonical_digest}
                    for ref in candidate.readiness_references
                ],
            }
            for candidate in ordered
        ],
        "evaluation_boundary": required_text(evaluation_boundary, "evaluation_boundary"),
        "organization_id": required_text(organization_id, "organization_id"),
        "plan_reference": {"artifact_id": plan_reference.artifact_id, "canonical_digest": plan_reference.canonical_digest},
        "schema_version": schema_version,
        "selection_id": required_text(selection_id, "selection_id"),
        "selection_policy_version": selection_policy_version,
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = _content(document)
    return RetainedSelectionEvidence(
        selection_id=document["selection_id"], organization_id=document["organization_id"],
        workload_context_id=document["workload_context_id"], plan_reference=plan_reference,
        candidates=ordered, evaluation_boundary=document["evaluation_boundary"],
        schema_version=schema_version, selection_policy_version=selection_policy_version,
        canonical_digest=namespaced_digest(SELECTION_EVIDENCE_NAMESPACE, content), canonical_content=content,
    )


def build_lease_evidence(
    *, lease_id: str, organization_id: str, workload_context_id: str, plan_id: str,
    work_item_ids: tuple[str, ...], bounded_permission: bool, effective_at: datetime,
    expires_at: datetime, revoked: bool, causal_authorization_reference: EvidenceReference,
    schema_version: str = SUPPORTED_LEASE_EVIDENCE_SCHEMA,
    lease_policy_version: str = SUPPORTED_LEASE_POLICY,
) -> RetainedLeaseEvidence:
    items = tuple(sorted(required_text(item, "work_item_id") for item in work_item_ids))
    if not items or len(items) != len(set(items)):
        raise DispatchDecisionInvalid("Lease work items must be non-empty and unique.")
    effective = utc_time(effective_at, "lease_effective_at")
    expires = utc_time(expires_at, "lease_expires_at")
    if expires < effective:
        raise DispatchDecisionInvalid("Lease expiry cannot precede effective time.")
    document = {
        "bounded_permission": bounded_permission,
        "causal_authorization_reference": {
            "artifact_id": causal_authorization_reference.artifact_id,
            "canonical_digest": causal_authorization_reference.canonical_digest,
        },
        "effective_at": effective,
        "expires_at": expires,
        "lease_id": required_text(lease_id, "lease_id"),
        "lease_policy_version": lease_policy_version,
        "organization_id": required_text(organization_id, "organization_id"),
        "plan_id": required_text(plan_id, "plan_id"),
        "revoked": revoked,
        "schema_version": schema_version,
        "work_item_ids": items,
        "workload_context_id": required_text(workload_context_id, "workload_context_id"),
    }
    content = _content(document)
    return RetainedLeaseEvidence(
        lease_id=document["lease_id"], organization_id=document["organization_id"],
        workload_context_id=document["workload_context_id"], plan_id=document["plan_id"],
        work_item_ids=items, bounded_permission=bounded_permission, effective_at=effective,
        expires_at=expires, revoked=revoked, causal_authorization_reference=causal_authorization_reference,
        schema_version=schema_version, lease_policy_version=lease_policy_version,
        canonical_digest=namespaced_digest(LEASE_EVIDENCE_NAMESPACE, content), canonical_content=content,
    )


def validate_plan(value: RetainedPlanEvidence) -> None:
    rebuilt = build_plan_evidence(
        plan_id=value.plan_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, work_item_ids=value.work_item_ids,
        schema_version=value.schema_version, planning_rule_version=value.planning_rule_version,
    )
    if value.schema_version != SUPPORTED_PLAN_EVIDENCE_SCHEMA or value.planning_rule_version != SUPPORTED_PLANNING_RULE:
        raise DispatchDecisionVersionUnsupported("Unsupported retained plan evidence version.")
    _match(value, rebuilt, "plan")


def validate_readiness(value: RetainedReadinessEvidence) -> None:
    rebuilt = build_readiness_evidence(
        readiness_id=value.readiness_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, evaluated_at=value.evaluated_at,
        expires_at=value.expires_at, superseded=value.superseded, schema_version=value.schema_version,
    )
    if value.schema_version != SUPPORTED_READINESS_EVIDENCE_SCHEMA:
        raise DispatchDecisionVersionUnsupported("Unsupported retained readiness evidence version.")
    _match(value, rebuilt, "readiness")


def validate_selection(value: RetainedSelectionEvidence) -> None:
    rebuilt = build_selection_evidence(
        selection_id=value.selection_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, plan_reference=value.plan_reference,
        candidates=value.candidates, evaluation_boundary=value.evaluation_boundary,
        schema_version=value.schema_version, selection_policy_version=value.selection_policy_version,
    )
    if value.schema_version != SUPPORTED_SELECTION_EVIDENCE_SCHEMA or value.selection_policy_version != SUPPORTED_SELECTION_POLICY:
        raise DispatchDecisionVersionUnsupported("Unsupported retained selection evidence version.")
    _match(value, rebuilt, "selection")


def validate_lease(value: RetainedLeaseEvidence) -> None:
    rebuilt = build_lease_evidence(
        lease_id=value.lease_id, organization_id=value.organization_id,
        workload_context_id=value.workload_context_id, plan_id=value.plan_id,
        work_item_ids=value.work_item_ids, bounded_permission=value.bounded_permission,
        effective_at=value.effective_at, expires_at=value.expires_at, revoked=value.revoked,
        causal_authorization_reference=value.causal_authorization_reference,
        schema_version=value.schema_version, lease_policy_version=value.lease_policy_version,
    )
    if value.schema_version != SUPPORTED_LEASE_EVIDENCE_SCHEMA or value.lease_policy_version != SUPPORTED_LEASE_POLICY:
        raise DispatchDecisionVersionUnsupported("Unsupported retained lease evidence version.")
    _match(value, rebuilt, "lease")


def _match(value: object, rebuilt: object, label: str) -> None:
    if value != rebuilt:
        raise DispatchDecisionDigestMismatch(f"Retained {label} evidence failed canonical verification.")


T = TypeVar("T")


class EvidenceSource(Protocol, Generic[T]):
    def get(self, artifact_id: str) -> T | None: ...


class InMemoryEvidenceSource(Generic[T]):
    def __init__(self, identity: Callable[[T], str], validator: Callable[[T], None]) -> None:
        self._identity = identity
        self._validator = validator
        self._items: dict[str, T] = {}
        self._lock = RLock()

    def retain(self, value: T) -> None:
        self._validator(value)
        key = self._identity(value)
        with self._lock:
            prior = self._items.get(key)
            if prior is not None and prior != value:
                raise DispatchDecisionInvalid("Immutable retained evidence cannot be replaced.")
            self._items[key] = value

    def get(self, artifact_id: str) -> T | None:
        with self._lock:
            value = self._items.get(artifact_id)
        if value is not None:
            self._validator(value)
        return value


def require_evidence(source: EvidenceSource[T], artifact_id: str, label: str) -> T:
    value = source.get(artifact_id)
    if value is None:
        raise DispatchEvidenceMissing(f"Retained {label} evidence is unavailable.")
    return value
