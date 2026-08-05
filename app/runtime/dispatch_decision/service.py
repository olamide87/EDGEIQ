from dataclasses import dataclass, replace
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.runtime.dispatch_decision.domain import (
    DispatchDecision,
    DispatchDecisionDigestMismatch,
    DispatchDecisionIdempotencyConflict,
    DispatchDecisionInvalid,
    DispatchDecisionNotFound,
    DispatchDecisionReplayDiverged,
    DispatchDecisionReconstructionFailed,
    DispatchDecisionVersionConflict,
    DispatchEvaluationOutcome,
    DispatchEvaluationResult,
    DispatchRequest,
)
from app.runtime.dispatch_decision.evidence import (
    EvidenceSource,
    InMemoryEvidenceSource,
    RetainedLeaseEvidence,
    RetainedPlanEvidence,
    RetainedReadinessEvidence,
    RetainedSelectionCandidate,
    RetainedSelectionEvidence,
    require_evidence,
    validate_lease,
    validate_plan,
    validate_readiness,
    validate_selection,
)
from app.runtime.dispatch_decision.policy import (
    RegisteredDispatchPolicy,
    VerifiedDispatchEvidence,
    policy_for,
)
from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.dispatch_decision.serialization import (
    build_dispatch_decision,
    canonical_input_content,
    dispatch_idempotency_identity,
    verify_recorded_content,
)

StreamKey = tuple[str, str, str, str, str]
IdempotencyKey = tuple[StreamKey, str]


@dataclass(frozen=True)
class _RepositoryState:
    streams: Mapping[StreamKey, tuple[DispatchDecisionRecord, ...]]
    by_id: Mapping[str, DispatchDecisionRecord]
    idempotency: Mapping[IdempotencyKey, DispatchDecisionRecord]


def _state(
    streams: Mapping[StreamKey, tuple[DispatchDecisionRecord, ...]] | None = None,
    by_id: Mapping[str, DispatchDecisionRecord] | None = None,
    idempotency: Mapping[IdempotencyKey, DispatchDecisionRecord] | None = None,
) -> _RepositoryState:
    return _RepositoryState(
        MappingProxyType(dict(streams or {})),
        MappingProxyType(dict(by_id or {})),
        MappingProxyType(dict(idempotency or {})),
    )


class InMemoryDispatchDecisionRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._state = _state()

    def _commit_state(self, state: _RepositoryState) -> None:
        self._state = state

    def append(self, record: DispatchDecisionRecord, *, expected_version: int) -> DispatchDecision:
        stream_key = record.request.stream_key
        idempotency_key = (stream_key, record.idempotency_identity)
        with self._lock:
            current = self._state
            prior = current.idempotency.get(idempotency_key)
            if prior is not None:
                if prior.canonical_input_content != record.canonical_input_content:
                    raise DispatchDecisionIdempotencyConflict(
                        "Dispatch idempotency identity was reused with different canonical input."
                    )
                return prior.decision
            history = current.streams.get(stream_key, ())
            if expected_version != len(history):
                raise DispatchDecisionVersionConflict(
                    f"Expected dispatch stream version {expected_version}; current version is {len(history)}."
                )
            if record.decision.stream_version != expected_version + 1:
                raise DispatchDecisionVersionConflict("Decision stream version does not follow expected version.")
            if record.decision.dispatch_decision_id in current.by_id:
                raise DispatchDecisionIdempotencyConflict("Dispatch decision identity already exists.")
            streams = dict(current.streams)
            by_id = dict(current.by_id)
            idempotency = dict(current.idempotency)
            streams[stream_key] = (*history, record)
            by_id[record.decision.dispatch_decision_id] = record
            idempotency[idempotency_key] = record
            self._commit_state(_state(streams, by_id, idempotency))
            return record.decision

    def record(self, decision_id: str) -> DispatchDecisionRecord | None:
        with self._lock:
            return self._state.by_id.get(decision_id)

    def history(self, stream_key: StreamKey) -> tuple[DispatchDecisionRecord, ...]:
        with self._lock:
            return self._state.streams.get(stream_key, ())

    def current(self, stream_key: StreamKey) -> DispatchDecision | None:
        with self._lock:
            history = self._state.streams.get(stream_key, ())
            return history[-1].decision if history else None


class DispatchDecisionService:
    def __init__(
        self,
        *,
        plans: EvidenceSource[RetainedPlanEvidence] | None = None,
        selections: EvidenceSource[RetainedSelectionEvidence] | None = None,
        readiness: EvidenceSource[RetainedReadinessEvidence] | None = None,
        leases: EvidenceSource[RetainedLeaseEvidence] | None = None,
        repository: InMemoryDispatchDecisionRepository | None = None,
    ) -> None:
        self.plans = plans or InMemoryEvidenceSource(lambda value: value.plan_id, validate_plan)
        self.selections = selections or InMemoryEvidenceSource(lambda value: value.selection_id, validate_selection)
        self.readiness = readiness or InMemoryEvidenceSource(lambda value: value.readiness_id, validate_readiness)
        self.leases = leases or InMemoryEvidenceSource(lambda value: value.lease_id, validate_lease)
        self.repository = repository or InMemoryDispatchDecisionRepository()

    def _resolve(
        self, request: DispatchRequest
    ) -> tuple[VerifiedDispatchEvidence, RegisteredDispatchPolicy]:
        scope = {
            "organization_id": request.organization_id,
            "workload_context_id": request.workload_context_id,
        }
        plan = require_evidence(self.plans, request.plan_id, **scope)
        selection = require_evidence(self.selections, request.selection_id, **scope)
        lease = require_evidence(self.leases, request.lease_id, **scope)
        for label, retained, expected in (
            ("plan", plan.canonical_digest, request.plan_digest),
            ("selection", selection.canonical_digest, request.selection_digest),
            ("lease", lease.canonical_digest, request.lease_digest),
        ):
            if retained != expected:
                raise DispatchDecisionDigestMismatch(f"Retained {label} digest does not match the request reference.")
        if request.work_item_id not in plan.work_item_ids:
            raise DispatchDecisionInvalid("The work item is not retained by the Execution Plan.")
        if selection.plan_reference.artifact_id != plan.plan_id or selection.plan_reference.canonical_digest != plan.canonical_digest:
            raise DispatchDecisionInvalid("Worker Selection does not reference the retained Execution Plan.")
        candidates = tuple(candidate for candidate in selection.candidates if candidate.candidate_id == request.selected_candidate_id)
        if len(candidates) != 1:
            raise DispatchDecisionInvalid("The selected candidate is absent from the retained Worker Selection Result.")
        candidate: RetainedSelectionCandidate = candidates[0]
        if selection.evaluation_boundary != request.evaluation_boundary:
            raise DispatchDecisionInvalid("Selection and Dispatch evidence boundaries do not match.")
        readiness_values: list[RetainedReadinessEvidence] = []
        for reference in candidate.readiness_references:
            retained = require_evidence(self.readiness, reference.artifact_id, **scope)
            if retained.canonical_digest != reference.canonical_digest:
                raise DispatchDecisionDigestMismatch("Retained readiness digest does not match Selection evidence.")
            readiness_values.append(retained)
        if lease.plan_id != plan.plan_id:
            raise DispatchDecisionInvalid("Execution Lease does not apply to the retained Execution Plan.")
        if request.work_item_id not in lease.work_item_ids:
            raise DispatchDecisionInvalid("Execution Lease does not apply to the retained work item.")
        policy = policy_for(
            request.dispatch_policy_id,
            request.dispatch_policy_version,
            request.dispatch_policy_digest,
        )
        evidence = VerifiedDispatchEvidence(
            request=request,
            plan=plan,
            selection=selection,
            candidate=candidate,
            readiness=tuple(readiness_values),
            lease=lease,
        )
        return evidence, policy

    def evaluate(
        self,
        request: DispatchRequest,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> DispatchEvaluationResult:
        evidence, policy = self._resolve(request)
        identity = dispatch_idempotency_identity(request, idempotency_key)
        decision, input_content, decision_content = build_dispatch_decision(
            evidence,
            policy,
            stream_version=expected_version + 1,
            idempotency_identity=identity,
        )
        accepted = self.repository.append(
            DispatchDecisionRecord(request, decision, identity, input_content, decision_content),
            expected_version=expected_version,
        )
        outcome = DispatchEvaluationOutcome.CREATED if accepted is decision else DispatchEvaluationOutcome.EXISTING_EQUIVALENT
        return DispatchEvaluationResult(outcome, accepted, accepted.stream_version)

    def get(self, decision_id: str, *, organization_id: str) -> DispatchDecision:
        record = self.repository.record(decision_id)
        if record is None or record.decision.organization_id != organization_id:
            raise DispatchDecisionNotFound("Dispatch decision was not found.")
        return record.decision

    def history(self, request: DispatchRequest) -> tuple[DispatchDecision, ...]:
        return tuple(record.decision for record in self.repository.history(request.stream_key))

    def current(self, request: DispatchRequest) -> DispatchDecision | None:
        return self.repository.current(request.stream_key)

    def reconstruct(self, decision_id: str, *, organization_id: str) -> DispatchDecision:
        record = self.repository.record(decision_id)
        if record is None or record.decision.organization_id != organization_id:
            raise DispatchDecisionNotFound("Dispatch decision was not found.")
        history = self.repository.history(record.request.stream_key)
        if not history or tuple(item.decision.stream_version for item in history) != tuple(range(1, len(history) + 1)):
            raise DispatchDecisionReconstructionFailed("Dispatch history contains a version gap.")
        verify_recorded_content(record.decision, record.canonical_input_content, record.canonical_decision_content)
        evidence, policy = self._resolve(record.request)
        expected_input = canonical_input_content(evidence, policy)
        if expected_input != record.canonical_input_content:
            raise DispatchDecisionDigestMismatch("Authoritative evidence no longer matches retained canonical input.")
        rebuilt, rebuilt_input, rebuilt_decision = build_dispatch_decision(
            evidence,
            policy,
            stream_version=record.decision.stream_version,
            idempotency_identity=record.idempotency_identity,
            recorded_at=record.decision.recorded_at,
        )
        if (
            rebuilt_input != record.canonical_input_content
            or rebuilt_decision != record.canonical_decision_content
            or rebuilt != record.decision
        ):
            raise DispatchDecisionReplayDiverged("Authoritative evidence did not reproduce the Dispatch Decision.")
        return replace(rebuilt, recorded_at=record.decision.recorded_at)
