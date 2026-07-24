from dataclasses import replace
from decimal import Decimal

from app.runtime.worker_selection.domain import (
    ReplayMetadata,
    SelectionOutcome,
    SelectionRequestInvalid,
    WorkerReadinessEvidence,
    WorkerSelection,
    WorkerSelectionCandidate,
    WorkerSelectionExclusion,
    WorkerSelectionRequest,
)
from app.runtime.worker_selection.policy import policy_for, score_components
from app.runtime.worker_selection.serialization import (
    SERIALIZATION_VERSION,
    canonical_hash,
)


ORDERING_VERSION = "score-desc-readiness-asc-worker-uuid-asc.v1"
CONFIGURATION_VERSION = "worker-selection.config.v1"


class WorkerSelectionEvaluator:
    def evaluate(
        self, request: WorkerSelectionRequest, *, version: int = 1
    ) -> WorkerSelection:
        self._validate_request(request)
        policy = policy_for(request.scoring_policy_version)
        selection_id = canonical_hash(
            {
                "schemaVersion": request.schema_version,
                "organizationId": request.organization_id,
                "workloadContextId": request.workload_context_id,
                "executionPlanReference": request.execution_plan_reference,
                "readinessReferences": tuple(item.reference for item in request.readiness),
                "preferenceEvidenceReferences": request.preference_evidence_references,
                "policyConstraintsReference": request.policy_constraints_reference,
                "scoringPolicyVersion": request.scoring_policy_version,
                "evaluatorVersion": request.evaluator_version,
                "evaluationBoundary": request.evaluation_boundary,
            },
            namespace="worker-selection-id",
        )
        provisional: list[tuple[WorkerReadinessEvidence, tuple, Decimal]] = []
        exclusions: list[WorkerSelectionExclusion] = []
        exclusion_categories: list[str] = []
        for evidence in request.readiness:
            reasons = self._exclusion_reasons(request, evidence)
            if reasons:
                exclusion_categories.extend(reasons)
                exclusion = WorkerSelectionExclusion(
                    worker_id=evidence.worker_id,
                    readiness_reference=evidence.reference,
                    reason_codes=reasons,
                    evidence_references=evidence.evidence_references,
                    canonical_hash="",
                )
                exclusions.append(
                    replace(
                        exclusion,
                        canonical_hash=canonical_hash(
                            exclusion, namespace="worker-selection-exclusion"
                        ),
                    )
                )
                continue
            components = score_components(
                evidence.scores, evidence.evidence_references, policy
            )
            total = sum(
                (Decimal(component.weighted_score) for component in components),
                Decimal("0"),
            )
            provisional.append((evidence, components, total))

        provisional.sort(key=lambda item: (-item[2], item[0].evaluated_at, item[0].worker_id))
        candidates: list[WorkerSelectionCandidate] = []
        for rank, (evidence, components, total) in enumerate(provisional, start=1):
            reason_codes = tuple(component.reason_code for component in components)
            candidate = WorkerSelectionCandidate(
                worker_id=evidence.worker_id,
                readiness_reference=evidence.reference,
                score=format(total, ".6f"),
                rank=rank,
                score_components=components,
                explanation=self._explanation(total, components),
                reason_codes=reason_codes,
                evidence_references=evidence.evidence_references,
                readiness_evaluated_at=evidence.evaluated_at,
                canonical_hash="",
                evaluation_timestamp=request.evaluation_boundary,
            )
            candidates.append(
                replace(
                    candidate,
                    canonical_hash=canonical_hash(
                        {"selectionId": selection_id, "candidate": candidate},
                        namespace="worker-selection-candidate",
                    ),
                )
            )

        outcome = self._outcome(candidates, exclusion_categories)
        input_hashes = tuple(item.canonical_hash for item in request.readiness)
        input_hash = canonical_hash(request, namespace="worker-selection-replay-input")
        output_material = {
            "outcome": outcome,
            "candidates": tuple(candidates),
            "excludedWorkers": tuple(exclusions),
        }
        output_hash = canonical_hash(
            output_material, namespace="worker-selection-replay-output"
        )
        metadata = ReplayMetadata(
            history_boundary=request.history_boundary,
            input_artifact_hashes=input_hashes,
            scoring_policy_hash=policy.canonical_hash,
            evaluator_version=request.evaluator_version,
            canonical_configuration_hash=canonical_hash(
                CONFIGURATION_VERSION, namespace="worker-selection-configuration"
            ),
            candidate_ordering_rule_version=ORDERING_VERSION,
            serialization_version=SERIALIZATION_VERSION,
            replay_input_hash=input_hash,
            replay_output_hash=output_hash,
        )
        selection = WorkerSelection(
            selection_id=selection_id,
            organization_id=request.organization_id,
            workload_context_id=request.workload_context_id,
            version=version,
            outcome=outcome,
            candidates=tuple(candidates),
            excluded_workers=tuple(exclusions),
            input_evidence_references=tuple(
                sorted(
                    (
                        request.execution_plan_reference,
                        request.workload_requirements_reference,
                        request.policy_constraints_reference,
                        *(item.reference for item in request.readiness),
                        *request.preference_evidence_references,
                    )
                )
            ),
            scoring_policy_version=request.scoring_policy_version,
            evaluator_version=request.evaluator_version,
            schema_version=request.schema_version,
            replay_metadata=metadata,
            canonical_hash="",
            evaluated_at=request.evaluation_boundary,
        )
        return replace(
            selection,
            canonical_hash=canonical_hash(selection, namespace="worker-selection"),
        )

    @staticmethod
    def _validate_request(request: WorkerSelectionRequest) -> None:
        required = (
            request.organization_id,
            request.workload_context_id,
            request.execution_plan_reference,
            request.workload_requirements_reference,
            request.policy_constraints_reference,
            request.history_boundary,
        )
        if any(not value for value in required):
            raise SelectionRequestInvalid("Required selection context is missing.")
        worker_ids = tuple(item.worker_id for item in request.readiness)
        if len(worker_ids) != len(set(worker_ids)):
            raise SelectionRequestInvalid("Duplicate worker readiness evidence.")

    @staticmethod
    def _exclusion_reasons(
        request: WorkerSelectionRequest, evidence: WorkerReadinessEvidence
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if (
            evidence.organization_id != request.organization_id
            or evidence.workload_context_id != request.workload_context_id
        ):
            reasons.append("ORGANIZATION_OR_WORKLOAD_MISMATCH")
        if not evidence.canonical_hash or not evidence.reference:
            reasons.append("REQUIRED_EVIDENCE_INVALID")
        if evidence.schema_version != "worker-readiness.v1":
            reasons.append("READINESS_VERSION_UNSUPPORTED")
        if evidence.expires_at < request.evaluation_boundary:
            reasons.append("READINESS_EXPIRED")
        if not evidence.ready:
            reasons.append("WORKER_NOT_READY")
        if not set(request.required_capabilities).issubset(evidence.capabilities):
            reasons.append("REQUIRED_CAPABILITY_MISSING")
        if evidence.hard_policy_pass is None:
            reasons.append("HARD_POLICY_EVIDENCE_UNAVAILABLE")
        elif not evidence.hard_policy_pass:
            reasons.append("HARD_POLICY_FILTERED")
        if not evidence.evidence_consistent:
            reasons.append("CONTRADICTORY_EVIDENCE")
        return tuple(sorted(reasons))

    @staticmethod
    def _outcome(
        candidates: list[WorkerSelectionCandidate], reasons: list[str]
    ) -> SelectionOutcome:
        if candidates:
            return SelectionOutcome.CANDIDATE_FOUND
        if any(reason == "CONTRADICTORY_EVIDENCE" for reason in reasons):
            return SelectionOutcome.INDETERMINATE
        if any(reason == "HARD_POLICY_EVIDENCE_UNAVAILABLE" for reason in reasons):
            return SelectionOutcome.EVIDENCE_UNAVAILABLE
        if reasons and all(reason == "HARD_POLICY_FILTERED" for reason in reasons):
            return SelectionOutcome.POLICY_FILTERED
        unavailable = {
            "ORGANIZATION_OR_WORKLOAD_MISMATCH",
            "REQUIRED_EVIDENCE_INVALID",
            "READINESS_VERSION_UNSUPPORTED",
            "READINESS_EXPIRED",
            "REQUIRED_CAPABILITY_MISSING",
        }
        if any(reason in unavailable for reason in reasons):
            return SelectionOutcome.EVIDENCE_UNAVAILABLE
        return SelectionOutcome.NO_ELIGIBLE_WORKERS

    @staticmethod
    def _explanation(total: Decimal, components: tuple) -> str:
        detail = ", ".join(
            f"{component.component_code}={component.weighted_score}"
            for component in components
        )
        return f"Final score {total:.6f}: {detail}."
