from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Mapping

from app.runtime.worker_selection.domain import (
    ScoreComponent,
    SelectionArtifactVersionUnsupported,
    SelectionRequestInvalid,
)
from app.runtime.worker_selection.serialization import canonical_hash


SCALE = Decimal("0.000001")


@dataclass(frozen=True)
class ComponentDefinition:
    code: str
    weight: int


@dataclass(frozen=True)
class ScoringPolicy:
    version: str
    components: tuple[ComponentDefinition, ...]

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self, namespace="worker-selection-policy")


SCORING_POLICY_V1 = ScoringPolicy(
    version="worker-selection.scoring.v1",
    components=(
        ComponentDefinition("CAPABILITY_FIT", 40),
        ComponentDefinition("ORGANIZATION_POLICY_PREFERENCE", 20),
        ComponentDefinition("LATENCY_OBJECTIVE", 15),
        ComponentDefinition("COST_PREFERENCE", 10),
        ComponentDefinition("AFFINITY_PREFERENCE", 10),
        ComponentDefinition("LOAD_BALANCE", 5),
    ),
)
POLICY_REGISTRY = (SCORING_POLICY_V1,)


def policy_for(version: str) -> ScoringPolicy:
    matches = tuple(policy for policy in POLICY_REGISTRY if policy.version == version)
    if len(matches) != 1:
        raise SelectionArtifactVersionUnsupported(
            f"Unsupported or ambiguous scoring policy: {version}"
        )
    return matches[0]


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise SelectionRequestInvalid("Score evidence must be a decimal string.") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > 1:
        raise SelectionRequestInvalid("Score evidence must be finite and within [0, 1].")
    return parsed.quantize(SCALE, rounding=ROUND_HALF_EVEN)


def score_components(
    scores: Mapping[str, str],
    evidence_references: tuple[str, ...],
    policy: ScoringPolicy,
) -> tuple[ScoreComponent, ...]:
    components: list[ScoreComponent] = []
    for definition in policy.components:
        raw = scores.get(definition.code)
        normalized = Decimal("0.000000") if raw is None else _decimal(raw)
        weighted = (normalized * definition.weight).quantize(
            SCALE, rounding=ROUND_HALF_EVEN
        )
        missing = raw is None
        components.append(
            ScoreComponent(
                component_code=definition.code,
                raw_value=raw,
                normalized_value=format(normalized, ".6f"),
                weight=definition.weight,
                weighted_score=format(weighted, ".6f"),
                reason_code=(
                    f"{definition.code}_EVIDENCE_MISSING"
                    if missing
                    else f"{definition.code}_SCORED"
                ),
                evidence_references=evidence_references if not missing else (),
            )
        )
    return tuple(components)
