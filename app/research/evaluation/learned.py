"""Governed evaluation integration for the first learned WR model."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict

from app.research.baselines import BASELINE_SPECS, BaselineName
from app.research.evaluation.governance import ResearchDecision
from app.research.evaluation.metrics import CalibrationBin, MetricSummary, calculate_metrics
from app.research.evaluation.scorecard import (
    BaselineEvaluationConfig,
    EvaluationPeriod,
    GOVERNED_BASELINE_HIERARCHY,
    PromotionRecommendation,
    ReproducibilityMetadata,
    build_governed_baseline_cohort,
    evaluate_wr_baselines,
    select_strongest_baseline,
)
from app.research.evaluation.statistics import BootstrapComparison, paired_mae_bootstrap
from app.research.features import canonical_feature_content_hash, validate_wr_feature_table
from app.research.manifest import canonical_hash
from app.research.models import (
    ModelTrainingContext,
    WRPoissonConfig,
    WRPoissonModel,
    WRPoissonState,
    chronological_model_split,
)


class LearnedMetricGates(BaseModel):
    """Promotion-critical metric evidence, excluding later governance gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lower_mae: bool
    statistically_significant_mae_improvement: bool
    equal_or_better_calibration: bool
    improved_poisson_deviance: bool


class LearnedCandidateResult(BaseModel):
    """Governed result for one learned-model candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_kind: str = "learned_model"
    model_name: str
    model_version: str
    model_fingerprint: str
    model_state: WRPoissonState
    governed_comparison_baseline: BaselineName
    metrics: MetricSummary
    calibration: tuple[CalibrationBin, ...]
    comparison: BootstrapComparison
    metric_gates: LearnedMetricGates


class LearnedEvaluationScorecard(BaseModel):
    """Reproducible learned-model comparison layered on the baseline scorecard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    governance_version: str
    evaluation_protocol_version: str
    evaluated_at: datetime
    baseline_scorecard_hash: str
    baseline_candidates: tuple[str, ...]
    candidate: LearnedCandidateResult
    recommendation: PromotionRecommendation
    reproducibility: ReproducibilityMetadata
    configuration_hash: str
    training_period: EvaluationPeriod
    validation_period: EvaluationPeriod
    random_seed: int
    shared_cohort_size: int
    scorecard_hash: str


def _learned_recommendation(gates: LearnedMetricGates) -> PromotionRecommendation:
    passed = (
        gates.lower_mae
        and gates.statistically_significant_mae_improvement
        and gates.equal_or_better_calibration
        and gates.improved_poisson_deviance
    )
    reasons = [
        "Learned-model metric gates passed; subgroup and remaining promotion gates are not evaluated."
        if passed
        else "One or more learned-model promotion-critical metric gates did not pass.",
        "v0.6A remains research-only and cannot receive PROMOTE from this evaluation.",
    ]
    return PromotionRecommendation(
        decision=ResearchDecision.RESEARCH,
        reasons=tuple(reasons),
    )


def fit_and_evaluate_wr_poisson(
    feature_table: pl.DataFrame,
    *,
    model_config: WRPoissonConfig,
    evaluation_config: BaselineEvaluationConfig,
    reproducibility: ReproducibilityMetadata,
    evaluated_at: datetime | None = None,
) -> tuple[WRPoissonModel, LearnedEvaluationScorecard]:
    """Fit chronologically and compare on the governed baseline shared cohort."""

    validate_wr_feature_table(feature_table)
    if canonical_feature_content_hash(feature_table) != reproducibility.canonical_feature_table_hash:
        raise ValueError("Canonical feature-table hash does not match learned evaluation input.")
    training, evaluation = chronological_model_split(
        feature_table,
        training_period=evaluation_config.training_period,
        evaluation_period=evaluation_config.validation_period,
    )
    context = ModelTrainingContext(
        dataset_manifest_hash=reproducibility.dataset_manifest_hash,
        feature_registry_hash=reproducibility.feature_registry_hash,
        canonical_feature_table_hash=reproducibility.canonical_feature_table_hash,
        git_commit_sha=reproducibility.git_commit_sha,
    )
    eligible_training = training.filter(
        pl.all_horizontal(
            *(pl.col(name).is_not_null() for name in model_config.feature_names)
        )
    )
    if eligible_training.height < model_config.minimum_training_rows:
        raise ValueError(
            "Chronological training cohort does not contain enough rows with all "
            "required pregame model features."
        )
    model = WRPoissonModel(model_config).fit(eligible_training, context=context)
    evaluation_time = evaluated_at or datetime.now(timezone.utc)
    eligible_evaluation = evaluation.filter(
        pl.all_horizontal(
            *(pl.col(name).is_not_null() for name in model_config.feature_names)
        )
    )
    if not eligible_evaluation.height:
        raise ValueError(
            "Chronological evaluation cohort has no rows with all required "
            "pregame model features."
        )
    evaluation_keys = eligible_evaluation.select("source_player_id", "game_id")
    baseline_scorecard = evaluate_wr_baselines(
        feature_table,
        config=evaluation_config,
        reproducibility=reproducibility,
        evaluated_at=evaluation_time,
        evaluation_keys=evaluation_keys,
    )
    shared, _ = build_governed_baseline_cohort(
        feature_table,
        config=evaluation_config,
        evaluation_keys=evaluation_keys,
    )
    strongest = select_strongest_baseline(
        {result.baseline: result.metrics for result in baseline_scorecard.results},
        hierarchy=set(GOVERNED_BASELINE_HIERARCHY),
    )
    if strongest is not baseline_scorecard.strongest_eligible_baseline:
        raise RuntimeError("Governed strongest-baseline selection is inconsistent.")
    shared_keys = set(shared)
    ordered_rows = [
        row
        for row in evaluation.iter_rows(named=True)
        if (str(row["source_player_id"]), str(row["game_id"])) in shared_keys
    ]
    if not ordered_rows:
        raise ValueError("Learned model has no rows in the governed shared cohort.")
    candidate_frame = pl.DataFrame(ordered_rows, schema=evaluation.schema)
    candidate_predictions = list(model.predict(candidate_frame))
    actuals = [float(row[model_config.target_column]) for row in ordered_rows]
    reference_predictions = [
        float(shared[(str(row["source_player_id"]), str(row["game_id"]))][strongest]["prediction"])
        for row in ordered_rows
    ]
    metrics, calibration = calculate_metrics(
        actuals,
        candidate_predictions,
        coverage=len(ordered_rows) / evaluation.height,
        calibration_line=evaluation_config.calibration_line,
        calibration_bins=evaluation_config.protocol.calibration_bins,
        poisson_epsilon=evaluation_config.poisson_epsilon,
    )
    comparison = paired_mae_bootstrap(
        actuals,
        reference_predictions,
        candidate_predictions,
        iterations=evaluation_config.protocol.bootstrap_iterations,
        confidence_level=evaluation_config.protocol.confidence_level,
        random_seed=evaluation_config.protocol.random_seed,
    )
    baseline_result = next(
        result for result in baseline_scorecard.results if result.baseline is strongest
    )
    gates = LearnedMetricGates(
        lower_mae=metrics.mae < baseline_result.metrics.mae,
        statistically_significant_mae_improvement=(
            comparison.statistically_significant_improvement
        ),
        equal_or_better_calibration=(
            metrics.calibration_error <= baseline_result.metrics.calibration_error
        ),
        improved_poisson_deviance=(
            metrics.poisson_deviance < baseline_result.metrics.poisson_deviance
        ),
    )
    candidate = LearnedCandidateResult(
        model_name=model.state.config.model_name,
        model_version=model.state.config.model_version,
        model_fingerprint=model.fingerprint,
        model_state=model.state,
        governed_comparison_baseline=strongest,
        metrics=metrics,
        calibration=calibration,
        comparison=comparison,
        metric_gates=gates,
    )
    recommendation = _learned_recommendation(gates)
    payload = {
        "schema_version": "1.0",
        "governance_version": baseline_scorecard.governance_version,
        "evaluation_protocol_version": (
            baseline_scorecard.evaluation_protocol_version
        ),
        "baseline_scorecard_hash": baseline_scorecard.scorecard_hash,
        "baseline_candidates": tuple(spec.name.value for spec in BASELINE_SPECS),
        "candidate": candidate.model_dump(mode="json"),
        "recommendation": recommendation.model_dump(mode="json"),
        "reproducibility": reproducibility.model_dump(mode="json"),
        "configuration_hash": evaluation_config.config_hash,
        "training_period": evaluation_config.training_period.model_dump(mode="json"),
        "validation_period": evaluation_config.validation_period.model_dump(mode="json"),
        "random_seed": evaluation_config.protocol.random_seed,
        "shared_cohort_size": len(ordered_rows),
    }
    scorecard = LearnedEvaluationScorecard(
        **payload,
        evaluated_at=evaluation_time,
        scorecard_hash=canonical_hash(payload),
    )
    return model, scorecard


def write_learned_scorecard(scorecard: LearnedEvaluationScorecard, path: Path) -> Path:
    """Atomically write a learned-model scorecard."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(scorecard.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
