"""Deterministic baseline evaluation, failure analysis, and scorecards."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.research.baselines import (
    BASELINE_SPECS,
    BaselineName,
    build_wr_baseline_predictions,
)
from app.research.evaluation.governance import (
    GOVERNANCE_V1,
    EvaluationProtocol,
    ResearchDecision,
)
from app.research.evaluation.metrics import (
    CalibrationBin,
    MetricSummary,
    calculate_metrics,
)
from app.research.evaluation.statistics import (
    BootstrapComparison,
    paired_mae_bootstrap,
)
from app.research.features import (
    FEATURE_COLUMNS,
    canonical_feature_content_hash,
    validate_wr_feature_table,
)
from app.research.manifest import canonical_hash
from feature_store.registry import WR_FEATURE_REGISTRY


class EvaluationPeriod(BaseModel):
    """Inclusive chronological period recorded in a scorecard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self) -> "EvaluationPeriod":
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("Evaluation periods must use timezone-aware timestamps.")
        if self.start > self.end:
            raise ValueError("Evaluation period start must not be after its end.")
        return self


class BaselineEvaluationConfig(BaseModel):
    """Immutable settings that determine evaluation results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    training_period: EvaluationPeriod
    validation_period: EvaluationPeriod
    calibration_line: float = Field(default=4.5, ge=0)
    poisson_epsilon: float = Field(default=1e-12, gt=0)
    minimum_evaluation_rows: int = Field(default=1, ge=1)
    error_report_limit: int = Field(default=10, ge=1)
    rookie_max_prior_games: int = Field(default=16, ge=0)
    high_volume_targets: float = Field(default=7.0, ge=0)
    early_season_last_week: int = Field(default=8, ge=1)
    post_bye_minimum_rest_days: float = Field(default=13.0, ge=0)
    protocol: EvaluationProtocol = Field(default_factory=lambda: GOVERNANCE_V1.protocol)

    @model_validator(mode="after")
    def chronological(self) -> "BaselineEvaluationConfig":
        if self.training_period.end >= self.validation_period.start:
            raise ValueError("Training period must end before validation begins.")
        return self

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ReproducibilityMetadata(BaseModel):
    """Content identities required to reproduce a scorecard."""

    model_config = ConfigDict(frozen=True)

    dataset_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_feature_table_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    git_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class BaselineResult(BaseModel):
    """Metrics and comparison evidence for one baseline."""

    model_config = ConfigDict(frozen=True)

    baseline: BaselineName
    level: str
    implementation_version: str
    status: str
    metrics: MetricSummary
    calibration: tuple[CalibrationBin, ...]
    comparison_to_strongest: BootstrapComparison | None


class ErrorRecord(BaseModel):
    """One auditable prediction error."""

    model_config = ConfigDict(frozen=True)

    source_player_id: str
    game_id: str
    team: str
    opponent: str
    actual: float
    prediction: float
    error: float


class SegmentResult(BaseModel):
    """Metrics for a pre-registered segment."""

    model_config = ConfigDict(frozen=True)

    sample_count: int = Field(ge=0)
    metrics: MetricSummary | None


class FailureReport(BaseModel):
    """Standardized diagnostic report for the strongest baseline."""

    model_config = ConfigDict(frozen=True)

    segments: dict[str, SegmentResult]
    largest_over_predictions: tuple[ErrorRecord, ...]
    largest_under_predictions: tuple[ErrorRecord, ...]
    bias_by_player: dict[str, float]
    bias_by_team: dict[str, float]
    bias_by_opponent: dict[str, float]
    missing_feature_frequencies: dict[str, float]
    disabled_features: tuple[str, ...]
    warnings: tuple[str, ...]


class PromotionRecommendation(BaseModel):
    """Formal decision emitted for every evaluation run."""

    model_config = ConfigDict(frozen=True)

    decision: ResearchDecision
    reasons: tuple[str, ...]


class BaselineScorecard(BaseModel):
    """Complete versioned v0.5C research artifact."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    governance_version: str
    evaluation_protocol_version: str
    evaluated_at: datetime
    configuration_hash: str
    training_period: EvaluationPeriod
    validation_period: EvaluationPeriod
    random_seed: int
    reproducibility: ReproducibilityMetadata
    baseline_versions: dict[str, str]
    shared_cohort_size: int
    baseline_selection_rule: str
    strongest_eligible_baseline: BaselineName
    results: tuple[BaselineResult, ...]
    failure_report: FailureReport
    recommendation: PromotionRecommendation
    scorecard_hash: str


def _shared_rows(
    predictions: pl.DataFrame,
    baseline_names: tuple[BaselineName, ...],
) -> tuple[dict[tuple[str, str], dict[BaselineName, dict[str, Any]]], dict[str, float]]:
    names = {name.value for name in baseline_names}
    rows = predictions.filter(pl.col("baseline").is_in(names)).to_dicts()
    grouped: dict[tuple[str, str], dict[BaselineName, dict[str, Any]]] = {}
    total_keys: set[tuple[str, str]] = set()
    eligible_counts = {name.value: 0 for name in baseline_names}
    for row in rows:
        key = (str(row["source_player_id"]), str(row["game_id"]))
        total_keys.add(key)
        name = BaselineName(str(row["baseline"]))
        if bool(row["eligible"]):
            eligible_counts[name.value] += 1
            grouped.setdefault(key, {})[name] = row
    shared = {
        key: values
        for key, values in grouped.items()
        if set(values) == set(baseline_names)
    }
    denominator = len(total_keys)
    coverage = {
        name: (count / denominator if denominator else 0.0)
        for name, count in eligible_counts.items()
    }
    return dict(sorted(shared.items())), coverage


def _metric_inputs(
    shared: dict[tuple[str, str], dict[BaselineName, dict[str, Any]]],
    baseline: BaselineName,
) -> tuple[list[float], list[float]]:
    actuals = [
        float(values[baseline]["actual_receptions"]) for values in shared.values()
    ]
    predictions = [float(values[baseline]["prediction"]) for values in shared.values()]
    return actuals, predictions


def select_strongest_baseline(
    metrics: dict[BaselineName, MetricSummary],
    *,
    hierarchy: set[BaselineName],
) -> BaselineName:
    """Select by governed MAE only, with name as an exact-tie breaker."""

    missing = sorted(name.value for name in hierarchy - set(metrics))
    if missing:
        raise ValueError(
            f"Cannot select strongest baseline; missing metrics for: {', '.join(missing)}."
        )
    if GOVERNANCE_V1.protocol.baseline_selection_metric.value != "mean_absolute_error":
        raise ValueError("Unsupported baseline-selection metric for Governance v1.0.")
    return min(
        hierarchy,
        key=lambda name: (metrics[name].mae, name.value),
    )


def _group_bias(rows: list[dict[str, Any]], column: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row[column]), []).append(float(row["error"]))
    return {
        name: sum(values) / len(values)
        for name, values in sorted(grouped.items())
    }


def _segment_metrics(
    rows: list[dict[str, Any]],
    predicate: Any,
    *,
    config: BaselineEvaluationConfig,
) -> SegmentResult:
    selected = [row for row in rows if predicate(row)]
    if not selected:
        return SegmentResult(sample_count=0, metrics=None)
    actuals = [float(row["actual"]) for row in selected]
    predictions = [float(row["prediction"]) for row in selected]
    metrics, _ = calculate_metrics(
        actuals,
        predictions,
        coverage=1.0,
        calibration_line=config.calibration_line,
        calibration_bins=config.protocol.calibration_bins,
        poisson_epsilon=config.poisson_epsilon,
    )
    return SegmentResult(sample_count=len(selected), metrics=metrics)


def _failure_report(
    feature_table: pl.DataFrame,
    shared: dict[tuple[str, str], dict[BaselineName, dict[str, Any]]],
    strongest: BaselineName,
    *,
    config: BaselineEvaluationConfig,
) -> FailureReport:
    context_columns = (
        "source_player_id",
        "game_id",
        "team",
        "opponent",
        "is_home",
        "game_week",
        "games_played_before",
        "targets_roll5",
        "rest_days",
    )
    context = {
        (str(row["source_player_id"]), str(row["game_id"])): row
        for row in feature_table.select(context_columns).iter_rows(named=True)
    }
    rows: list[dict[str, Any]] = []
    for key, values in shared.items():
        prediction_row = values[strongest]
        item = context[key]
        actual = float(prediction_row["actual_receptions"])
        prediction = float(prediction_row["prediction"])
        rows.append(
            {
                **item,
                "actual": actual,
                "prediction": prediction,
                "error": prediction - actual,
            }
        )
    rows.sort(key=lambda row: (str(row["game_id"]), str(row["source_player_id"])))

    def record(row: dict[str, Any]) -> ErrorRecord:
        return ErrorRecord(
            source_player_id=str(row["source_player_id"]),
            game_id=str(row["game_id"]),
            team=str(row["team"]),
            opponent=str(row["opponent"]),
            actual=float(row["actual"]),
            prediction=float(row["prediction"]),
            error=float(row["error"]),
        )

    over = sorted(
        (row for row in rows if float(row["error"]) > 0),
        key=lambda row: (-float(row["error"]), str(row["game_id"]), str(row["source_player_id"])),
    )[: config.error_report_limit]
    under = sorted(
        (row for row in rows if float(row["error"]) < 0),
        key=lambda row: (float(row["error"]), str(row["game_id"]), str(row["source_player_id"])),
    )[: config.error_report_limit]
    segments = {
        "rookies": _segment_metrics(
            rows,
            lambda row: int(row["games_played_before"]) <= config.rookie_max_prior_games,
            config=config,
        ),
        "veterans": _segment_metrics(
            rows,
            lambda row: int(row["games_played_before"]) > config.rookie_max_prior_games,
            config=config,
        ),
        "low_volume": _segment_metrics(
            rows,
            lambda row: row["targets_roll5"] is not None
            and float(row["targets_roll5"]) < config.high_volume_targets,
            config=config,
        ),
        "high_volume": _segment_metrics(
            rows,
            lambda row: row["targets_roll5"] is not None
            and float(row["targets_roll5"]) >= config.high_volume_targets,
            config=config,
        ),
        "early_season": _segment_metrics(
            rows,
            lambda row: int(row["game_week"]) <= config.early_season_last_week,
            config=config,
        ),
        "late_season": _segment_metrics(
            rows,
            lambda row: int(row["game_week"]) > config.early_season_last_week,
            config=config,
        ),
        "home": _segment_metrics(rows, lambda row: bool(row["is_home"]), config=config),
        "away": _segment_metrics(rows, lambda row: not bool(row["is_home"]), config=config),
        "after_bye": _segment_metrics(
            rows,
            lambda row: row["rest_days"] is not None
            and float(row["rest_days"]) >= config.post_bye_minimum_rest_days,
            config=config,
        ),
    }
    missing = {
        column: feature_table.get_column(column).null_count() / feature_table.height
        if feature_table.height
        else 0.0
        for column in FEATURE_COLUMNS
    }
    disabled = tuple(
        feature.name for feature in WR_FEATURE_REGISTRY.features if not feature.enabled
    )
    warnings = tuple(
        f"Segment {name} has no evaluable rows."
        for name, result in segments.items()
        if result.sample_count == 0
    )
    return FailureReport(
        segments=segments,
        largest_over_predictions=tuple(record(row) for row in over),
        largest_under_predictions=tuple(record(row) for row in under),
        bias_by_player=_group_bias(rows, "source_player_id"),
        bias_by_team=_group_bias(rows, "team"),
        bias_by_opponent=_group_bias(rows, "opponent"),
        missing_feature_frequencies=missing,
        disabled_features=disabled,
        warnings=warnings,
    )


def evaluate_wr_baselines(
    feature_table: pl.DataFrame,
    *,
    config: BaselineEvaluationConfig,
    reproducibility: ReproducibilityMetadata,
    evaluated_at: datetime | None = None,
) -> BaselineScorecard:
    """Evaluate every governed baseline and return a deterministic scorecard."""

    validate_wr_feature_table(feature_table)
    content_hash = canonical_feature_content_hash(feature_table)
    if reproducibility.canonical_feature_table_hash != content_hash:
        raise ValueError("Canonical feature-table hash does not match evaluation input.")
    if reproducibility.feature_registry_hash != WR_FEATURE_REGISTRY.registry_hash:
        raise ValueError("Feature registry hash does not match Governance input.")

    predictions = build_wr_baseline_predictions(feature_table)
    kickoff_dtype = predictions.schema["kickoff"]
    validation_start = config.validation_period.start
    validation_end = config.validation_period.end
    if isinstance(kickoff_dtype, pl.Datetime) and kickoff_dtype.time_zone is None:
        validation_start = validation_start.astimezone(timezone.utc).replace(tzinfo=None)
        validation_end = validation_end.astimezone(timezone.utc).replace(tzinfo=None)
    predictions = predictions.filter(
        (pl.col("kickoff") >= validation_start)
        & (pl.col("kickoff") <= validation_end)
    )
    required = tuple(spec.name for spec in BASELINE_SPECS)
    shared, coverage = _shared_rows(predictions, required)
    if len(shared) < config.minimum_evaluation_rows:
        raise ValueError(
            "Shared baseline cohort does not meet minimum_evaluation_rows."
        )

    metrics_by_name: dict[BaselineName, MetricSummary] = {}
    calibration_by_name: dict[BaselineName, tuple[CalibrationBin, ...]] = {}
    for name in required:
        actuals, predicted = _metric_inputs(shared, name)
        metrics, calibration = calculate_metrics(
            actuals,
            predicted,
            coverage=coverage[name.value],
            calibration_line=config.calibration_line,
            calibration_bins=config.protocol.calibration_bins,
            poisson_epsilon=config.poisson_epsilon,
        )
        metrics_by_name[name] = metrics
        calibration_by_name[name] = calibration

    hierarchy = {
        BaselineName.LEAGUE_MEAN,
        BaselineName.PREVIOUS_GAME,
        BaselineName.ROLLING_3,
        BaselineName.ROLLING_5,
        BaselineName.SEASON_TO_DATE,
        BaselineName.POISSON,
    }
    strongest = select_strongest_baseline(metrics_by_name, hierarchy=hierarchy)
    actuals, strongest_predictions = _metric_inputs(shared, strongest)
    results: list[BaselineResult] = []
    for spec in BASELINE_SPECS:
        _, candidate_predictions = _metric_inputs(shared, spec.name)
        comparison = (
            None
            if spec.name is strongest
            else paired_mae_bootstrap(
                actuals,
                strongest_predictions,
                candidate_predictions,
                iterations=config.protocol.bootstrap_iterations,
                confidence_level=config.protocol.confidence_level,
                random_seed=config.protocol.random_seed,
            )
        )
        results.append(
            BaselineResult(
                baseline=spec.name,
                level=spec.level,
                implementation_version=spec.implementation_version,
                status=(
                    "STRONGEST_BASELINE"
                    if spec.name is strongest
                    else "DIAGNOSTIC"
                    if spec.name is BaselineName.CAREER_AVERAGE
                    else "REFERENCE"
                ),
                metrics=metrics_by_name[spec.name],
                calibration=calibration_by_name[spec.name],
                comparison_to_strongest=comparison,
            )
        )

    report = _failure_report(feature_table, shared, strongest, config=config)
    evaluation_time = evaluated_at or datetime.now(timezone.utc)
    baseline_versions = {
        spec.name.value: spec.implementation_version for spec in BASELINE_SPECS
    }
    payload = {
        "schema_version": "1.0",
        "governance_version": GOVERNANCE_V1.version,
        "evaluation_protocol_version": config.protocol.version,
        "configuration_hash": config.config_hash,
        "training_period": config.training_period.model_dump(mode="json"),
        "validation_period": config.validation_period.model_dump(mode="json"),
        "random_seed": config.protocol.random_seed,
        "reproducibility": reproducibility.model_dump(mode="json"),
        "baseline_versions": baseline_versions,
        "shared_cohort_size": len(shared),
        "baseline_selection_rule": (
            "lowest_mean_absolute_error_on_shared_cohort_then_baseline_name"
        ),
        "strongest_eligible_baseline": strongest.value,
        "results": [result.model_dump(mode="json") for result in results],
        "failure_report": report.model_dump(mode="json"),
        "recommendation": {
            "decision": ResearchDecision.RESEARCH.value,
            "reasons": [
                "v0.5C establishes the governed baseline benchmark.",
                "No learned candidate was evaluated for promotion.",
            ],
        },
    }
    return BaselineScorecard(
        **payload,
        evaluated_at=evaluation_time,
        scorecard_hash=canonical_hash(payload),
    )


def write_baseline_scorecard(scorecard: BaselineScorecard, path: Path) -> Path:
    """Atomically write a scorecard without changing its canonical identity."""

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
