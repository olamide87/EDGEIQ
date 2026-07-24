from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.runtime.worker_selection.domain import (
    SelectionArtifactVersionUnsupported,
    SelectionError,
    SelectionIdempotencyConflict,
    SelectionRequestInvalid,
    SelectionVersionConflict,
    WorkerReadinessEvidence,
    WorkerSelection,
    WorkerSelectionRequest,
)
from app.runtime.worker_selection.serialization import canonical_value
from app.runtime.worker_selection.service import (
    WorkerSelectionService,
    worker_selection_service,
)


router = APIRouter(prefix="/worker-selection", tags=["worker-selection"])


class ReadinessInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    worker_id: str = Field(alias="workerId")
    reference: str
    canonical_hash: str = Field(alias="canonicalHash")
    organization_id: str = Field(alias="organizationId")
    workload_context_id: str = Field(alias="workloadContextId")
    evaluated_at: datetime = Field(alias="evaluatedAt")
    expires_at: datetime = Field(alias="expiresAt")
    ready: bool
    capabilities: tuple[str, ...] = ()
    hard_policy_pass: bool | None = Field(default=True, alias="hardPolicyPass")
    evidence_consistent: bool = Field(default=True, alias="evidenceConsistent")
    scores: dict[str, str] = Field(default_factory=dict)
    evidence_references: tuple[str, ...] = Field(
        default=(), alias="evidenceReferences"
    )
    schema_version: str = Field(
        default="worker-readiness.v1", alias="schemaVersion"
    )

    def to_domain(self) -> WorkerReadinessEvidence:
        return WorkerReadinessEvidence(**self.model_dump())


class WorkerSelectionEvaluateInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    organization_id: str = Field(alias="organizationId")
    workload_context_id: str = Field(alias="workloadContextId")
    execution_plan_reference: str = Field(alias="executionPlanReference")
    workload_requirements_reference: str = Field(
        alias="workloadRequirementsReference"
    )
    policy_constraints_reference: str = Field(alias="policyConstraintsReference")
    required_capabilities: tuple[str, ...] = Field(alias="requiredCapabilities")
    readiness: tuple[ReadinessInput, ...]
    evaluation_boundary: datetime = Field(alias="evaluationBoundary")
    history_boundary: str = Field(alias="historyBoundary")
    preference_evidence_references: tuple[str, ...] = Field(
        default=(), alias="preferenceEvidenceReferences"
    )
    scoring_policy_version: str = Field(
        default="worker-selection.scoring.v1", alias="scoringPolicyVersion"
    )
    evaluator_version: str = Field(
        default="worker-selection.evaluator.v1", alias="evaluatorVersion"
    )
    schema_version: str = Field(default="worker-selection.v1", alias="schemaVersion")
    expected_version: int = Field(default=0, ge=0, alias="expectedVersion")

    def to_domain(self) -> WorkerSelectionRequest:
        values = self.model_dump(exclude={"readiness", "expected_version"})
        return WorkerSelectionRequest(
            **values,
            readiness=tuple(item.to_domain() for item in self.readiness),
        )


def get_worker_selection_service() -> WorkerSelectionService:
    return worker_selection_service


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _api_value(value: object) -> object:
    canonical = canonical_value(value)
    if isinstance(canonical, dict):
        return {_camel(key): _api_value(item) for key, item in canonical.items()}
    if isinstance(canonical, list):
        return [_api_value(item) for item in canonical]
    return canonical


def _response(selection: WorkerSelection, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=_api_value(selection), status_code=status_code)


def _domain_error(exc: SelectionError) -> HTTPException:
    if isinstance(exc, (SelectionIdempotencyConflict, SelectionVersionConflict)):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, SelectionArtifactVersionUnsupported):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, SelectionRequestInvalid):
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return HTTPException(status_code=code, detail={"code": exc.code})


@router.post("/evaluate", status_code=status.HTTP_201_CREATED)
def evaluate_worker_selection(
    payload: WorkerSelectionEvaluateInput,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: WorkerSelectionService = Depends(get_worker_selection_service),
) -> JSONResponse:
    try:
        selection = service.evaluate(
            payload.to_domain(),
            expected_version=payload.expected_version,
            idempotency_key=idempotency_key,
        )
    except SelectionError as exc:
        raise _domain_error(exc) from exc
    return _response(selection, status.HTTP_201_CREATED)


@router.get("/{selection_id}/history")
def get_worker_selection_history(
    selection_id: str,
    organization_id: Annotated[str, Header(alias="Organization-Id")],
    service: WorkerSelectionService = Depends(get_worker_selection_service),
) -> JSONResponse:
    selection = service.get(selection_id)
    if selection is None or selection.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Worker selection not found.")
    history = service.history(
        selection.organization_id, selection.workload_context_id
    )
    return JSONResponse(content=_api_value(history))


@router.get("/{selection_id}")
def get_worker_selection(
    selection_id: str,
    organization_id: Annotated[str, Header(alias="Organization-Id")],
    service: WorkerSelectionService = Depends(get_worker_selection_service),
) -> JSONResponse:
    selection = service.get(selection_id)
    if selection is None or selection.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Worker selection not found.")
    return _response(selection)


@router.get("")
def get_current_worker_selection(
    organization_id: Annotated[str, Header(alias="Organization-Id")],
    workload_id: str = Query(alias="workloadId"),
    service: WorkerSelectionService = Depends(get_worker_selection_service),
) -> JSONResponse:
    selection = service.current(organization_id, workload_id)
    if selection is None:
        raise HTTPException(status_code=404, detail="Worker selection not found.")
    return _response(selection)
