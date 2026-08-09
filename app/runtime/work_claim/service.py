from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.runtime.dispatch_decision.domain import DispatchDecisionOutcome
from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.work_claim.domain import (
    WorkClaimDigestMismatch,
    WorkClaimError,
    WorkClaimEvaluationOutcome,
    WorkClaimEvaluationResult,
    WorkClaimEvent,
    WorkClaimEventType,
    WorkClaimIdempotencyConflict,
    WorkClaimIllegalTransition,
    WorkClaimInvalid,
    WorkClaimNotFound,
    WorkClaimPersistenceFailure,
    WorkClaimReplayDiverged,
    WorkClaimReconstructionFailed,
    WorkClaimRequest,
    WorkClaimVersionConflict,
)
from app.runtime.work_claim.evidence import (
    RetainedClaimantEvidence,
    ScopedEvidenceSource,
    claimant_source,
    dispatch_source,
    require_evidence,
)
from app.runtime.work_claim.policy import (
    RegisteredWorkClaimPolicy,
    WorkClaimDerivedState,
    policy_for,
)
from app.runtime.work_claim.ports import LineageKey, WorkClaimRecord
from app.runtime.work_claim.serialization import (
    build_work_claim_event,
    canonical_input_content,
    lineage_identity,
    verify_recorded_content,
    work_claim_idempotency_identity,
)

IdempotencyKey = tuple[str, LineageKey, str]


@dataclass(frozen=True)
class _RepositoryState:
    streams: Mapping[LineageKey, tuple[WorkClaimRecord, ...]]
    by_id: Mapping[str, WorkClaimRecord]
    idempotency: Mapping[IdempotencyKey, WorkClaimRecord]
    current: Mapping[LineageKey, WorkClaimEvent]


def _state(
    streams: Mapping[LineageKey, tuple[WorkClaimRecord, ...]] | None = None,
    by_id: Mapping[str, WorkClaimRecord] | None = None,
    idempotency: Mapping[IdempotencyKey, WorkClaimRecord] | None = None,
    current: Mapping[LineageKey, WorkClaimEvent] | None = None,
) -> _RepositoryState:
    return _RepositoryState(
        MappingProxyType(dict(streams or {})),
        MappingProxyType(dict(by_id or {})),
        MappingProxyType(dict(idempotency or {})),
        MappingProxyType(dict(current or {})),
    )


class InMemoryWorkClaimRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._state = _state()

    def _commit_state(self, state: _RepositoryState) -> None:
        self._state = state

    def idempotent(
        self,
        *,
        organization_id: str,
        lineage_key: LineageKey,
        idempotency_identity: str,
        canonical_input_content: bytes,
    ) -> WorkClaimEvent | None:
        key = (organization_id, lineage_key, idempotency_identity)
        with self._lock:
            prior = self._state.idempotency.get(key)
        if prior is None:
            return None
        if prior.canonical_input_content != canonical_input_content:
            raise WorkClaimIdempotencyConflict(
                "Work Claim idempotency identity was reused with different canonical input."
            )
        return prior.event

    def append(self, record: WorkClaimRecord, *, expected_version: int) -> WorkClaimEvent:
        lineage_key = record.request.lineage_key
        idempotency_key = (
            record.request.organization_id,
            lineage_key,
            record.idempotency_identity,
        )
        with self._lock:
            current_state = self._state
            prior = current_state.idempotency.get(idempotency_key)
            if prior is not None:
                if prior.canonical_input_content != record.canonical_input_content:
                    raise WorkClaimIdempotencyConflict(
                        "Work Claim idempotency identity was reused with different canonical input."
                    )
                return prior.event
            history = current_state.streams.get(lineage_key, ())
            if expected_version != len(history):
                raise WorkClaimVersionConflict(
                    f"Expected Work Claim lineage version {expected_version}; current version is {len(history)}."
                )
            if record.request.expected_lineage_version != expected_version:
                raise WorkClaimVersionConflict("Request and repository expected versions differ.")
            if record.event.lineage_version != expected_version + 1:
                raise WorkClaimVersionConflict("Event lineage version does not follow expected version.")
            if record.event.event_id in current_state.by_id:
                raise WorkClaimIdempotencyConflict("Work Claim event identity already exists.")
            streams = dict(current_state.streams)
            by_id = dict(current_state.by_id)
            idempotency = dict(current_state.idempotency)
            current = dict(current_state.current)
            streams[lineage_key] = (*history, record)
            by_id[record.event.event_id] = record
            idempotency[idempotency_key] = record
            current[lineage_key] = record.event
            replacement = _state(streams, by_id, idempotency, current)
            try:
                self._commit_state(replacement)
            except WorkClaimError:
                raise
            except Exception as exc:
                raise WorkClaimPersistenceFailure("Work Claim publication failed.") from exc
            return record.event

    def record(self, event_id: str) -> WorkClaimRecord | None:
        with self._lock:
            return self._state.by_id.get(event_id)

    def history(self, lineage_key: LineageKey) -> tuple[WorkClaimRecord, ...]:
        with self._lock:
            return self._state.streams.get(lineage_key, ())

    def current(self, lineage_key: LineageKey) -> WorkClaimEvent | None:
        with self._lock:
            return self._state.current.get(lineage_key)


def _advance_state(state: WorkClaimDerivedState, event: WorkClaimEvent) -> WorkClaimDerivedState:
    expected_version = state.lineage_version + 1
    if event.lineage_version != expected_version:
        raise WorkClaimReconstructionFailed("Work Claim lineage contains a version gap or duplicate.")
    if event.event_type is WorkClaimEventType.GENERATION_CREATED:
        expected_generation = 1 if state.current_generation == 0 else state.current_generation + 1
        if event.generation != expected_generation:
            raise WorkClaimReconstructionFailed("Work Claim generation is duplicate, skipped, or non-monotonic.")
        if state.current_generation and state.ended_event is None:
            raise WorkClaimReconstructionFailed("A later generation precedes valid prior termination.")
        return WorkClaimDerivedState(
            lineage_version=event.lineage_version,
            current_generation=event.generation,
            generation_event=event,
            accepted_event=None,
            ended_event=None,
            latest_fence=state.latest_fence,
            last_event=event,
        )
    if state.generation_event is None or event.generation != state.current_generation:
        raise WorkClaimReconstructionFailed("Lifecycle event does not belong to the current generation.")
    if state.ended_event is not None:
        raise WorkClaimReconstructionFailed("Lifecycle event follows a terminal generation event.")
    if event.event_type is WorkClaimEventType.CLAIM_ACCEPTED:
        if state.accepted_event is not None:
            raise WorkClaimReconstructionFailed("A generation contains multiple accepted claims.")
        if event.fence != state.latest_fence + 1:
            raise WorkClaimReconstructionFailed("Acceptance fence is duplicate, reused, or non-monotonic.")
        return WorkClaimDerivedState(
            event.lineage_version,
            state.current_generation,
            state.generation_event,
            event,
            None,
            event.fence,
            event,
        )
    if event.fence is not None:
        raise WorkClaimReconstructionFailed("A non-acceptance event advanced the fence.")
    if event.event_type is WorkClaimEventType.CLAIM_REJECTED:
        return WorkClaimDerivedState(
            event.lineage_version,
            state.current_generation,
            state.generation_event,
            state.accepted_event,
            None,
            state.latest_fence,
            event,
        )
    if event.event_type in (WorkClaimEventType.CLAIM_EXPIRED, WorkClaimEventType.CLAIM_RELEASED):
        if state.accepted_event is None or event.causal_event_id != state.accepted_event.event_id:
            raise WorkClaimReconstructionFailed("Expiry or release lacks exact accepted-claim causation.")
        return WorkClaimDerivedState(
            event.lineage_version,
            state.current_generation,
            state.generation_event,
            state.accepted_event,
            event,
            state.latest_fence,
            event,
        )
    raise WorkClaimReconstructionFailed("Unsupported Work Claim event type in lineage history.")


class WorkClaimService:
    def __init__(
        self,
        *,
        dispatches: ScopedEvidenceSource[DispatchDecisionRecord] | None = None,
        claimants: ScopedEvidenceSource[RetainedClaimantEvidence] | None = None,
        repository: InMemoryWorkClaimRepository | None = None,
    ) -> None:
        self.dispatches = dispatches or dispatch_source()
        self.claimants = claimants or claimant_source()
        self.repository = repository or InMemoryWorkClaimRepository()

    def _resolve(
        self,
        request: WorkClaimRequest,
    ) -> tuple[DispatchDecisionRecord, RetainedClaimantEvidence, RegisteredWorkClaimPolicy]:
        scope = {
            "organization_id": request.organization_id,
            "workload_context_id": request.workload_context_id,
        }
        dispatch = require_evidence(self.dispatches, request.dispatch_decision_id, **scope)
        claimant = require_evidence(self.claimants, request.claimant_evidence_id, **scope)
        decision = dispatch.decision
        if decision.canonical_decision_digest != request.dispatch_decision_digest:
            raise WorkClaimDigestMismatch("Retained Dispatch digest does not match the request reference.")
        if claimant.canonical_digest != request.claimant_evidence_digest:
            raise WorkClaimDigestMismatch("Retained claimant digest does not match the request reference.")
        if decision.outcome is not DispatchDecisionOutcome.APPROVED:
            raise WorkClaimInvalid("Work Claim requires an approved Dispatch Decision.")
        if decision.plan_reference.artifact_id != request.plan_id or decision.work_item_id != request.work_item_id:
            raise WorkClaimInvalid("Dispatch Decision does not identify the requested planned work item.")
        if decision.selected_candidate_id != request.selected_candidate_id:
            raise WorkClaimInvalid("Request selected candidate does not match Dispatch evidence.")
        if decision.reconstruction_metadata.history_boundary != request.evidence_boundary:
            raise WorkClaimInvalid("Dispatch and Work Claim evidence boundaries do not match.")
        if request.semantic_at < claimant.effective_at or request.semantic_at > claimant.expires_at:
            raise WorkClaimInvalid("Claimant evidence is not applicable at the retained semantic time.")
        policy = policy_for(
            request.claim_policy_id,
            request.claim_policy_version,
            request.claim_policy_digest,
        )
        return dispatch, claimant, policy

    def _replay(
        self,
        history: tuple[WorkClaimRecord, ...],
    ) -> tuple[WorkClaimDerivedState, dict[str, WorkClaimEvent]]:
        state = WorkClaimDerivedState()
        rebuilt_by_id: dict[str, WorkClaimEvent] = {}
        for record in history:
            if record.request.lineage_key != history[0].request.lineage_key:
                raise WorkClaimReconstructionFailed("Work Claim history crosses lineage identity.")
            if record.event.lineage_id != lineage_identity(record.request.lineage_key):
                raise WorkClaimReconstructionFailed("Work Claim lineage identity diverged.")
            if record.request.expected_lineage_version != state.lineage_version:
                raise WorkClaimReconstructionFailed("Retained request boundary does not match lineage history.")
            verify_recorded_content(
                record.event,
                record.canonical_input_content,
                record.canonical_event_content,
            )
            dispatch, claimant, policy = self._resolve(record.request)
            expected_input = canonical_input_content(record.request, dispatch, claimant, policy)
            if expected_input != record.canonical_input_content:
                raise WorkClaimDigestMismatch("Authoritative evidence no longer matches retained Work Claim input.")
            decision = policy.decide(record.request, dispatch, claimant, state)
            rebuilt, rebuilt_input, rebuilt_event = build_work_claim_event(
                record.request,
                dispatch,
                claimant,
                policy,
                decision,
                lineage_version=state.lineage_version + 1,
                idempotency_identity=record.idempotency_identity,
                recorded_at=record.event.recorded_at,
            )
            if (
                rebuilt_input != record.canonical_input_content
                or rebuilt_event != record.canonical_event_content
                or rebuilt != record.event
            ):
                raise WorkClaimReplayDiverged("Authoritative evidence did not reproduce Work Claim history.")
            state = _advance_state(state, rebuilt)
            rebuilt_by_id[rebuilt.event_id] = rebuilt
        return state, rebuilt_by_id

    def evaluate(self, request: WorkClaimRequest) -> WorkClaimEvaluationResult:
        dispatch, claimant, policy = self._resolve(request)
        identity = work_claim_idempotency_identity(request)
        input_content = canonical_input_content(request, dispatch, claimant, policy)
        prior = self.repository.idempotent(
            organization_id=request.organization_id,
            lineage_key=request.lineage_key,
            idempotency_identity=identity,
            canonical_input_content=input_content,
        )
        if prior is not None:
            return WorkClaimEvaluationResult(
                WorkClaimEvaluationOutcome.EXISTING_EQUIVALENT,
                prior,
                prior.lineage_version,
            )
        history = self.repository.history(request.lineage_key)
        if request.expected_lineage_version != len(history):
            raise WorkClaimVersionConflict(
                f"Expected Work Claim lineage version {request.expected_lineage_version}; "
                f"current version is {len(history)}."
            )
        state, _ = self._replay(history) if history else (WorkClaimDerivedState(), {})
        decision = policy.decide(request, dispatch, claimant, state)
        event, input_content, event_content = build_work_claim_event(
            request,
            dispatch,
            claimant,
            policy,
            decision,
            lineage_version=request.expected_lineage_version + 1,
            idempotency_identity=identity,
        )
        accepted = self.repository.append(
            WorkClaimRecord(request, event, identity, input_content, event_content),
            expected_version=request.expected_lineage_version,
        )
        outcome = (
            WorkClaimEvaluationOutcome.CREATED
            if accepted is event
            else WorkClaimEvaluationOutcome.EXISTING_EQUIVALENT
        )
        return WorkClaimEvaluationResult(outcome, accepted, accepted.lineage_version)

    def get(
        self,
        event_id: str,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> WorkClaimEvent:
        record = self.repository.record(event_id)
        if (
            record is None
            or record.event.organization_id != organization_id
            or record.event.workload_context_id != workload_context_id
        ):
            raise WorkClaimNotFound("Work Claim event was not found.")
        return record.event

    def history(
        self,
        lineage_key: LineageKey,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> tuple[WorkClaimEvent, ...]:
        if lineage_key[0] != organization_id or lineage_key[1] != workload_context_id:
            raise WorkClaimNotFound("Work Claim lineage was not found.")
        return tuple(record.event for record in self.repository.history(lineage_key))

    def current(
        self,
        lineage_key: LineageKey,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> WorkClaimEvent | None:
        if lineage_key[0] != organization_id or lineage_key[1] != workload_context_id:
            raise WorkClaimNotFound("Work Claim lineage was not found.")
        return self.repository.current(lineage_key)

    def reconstruct(
        self,
        event_id: str,
        *,
        organization_id: str,
        workload_context_id: str,
    ) -> WorkClaimEvent:
        record = self.repository.record(event_id)
        if (
            record is None
            or record.event.organization_id != organization_id
            or record.event.workload_context_id != workload_context_id
        ):
            raise WorkClaimNotFound("Work Claim event was not found.")
        history = self.repository.history(record.request.lineage_key)
        _, rebuilt = self._replay(history)
        try:
            return rebuilt[event_id]
        except KeyError as exc:
            raise WorkClaimReconstructionFailed("Work Claim event is absent from authoritative history.") from exc
