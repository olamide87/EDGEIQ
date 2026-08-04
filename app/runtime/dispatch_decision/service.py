from dataclasses import replace
from threading import RLock

from app.runtime.dispatch_decision.domain import (
    DispatchDecision,
    DispatchDecisionIdempotencyConflict,
    DispatchDecisionNotFound,
    DispatchDecisionOrganizationMismatch,
    DispatchDecisionReplayDiverged,
    DispatchDecisionReconstructionFailed,
    DispatchDecisionVersionConflict,
    DispatchEvaluationInput,
    DispatchEvaluationOutcome,
    DispatchEvaluationResult,
)
from app.runtime.dispatch_decision.ports import DispatchDecisionRecord
from app.runtime.dispatch_decision.serialization import (
    build_dispatch_decision,
    canonical_input_content,
    dispatch_idempotency_identity,
    verify_recorded_content,
)


class InMemoryDispatchDecisionRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._streams: dict[tuple[str, str, str, str, str], tuple[DispatchDecisionRecord, ...]] = {}
        self._by_id: dict[str, DispatchDecisionRecord] = {}
        self._idempotency: dict[tuple[tuple[str, str, str, str, str], str], DispatchDecisionRecord] = {}

    def append(self, record: DispatchDecisionRecord, *, expected_version: int) -> DispatchDecision:
        stream_key = record.evaluation_input.stream_key
        idempotency_key = (stream_key, record.idempotency_identity)
        with self._lock:
            prior = self._idempotency.get(idempotency_key)
            if prior is not None:
                if prior.canonical_input_content != record.canonical_input_content:
                    raise DispatchDecisionIdempotencyConflict(
                        "Dispatch idempotency identity was reused with different canonical input."
                    )
                return prior.decision
            history = self._streams.get(stream_key, ())
            if expected_version != len(history):
                raise DispatchDecisionVersionConflict(
                    f"Expected dispatch stream version {expected_version}; current version is {len(history)}."
                )
            if record.decision.stream_version != expected_version + 1:
                raise DispatchDecisionVersionConflict("Decision stream version does not follow expected version.")
            if record.decision.dispatch_decision_id in self._by_id:
                raise DispatchDecisionIdempotencyConflict("Dispatch decision identity already exists.")
            self._streams[stream_key] = (*history, record)
            self._by_id[record.decision.dispatch_decision_id] = record
            self._idempotency[idempotency_key] = record
            return record.decision

    def record(self, decision_id: str) -> DispatchDecisionRecord | None:
        with self._lock:
            return self._by_id.get(decision_id)

    def history(self, stream_key: tuple[str, str, str, str, str]) -> tuple[DispatchDecisionRecord, ...]:
        with self._lock:
            return self._streams.get(stream_key, ())

    def current(self, stream_key: tuple[str, str, str, str, str]) -> DispatchDecision | None:
        with self._lock:
            history = self._streams.get(stream_key, ())
            return history[-1].decision if history else None


class DispatchDecisionService:
    def __init__(self, repository: InMemoryDispatchDecisionRepository | None = None) -> None:
        self.repository = repository or InMemoryDispatchDecisionRepository()

    def evaluate(
        self,
        evaluation_input: DispatchEvaluationInput,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> DispatchEvaluationResult:
        identity = dispatch_idempotency_identity(evaluation_input, idempotency_key)
        decision, input_content, decision_content = build_dispatch_decision(
            evaluation_input,
            stream_version=expected_version + 1,
            idempotency_identity=identity,
        )
        accepted = self.repository.append(
            DispatchDecisionRecord(
                evaluation_input=evaluation_input,
                decision=decision,
                idempotency_identity=identity,
                canonical_input_content=input_content,
                canonical_decision_content=decision_content,
            ),
            expected_version=expected_version,
        )
        outcome = (
            DispatchEvaluationOutcome.CREATED
            if accepted is decision
            else DispatchEvaluationOutcome.EXISTING_EQUIVALENT
        )
        return DispatchEvaluationResult(outcome=outcome, decision=accepted, stream_version=accepted.stream_version)

    def get(self, decision_id: str, *, organization_id: str) -> DispatchDecision:
        record = self.repository.record(decision_id)
        if record is None or record.decision.organization_id != organization_id:
            raise DispatchDecisionNotFound("Dispatch decision was not found.")
        return record.decision

    def history(self, evaluation_input: DispatchEvaluationInput) -> tuple[DispatchDecision, ...]:
        return tuple(record.decision for record in self.repository.history(evaluation_input.stream_key))

    def current(self, evaluation_input: DispatchEvaluationInput) -> DispatchDecision | None:
        return self.repository.current(evaluation_input.stream_key)

    def reconstruct(self, decision_id: str, *, organization_id: str) -> DispatchDecision:
        record = self.repository.record(decision_id)
        if record is None or record.decision.organization_id != organization_id:
            raise DispatchDecisionNotFound("Dispatch decision was not found.")
        if record.evaluation_input.organization_id != organization_id:
            raise DispatchDecisionOrganizationMismatch("Retained input organization does not match.")
        expected_input = canonical_input_content(record.evaluation_input)
        verify_recorded_content(record.decision, record.canonical_input_content, record.canonical_decision_content)
        if expected_input != record.canonical_input_content:
            from app.runtime.dispatch_decision.domain import DispatchDecisionDigestMismatch

            raise DispatchDecisionDigestMismatch("Retained canonical input content diverged.")
        history = self.repository.history(record.evaluation_input.stream_key)
        if not history or tuple(item.decision.stream_version for item in history) != tuple(range(1, len(history) + 1)):
            raise DispatchDecisionReconstructionFailed("Dispatch history contains a version gap.")
        rebuilt, rebuilt_input, rebuilt_decision = build_dispatch_decision(
            record.evaluation_input,
            stream_version=record.decision.stream_version,
            idempotency_identity=record.idempotency_identity,
            recorded_at=record.decision.recorded_at,
        )
        if (
            rebuilt_input != record.canonical_input_content
            or rebuilt_decision != record.canonical_decision_content
            or rebuilt.dispatch_decision_id != record.decision.dispatch_decision_id
            or rebuilt.canonical_decision_digest != record.decision.canonical_decision_digest
            or rebuilt != record.decision
        ):
            raise DispatchDecisionReplayDiverged("Retained inputs did not reproduce the Dispatch Decision.")
        return replace(rebuilt, recorded_at=record.decision.recorded_at)
