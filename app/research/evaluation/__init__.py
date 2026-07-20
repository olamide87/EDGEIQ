"""Reproducible research evaluation and promotion boundaries."""

from app.research.evaluation.governance import (
    GOVERNANCE_V1,
    EvaluationProtocol,
    GovernancePolicy,
    MetricDefinition,
    MetricDirection,
    MetricName,
    MetricRole,
    PromotionCriteria,
    ResearchDecision,
)
from app.research.evaluation.metrics import (
    CalibrationBin,
    MetricSummary,
    calculate_metrics,
    poisson_over_probability,
)
from app.research.evaluation.scorecard import (
    BaselineEvaluationConfig,
    BaselineResult,
    BaselineScorecard,
    EvaluationPeriod,
    FailureReport,
    PromotionRecommendation,
    ReproducibilityMetadata,
    evaluate_wr_baselines,
    write_baseline_scorecard,
)
from app.research.evaluation.statistics import (
    BootstrapComparison,
    paired_mae_bootstrap,
)

__all__ = [
    "BaselineEvaluationConfig",
    "BaselineResult",
    "BaselineScorecard",
    "BootstrapComparison",
    "CalibrationBin",
    "GOVERNANCE_V1",
    "EvaluationProtocol",
    "EvaluationPeriod",
    "FailureReport",
    "GovernancePolicy",
    "MetricSummary",
    "MetricDefinition",
    "MetricDirection",
    "MetricName",
    "MetricRole",
    "PromotionCriteria",
    "PromotionRecommendation",
    "ReproducibilityMetadata",
    "ResearchDecision",
    "calculate_metrics",
    "evaluate_wr_baselines",
    "paired_mae_bootstrap",
    "poisson_over_probability",
    "write_baseline_scorecard",
]
