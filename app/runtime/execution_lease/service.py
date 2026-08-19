from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Mapping

from app.runtime.execution_lease.domain import (
    ExecutionLeaseDigestMismatch, ExecutionLeaseError, ExecutionLeaseEvaluationResult,
    ExecutionLeaseEvent, ExecutionLeaseIdempotencyConflict, ExecutionLeaseIllegalTransition,
    ExecutionLeaseInvalid, ExecutionLeaseNotFound, ExecutionLeasePersistenceFailure,
    ExecutionLeaseReplayDiverged, ExecutionLeaseReconstructionFailed,
    ExecutionLeaseRequest, ExecutionLeaseVersionConflict, LeaseEvaluationOutcome,
    LeaseEventType, LeaseOperation,
)
from app.runtime.execution_lease.evidence import (
    RetainedAuthorizationEvidence, RetainedRevocationEvidence, ScopedEvidenceSource,
    authorization_source, require_evidence, revocation_source,
)
from app.runtime.execution_lease.policy import RegisteredExecutionLeasePolicy, policy_for
from app.runtime.execution_lease.ports import ExecutionLeaseRecord, LineageKey
from app.runtime.execution_lease.serialization import (
    build_execution_lease_event, canonical_input_content, idempotency_identity,
    lineage_identity, verify_recorded_content,
)

IdempotencyKey = tuple[str, LineageKey, str]


@dataclass(frozen=True)
class LeaseDerivedState:
    lineage_version: int = 0
    generation: int = 0
    current_authority_event: ExecutionLeaseEvent | None = None
    terminal_event: ExecutionLeaseEvent | None = None
    last_event: ExecutionLeaseEvent | None = None


@dataclass(frozen=True)
class _RepositoryState:
    streams: Mapping[LineageKey, tuple[ExecutionLeaseRecord, ...]]
    by_id: Mapping[str, ExecutionLeaseRecord]
    idempotency: Mapping[IdempotencyKey, ExecutionLeaseRecord]
    current: Mapping[LineageKey, ExecutionLeaseEvent]


def _state(streams=None, by_id=None, idempotency=None, current=None) -> _RepositoryState:
    return _RepositoryState(MappingProxyType(dict(streams or {})), MappingProxyType(dict(by_id or {})), MappingProxyType(dict(idempotency or {})), MappingProxyType(dict(current or {})))


class InMemoryExecutionLeaseRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._state = _state()

    def _commit_state(self, state: _RepositoryState) -> None:
        self._state = state

    def idempotent(self, *, organization_id: str, lineage_key: LineageKey, idempotency: str, canonical_input: bytes) -> ExecutionLeaseEvent | None:
        key = (organization_id, lineage_key, idempotency)
        with self._lock:
            prior = self._state.idempotency.get(key)
        if prior is None:
            return None
        if prior.canonical_input_content != canonical_input:
            raise ExecutionLeaseIdempotencyConflict("Execution Lease idempotency identity was reused with different canonical input.")
        return prior.event

    def idempotency_record(self, *, organization_id: str, lineage_key: LineageKey, idempotency: str) -> ExecutionLeaseRecord | None:
        with self._lock:
            return self._state.idempotency.get((organization_id, lineage_key, idempotency))

    def append(self, record: ExecutionLeaseRecord, *, expected_version: int) -> ExecutionLeaseEvent:
        key = record.request.lineage_key
        idempotency_key = (record.request.organization_id, key, record.idempotency_identity)
        with self._lock:
            current_state = self._state
            prior = current_state.idempotency.get(idempotency_key)
            if prior is not None:
                if prior.canonical_input_content != record.canonical_input_content:
                    raise ExecutionLeaseIdempotencyConflict("Execution Lease idempotency identity was reused with different canonical input.")
                return prior.event
            history = current_state.streams.get(key, ())
            if expected_version != len(history) or record.request.expected_lineage_version != expected_version or record.event.lineage_version != expected_version + 1:
                raise ExecutionLeaseVersionConflict(f"Expected Execution Lease lineage version {expected_version}; current version is {len(history)}.")
            if record.event.event_id in current_state.by_id:
                raise ExecutionLeaseIdempotencyConflict("Execution Lease event identity already exists.")
            streams, by_id, idempotency, current = map(dict, (current_state.streams, current_state.by_id, current_state.idempotency, current_state.current))
            streams[key] = (*history, record)
            by_id[record.event.event_id] = record
            idempotency[idempotency_key] = record
            current[key] = record.event
            replacement = _state(streams, by_id, idempotency, current)
            try:
                self._commit_state(replacement)
            except ExecutionLeaseError:
                raise
            except Exception as exc:
                raise ExecutionLeasePersistenceFailure("Execution Lease publication failed.") from exc
            return record.event

    def record(self, event_id: str) -> ExecutionLeaseRecord | None:
        with self._lock:
            return self._state.by_id.get(event_id)

    def history(self, key: LineageKey) -> tuple[ExecutionLeaseRecord, ...]:
        with self._lock:
            return self._state.streams.get(key, ())

    def current(self, key: LineageKey) -> ExecutionLeaseEvent | None:
        with self._lock:
            return self._state.current.get(key)


def _advance_state(state: LeaseDerivedState, event: ExecutionLeaseEvent) -> LeaseDerivedState:
    if event.lineage_version != state.lineage_version + 1:
        raise ExecutionLeaseReconstructionFailed("Execution Lease lineage contains a version gap or duplicate.")
    if event.event_type is LeaseEventType.GRANTED:
        if state.lineage_version != 0 or event.generation != 1 or event.prior_event_id is not None:
            raise ExecutionLeaseReconstructionFailed("Initial grant generation or causality is illegal.")
        return LeaseDerivedState(event.lineage_version, 1, event, None, event)
    current = state.current_authority_event
    if current is None or event.prior_event_id != state.last_event.event_id:
        raise ExecutionLeaseReconstructionFailed("Lifecycle event lacks exact prior-event causality.")
    if state.terminal_event is not None:
        raise ExecutionLeaseReconstructionFailed("A lifecycle event follows terminal revocation or supersession.")
    if event.event_type is LeaseEventType.RENEWED:
        if event.generation != state.generation or event.lease_id != current.lease_id:
            raise ExecutionLeaseReconstructionFailed("Renewal changed lease generation or identity.")
        return LeaseDerivedState(event.lineage_version, state.generation, event, None, event)
    if event.event_type is LeaseEventType.REVOKED:
        if event.generation != state.generation or event.lease_id != current.lease_id:
            raise ExecutionLeaseReconstructionFailed("Revocation changed lease generation or identity.")
        return LeaseDerivedState(event.lineage_version, state.generation, current, event, event)
    if event.event_type is LeaseEventType.SUPERSEDED:
        if event.generation != state.generation + 1 or event.superseded_lease_id != current.lease_id:
            raise ExecutionLeaseReconstructionFailed("Supersession generation or causality is illegal.")
        return LeaseDerivedState(event.lineage_version, event.generation, event, None, event)
    raise ExecutionLeaseReconstructionFailed("Unsupported Execution Lease event type.")


class ExecutionLeaseService:
    def __init__(self, *, authorizations: ScopedEvidenceSource[RetainedAuthorizationEvidence] | None = None, revocations: ScopedEvidenceSource[RetainedRevocationEvidence] | None = None, repository: InMemoryExecutionLeaseRepository | None = None) -> None:
        self.authorizations = authorizations or authorization_source()
        self.revocations = revocations or revocation_source()
        self.repository = repository or InMemoryExecutionLeaseRepository()

    def _resolve(self, request: ExecutionLeaseRequest) -> tuple[RetainedAuthorizationEvidence | None, RetainedRevocationEvidence | None, RegisteredExecutionLeasePolicy]:
        scope = {"organization_id": request.organization_id, "workload_context_id": request.workload_context_id}
        authorization = None
        revocation = None
        if request.authorization_evidence_id is not None:
            authorization = require_evidence(self.authorizations, request.authorization_evidence_id, **scope)
            if authorization.canonical_digest != request.authorization_evidence_digest:
                raise ExecutionLeaseDigestMismatch("Retained Authorization digest does not match the request reference.")
            if not authorization.approved:
                raise ExecutionLeaseInvalid("Execution Lease requires affirmative Authorization Checkpoint evidence.")
            if authorization.plan_id != request.plan_id or authorization.work_item_id != request.work_item_id:
                raise ExecutionLeaseInvalid("Authorization scope does not match the requested work item.")
            if authorization.history_boundary != request.authorization_history_boundary:
                raise ExecutionLeaseInvalid("Authorization history boundary does not match.")
            if not set(request.requested_permissions).issubset(authorization.permission_ceiling):
                raise ExecutionLeaseInvalid("Requested permissions exceed retained Authorization authority.")
            if not (authorization.effective_at <= request.evaluation_at < authorization.expires_at):
                raise ExecutionLeaseInvalid("Authorization evidence is not applicable at the retained evaluation time.")
            if request.effective_at < authorization.effective_at or request.expires_at is None or request.expires_at > authorization.expires_at:
                raise ExecutionLeaseInvalid("Lease time boundaries exceed retained Authorization authority.")
        if request.revocation_evidence_id is not None:
            revocation = require_evidence(self.revocations, request.revocation_evidence_id, **scope)
            if revocation.canonical_digest != request.revocation_evidence_digest:
                raise ExecutionLeaseDigestMismatch("Retained revocation digest does not match the request reference.")
            if (revocation.plan_id, revocation.work_item_id, revocation.permission_family) != (request.plan_id, request.work_item_id, request.permission_family):
                raise ExecutionLeaseInvalid("Revocation evidence scope does not match the lease lineage.")
            if revocation.effective_at != request.effective_at:
                raise ExecutionLeaseInvalid("Revocation semantic boundary does not match retained evidence.")
        return authorization, revocation, policy_for(request.lease_policy_id, request.lease_policy_version, request.lease_policy_digest)

    def _decision(self, request: ExecutionLeaseRequest, state: LeaseDerivedState) -> tuple[LeaseEventType, int, str | None]:
        if state.last_event is not None and request.evaluation_at < state.last_event.reconstruction_metadata.evaluation_at:
            raise ExecutionLeaseIllegalTransition("Semantic evaluation time cannot precede committed lineage evidence.")
        if request.operation is LeaseOperation.GRANT:
            if state.lineage_version != 0:
                raise ExecutionLeaseIllegalTransition("A grant is valid only for an empty lineage; later-generation policy is deferred.")
            return LeaseEventType.GRANTED, 1, None
        if state.current_authority_event is None or state.last_event is None or request.prior_event_id != state.last_event.event_id:
            raise ExecutionLeaseIllegalTransition("Lifecycle operation must reference the exact latest lineage event.")
        if state.terminal_event is not None:
            raise ExecutionLeaseIllegalTransition("Post-revocation or post-supersession generation policy is deferred.")
        if request.operation is LeaseOperation.RENEW:
            if (
                state.current_authority_event.authorization_reference is None
                or request.authorization_evidence_id
                == state.current_authority_event.authorization_reference.artifact_id
            ):
                raise ExecutionLeaseInvalid("Renewal requires fresh Authorization Checkpoint evidence.")
            if not set(request.requested_permissions).issubset(state.current_authority_event.permissions):
                raise ExecutionLeaseInvalid("Renewal cannot broaden prior lease permissions.")
            if request.effective_at < state.current_authority_event.effective_at:
                raise ExecutionLeaseInvalid("Renewal cannot backdate the retained authority boundary.")
            return LeaseEventType.RENEWED, state.generation, None
        if request.operation is LeaseOperation.REVOKE:
            if request.effective_at < state.current_authority_event.effective_at:
                raise ExecutionLeaseInvalid("Revocation cannot precede the retained authority boundary.")
            return LeaseEventType.REVOKED, state.generation, None
        if request.operation is LeaseOperation.SUPERSEDE:
            if (
                state.current_authority_event.authorization_reference is None
                or request.authorization_evidence_id
                == state.current_authority_event.authorization_reference.artifact_id
            ):
                raise ExecutionLeaseInvalid("Supersession requires fresh Authorization Checkpoint evidence.")
            if request.effective_at < state.current_authority_event.effective_at:
                raise ExecutionLeaseInvalid("Supersession cannot precede the retained authority boundary.")
            return LeaseEventType.SUPERSEDED, state.generation + 1, state.current_authority_event.lease_id
        raise ExecutionLeaseIllegalTransition("Unsupported Execution Lease operation.")

    def _replay(self, history: tuple[ExecutionLeaseRecord, ...]) -> tuple[LeaseDerivedState, dict[str, ExecutionLeaseEvent]]:
        state = LeaseDerivedState()
        rebuilt_by_id: dict[str, ExecutionLeaseEvent] = {}
        for record in history:
            if record.request.lineage_key != history[0].request.lineage_key or record.event.lineage_id != lineage_identity(record.request.lineage_key):
                raise ExecutionLeaseReconstructionFailed("Execution Lease history crosses lineage identity.")
            if record.request.expected_lineage_version != state.lineage_version:
                raise ExecutionLeaseReconstructionFailed("Retained request boundary does not match lineage history.")
            verify_recorded_content(record.event, record.canonical_input_content, record.canonical_event_content)
            authorization, revocation, policy = self._resolve(record.request)
            event_type, generation, superseded = self._decision(record.request, state)
            expected_input = canonical_input_content(record.request, authorization, revocation, policy, generation=generation)
            if expected_input != record.canonical_input_content:
                raise ExecutionLeaseDigestMismatch("Authoritative evidence no longer matches retained lease input.")
            rebuilt, rebuilt_input, rebuilt_event = build_execution_lease_event(
                record.request, authorization, revocation, policy, event_type=event_type,
                generation=generation, lineage_version=state.lineage_version + 1,
                idempotency=record.idempotency_identity, superseded_lease_id=superseded,
                recorded_at=record.event.recorded_at,
            )
            if rebuilt_input != record.canonical_input_content or rebuilt_event != record.canonical_event_content or rebuilt != record.event:
                raise ExecutionLeaseReplayDiverged("Authoritative evidence did not reproduce Execution Lease history.")
            state = _advance_state(state, rebuilt)
            rebuilt_by_id[rebuilt.event_id] = rebuilt
        return state, rebuilt_by_id

    def evaluate(self, request: ExecutionLeaseRequest) -> ExecutionLeaseEvaluationResult:
        authorization, revocation, policy = self._resolve(request)
        identity = idempotency_identity(request)
        prior_record = self.repository.idempotency_record(
            organization_id=request.organization_id,
            lineage_key=request.lineage_key,
            idempotency=identity,
        )
        if prior_record is not None:
            retry_input = canonical_input_content(
                request, authorization, revocation, policy,
                generation=prior_record.event.generation,
            )
            if retry_input != prior_record.canonical_input_content:
                raise ExecutionLeaseIdempotencyConflict(
                    "Execution Lease idempotency identity was reused with different canonical input."
                )
            return ExecutionLeaseEvaluationResult(
                LeaseEvaluationOutcome.EXISTING_EQUIVALENT,
                prior_record.event,
                prior_record.event.lineage_version,
            )
        history = self.repository.history(request.lineage_key)
        if request.expected_lineage_version != len(history):
            raise ExecutionLeaseVersionConflict(
                f"Expected Execution Lease lineage version {request.expected_lineage_version}; current version is {len(history)}."
            )
        state, _ = self._replay(history) if history else (LeaseDerivedState(), {})
        event_type, generation, superseded = self._decision(request, state)
        input_content = canonical_input_content(request, authorization, revocation, policy, generation=generation)
        prior = self.repository.idempotent(organization_id=request.organization_id, lineage_key=request.lineage_key, idempotency=identity, canonical_input=input_content)
        if prior is not None:
            return ExecutionLeaseEvaluationResult(LeaseEvaluationOutcome.EXISTING_EQUIVALENT, prior, prior.lineage_version)
        event, input_content, event_content = build_execution_lease_event(
            request, authorization, revocation, policy, event_type=event_type,
            generation=generation, lineage_version=request.expected_lineage_version + 1,
            idempotency=identity, superseded_lease_id=superseded,
        )
        accepted = self.repository.append(ExecutionLeaseRecord(request, event, identity, input_content, event_content), expected_version=request.expected_lineage_version)
        outcome = LeaseEvaluationOutcome.CREATED if accepted is event else LeaseEvaluationOutcome.EXISTING_EQUIVALENT
        return ExecutionLeaseEvaluationResult(outcome, accepted, accepted.lineage_version)

    def get(self, event_id: str, *, organization_id: str, workload_context_id: str) -> ExecutionLeaseEvent:
        record = self.repository.record(event_id)
        if record is None or record.event.organization_id != organization_id or record.event.workload_context_id != workload_context_id:
            raise ExecutionLeaseNotFound("Execution Lease event was not found.")
        return record.event

    def history(self, lineage_key: LineageKey, *, organization_id: str, workload_context_id: str) -> tuple[ExecutionLeaseEvent, ...]:
        if lineage_key[0] != organization_id or lineage_key[1] != workload_context_id:
            raise ExecutionLeaseNotFound("Execution Lease lineage was not found.")
        return tuple(record.event for record in self.repository.history(lineage_key))

    def current(self, lineage_key: LineageKey, *, organization_id: str, workload_context_id: str) -> ExecutionLeaseEvent | None:
        if lineage_key[0] != organization_id or lineage_key[1] != workload_context_id:
            raise ExecutionLeaseNotFound("Execution Lease lineage was not found.")
        return self.repository.current(lineage_key)

    def reconstruct(self, event_id: str, *, organization_id: str, workload_context_id: str) -> ExecutionLeaseEvent:
        record = self.repository.record(event_id)
        if record is None or record.event.organization_id != organization_id or record.event.workload_context_id != workload_context_id:
            raise ExecutionLeaseNotFound("Execution Lease event was not found.")
        history = self.repository.history(record.request.lineage_key)
        _, rebuilt = self._replay(history)
        try:
            return rebuilt[event_id]
        except KeyError as exc:
            raise ExecutionLeaseReconstructionFailed("Execution Lease event is absent from authoritative history.") from exc

    def applicable(self, lineage_key: LineageKey, *, organization_id: str, workload_context_id: str, evaluation_at, through_version: int | None = None) -> bool:
        if lineage_key[0] != organization_id or lineage_key[1] != workload_context_id:
            raise ExecutionLeaseNotFound("Execution Lease lineage was not found.")
        history = self.repository.history(lineage_key)
        if through_version is not None:
            if through_version < 1 or through_version > len(history):
                raise ExecutionLeaseReconstructionFailed("Requested lineage boundary is unavailable.")
            history = history[:through_version]
        state, _ = self._replay(history) if history else (LeaseDerivedState(), {})
        return state.terminal_event is None and state.current_authority_event is not None and state.current_authority_event.applicable_at(evaluation_at)
