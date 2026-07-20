"""Typed, versioned research-governance definitions.

This module encodes the immutable v1.0 contract. Metric calculations, baseline
predictions, scorecards, and promotion recommendations live in later layers.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MetricName(StrEnum):
    """Stable machine names for governed research metrics."""

    MAE = "mean_absolute_error"
    CALIBRATION_ERROR = "expected_calibration_error"
    POISSON_DEVIANCE = "mean_poisson_deviance"
    RMSE = "root_mean_squared_error"
    BIAS = "signed_bias"
    COVERAGE = "prediction_coverage"
    PREDICTION_VARIANCE = "prediction_variance"
    SAMPLE_COUNT = "sample_count"


class MetricRole(StrEnum):
    """Whether a metric controls promotion or explains model behavior."""

    PRIMARY = "primary"
    DIAGNOSTIC = "diagnostic"


class MetricDirection(StrEnum):
    """Direction in which a metric improves."""

    LOWER = "lower"
    HIGHER = "higher"
    TARGET_ZERO = "target_zero"
    INFORMATIONAL = "informational"


class ResearchDecision(StrEnum):
    """The only valid terminal decisions for a governed evaluation."""

    PROMOTE = "PROMOTE"
    RESEARCH = "RESEARCH"
    REVISE = "REVISE"
    REJECT = "REJECT"


class MetricDefinition(BaseModel):
    """A versioned metric's role and comparison semantics."""

    model_config = ConfigDict(frozen=True)

    name: MetricName
    role: MetricRole
    direction: MetricDirection
    description: str = Field(min_length=1)


class EvaluationProtocol(BaseModel):
    """Pre-registered statistical protocol for Governance v1.0."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    validation_method: str = "chronological_held_out"
    primary_metric: MetricName = MetricName.MAE
    baseline_selection_metric: MetricName = MetricName.MAE
    baseline_tie_breaker: str = "baseline_name_ascending"
    calibration_metric: MetricName = MetricName.CALIBRATION_ERROR
    calibration_method: str = "fixed_width"
    calibration_bins: int = Field(default=10, ge=2)
    distribution_metric: MetricName = MetricName.POISSON_DEVIANCE
    significance_test: str = "paired_bootstrap"
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    bootstrap_iterations: int = Field(default=10_000, ge=1)
    random_seed: int = 50_000

    @model_validator(mode="after")
    def enforce_v1_contract(self) -> "EvaluationProtocol":
        if self.validation_method != "chronological_held_out":
            raise ValueError("Governance v1.0 requires chronological held-out validation.")
        if self.primary_metric is not MetricName.MAE:
            raise ValueError("Governance v1.0 uses MAE as its primary error metric.")
        if self.baseline_selection_metric is not MetricName.MAE:
            raise ValueError("Governance v1.0 selects the strongest baseline by MAE.")
        if self.baseline_tie_breaker != "baseline_name_ascending":
            raise ValueError("Governance v1.0 requires a stable baseline-name tie breaker.")
        if self.calibration_metric is not MetricName.CALIBRATION_ERROR:
            raise ValueError("Governance v1.0 requires expected calibration error.")
        if self.calibration_method != "fixed_width":
            raise ValueError("Governance v1.0 requires fixed-width calibration bins.")
        if self.calibration_bins != 10:
            raise ValueError("Governance v1.0 freezes calibration at ten bins.")
        if self.distribution_metric is not MetricName.POISSON_DEVIANCE:
            raise ValueError("Governance v1.0 requires mean Poisson deviance.")
        if self.significance_test != "paired_bootstrap":
            raise ValueError("Governance v1.0 requires paired bootstrap comparisons.")
        return self


class PromotionCriteria(BaseModel):
    """Boolean gates that every learned-model promotion must satisfy."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    strongest_eligible_baseline: bool = True
    significant_mae_improvement: bool = True
    equal_or_better_calibration: bool = True
    improved_poisson_deviance: bool = True
    predefined_subgroups_pass: bool = True
    no_unresolved_leakage: bool = True
    no_unresolved_reproducibility_issue: bool = True
    no_unresolved_data_quality_issue: bool = True
    reproducible_artifacts: bool = True
    final_decision: ResearchDecision = ResearchDecision.PROMOTE


class GovernancePolicy(BaseModel):
    """Complete machine-readable research contract."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(pattern=r"^\d+\.\d+$")
    protocol: EvaluationProtocol
    metrics: tuple[MetricDefinition, ...]
    promotion: PromotionCriteria
    allowed_decisions: tuple[ResearchDecision, ...]

    @model_validator(mode="after")
    def validate_contract(self) -> "GovernancePolicy":
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("Governance metric names must be unique.")
        if set(names) != set(MetricName):
            raise ValueError("Governance policy must define every governed metric exactly once.")
        primary = {
            metric.name for metric in self.metrics if metric.role is MetricRole.PRIMARY
        }
        required_primary = {
            MetricName.MAE,
            MetricName.CALIBRATION_ERROR,
            MetricName.POISSON_DEVIANCE,
        }
        if primary != required_primary:
            raise ValueError(
                "Primary metrics must be MAE, calibration error, and Poisson deviance."
            )
        if self.allowed_decisions != tuple(ResearchDecision):
            raise ValueError("Governance policy must expose all research decisions in order.")
        return self

    def metric(self, name: MetricName) -> MetricDefinition:
        """Return one governed metric definition."""

        for metric in self.metrics:
            if metric.name is name:
                return metric
        raise KeyError(name)


GOVERNANCE_V1 = GovernancePolicy(
    version="1.0",
    protocol=EvaluationProtocol(),
    metrics=(
        MetricDefinition(
            name=MetricName.MAE,
            role=MetricRole.PRIMARY,
            direction=MetricDirection.LOWER,
            description="Mean absolute prediction error.",
        ),
        MetricDefinition(
            name=MetricName.CALIBRATION_ERROR,
            role=MetricRole.PRIMARY,
            direction=MetricDirection.LOWER,
            description="Expected calibration error under pre-registered bins.",
        ),
        MetricDefinition(
            name=MetricName.POISSON_DEVIANCE,
            role=MetricRole.PRIMARY,
            direction=MetricDirection.LOWER,
            description="Mean Poisson deviance for non-negative count outcomes.",
        ),
        MetricDefinition(
            name=MetricName.RMSE,
            role=MetricRole.DIAGNOSTIC,
            direction=MetricDirection.LOWER,
            description="Root mean squared prediction error.",
        ),
        MetricDefinition(
            name=MetricName.BIAS,
            role=MetricRole.DIAGNOSTIC,
            direction=MetricDirection.TARGET_ZERO,
            description="Mean signed prediction error.",
        ),
        MetricDefinition(
            name=MetricName.COVERAGE,
            role=MetricRole.DIAGNOSTIC,
            direction=MetricDirection.HIGHER,
            description="Share of eligible rows receiving a prediction.",
        ),
        MetricDefinition(
            name=MetricName.PREDICTION_VARIANCE,
            role=MetricRole.DIAGNOSTIC,
            direction=MetricDirection.INFORMATIONAL,
            description="Population variance of predictions.",
        ),
        MetricDefinition(
            name=MetricName.SAMPLE_COUNT,
            role=MetricRole.DIAGNOSTIC,
            direction=MetricDirection.INFORMATIONAL,
            description="Number of evaluated player-games.",
        ),
    ),
    promotion=PromotionCriteria(),
    allowed_decisions=tuple(ResearchDecision),
)
