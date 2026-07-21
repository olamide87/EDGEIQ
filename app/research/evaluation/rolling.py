"""Deterministic expanding-window evaluation for the learned WR model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.research.evaluation.governance import GOVERNANCE_V1, ResearchDecision
from app.research.evaluation.learned import fit_and_evaluate_wr_poisson
from app.research.evaluation.metrics import (
    MetricSummary,
    PredictionBiasSummary,
    ResidualSummary,
    calculate_metrics,
    summarize_prediction_bias,
    summarize_residuals,
)
from app.research.evaluation.scorecard import (
    BaselineEvaluationConfig,
    EvaluationPeriod,
    PromotionRecommendation,
    ReproducibilityMetadata,
    build_governed_baseline_cohort,
    evaluate_wr_baselines,
)
from app.research.evaluation.statistics import (
    ComparisonMetric,
    MetricDifferenceInterval,
    paired_metric_bootstrap,
)
from app.research.features import canonical_feature_content_hash, validate_wr_feature_table
from app.research.manifest import canonical_hash
from app.research.models import (
    WRPoissonConfig,
    WRPoissonState,
    chronological_model_split,
    raw_scale_coefficients,
)
from app.research.baselines import BaselineName


class RollingEvaluationWindow(BaseModel):
    """One predeclared held-out period in a rolling evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_id: str = Field(min_length=1)
    evaluation_period: EvaluationPeriod


class RollingEvaluationConfig(BaseModel):
    """Immutable expanding-window protocol and governed metric settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    rolling_protocol_version: str = "1.0"
    training_start: datetime
    windows: tuple[RollingEvaluationWindow, ...]
    baseline_config: BaselineEvaluationConfig

    @model_validator(mode="after")
    def validate_windows(self) -> "RollingEvaluationConfig":
        if self.training_start.utcoffset() is None:
            raise ValueError("Rolling training_start must be timezone-aware.")
        if not self.windows:
            raise ValueError("Rolling evaluation requires at least one window.")
        ids = [window.window_id for window in self.windows]
        if len(ids) != len(set(ids)):
            raise ValueError("Rolling window IDs must be unique.")
        ordered = tuple(
            sorted(
                self.windows,
                key=lambda item: (
                    item.evaluation_period.start,
                    item.evaluation_period.end,
                    item.window_id,
                ),
            )
        )
        if self.windows != ordered:
            raise ValueError("Rolling windows must be in canonical chronological order.")
        previous_end: datetime | None = None
        for window in self.windows:
            period = window.evaluation_period
            if self.training_start >= period.start:
                raise ValueError("Rolling training_start must precede every window.")
            if previous_end is not None and previous_end >= period.start:
                raise ValueError("Rolling evaluation windows must not overlap.")
            previous_end = period.end
        return self

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class MetricDifference(BaseModel):
    """Learned-minus-baseline difference for one metric."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: ComparisonMetric
    learned_value: float
    baseline_value: float
    difference: float


class CoefficientSnapshot(BaseModel):
    """One feature coefficient from one fitted rolling window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_name: str
    standardized_coefficient: float
    raw_scale_coefficient: float


class CoefficientStabilitySummary(BaseModel):
    """Cross-window coefficient range and sign behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_name: str
    window_count: int = Field(ge=1)
    standardized_minimum: float
    standardized_maximum: float
    standardized_mean: float
    standardized_range: float = Field(ge=0)
    raw_scale_minimum: float
    raw_scale_maximum: float
    raw_scale_mean: float
    raw_scale_range: float = Field(ge=0)
    sign_change_count: int = Field(ge=0)


class RollingWindowResult(BaseModel):
    """Auditable result for one expanding training and held-out window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_id: str
    training_period: EvaluationPeriod
    evaluation_period: EvaluationPeriod
    training_row_count: int = Field(ge=1)
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_state: WRPoissonState
    governed_comparison_baseline: BaselineName
    shared_cohort_size: int = Field(ge=1)
    shared_cohort_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_scorecard_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learned_metrics: MetricSummary
    baseline_metrics: MetricSummary
    metric_differences: tuple[MetricDifference, ...]
    learned_residuals: ResidualSummary
    baseline_residuals: ResidualSummary
    prediction_bias: PredictionBiasSummary
    coefficients: tuple[CoefficientSnapshot, ...]


class RollingEvaluationScorecard(BaseModel):
    """Canonical v0.6B rolling learned-model research artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    governance_version: str
    rolling_protocol_version: str
    evaluated_at: datetime
    configuration_hash: str
    reproducibility: ReproducibilityMetadata
    windows: tuple[RollingWindowResult, ...]
    aggregate_learned_metrics: MetricSummary
    aggregate_baseline_metrics: MetricSummary
    aggregate_metric_differences: tuple[MetricDifference, ...]
    aggregate_confidence_intervals: tuple[MetricDifferenceInterval, ...]
    coefficient_stability: tuple[CoefficientStabilitySummary, ...]
    recommendation: PromotionRecommendation
    scorecard_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def calculate_metric_differences(
    learned: MetricSummary, baseline: MetricSummary
) -> tuple[MetricDifference, ...]:
    """Return required metrics in stable learned-minus-baseline order."""

    values = (
        (ComparisonMetric.MAE, learned.mae, baseline.mae),
        (ComparisonMetric.RMSE, learned.rmse, baseline.rmse),
        (
            ComparisonMetric.POISSON_DEVIANCE,
            learned.poisson_deviance,
            baseline.poisson_deviance,
        ),
        (ComparisonMetric.MEAN_PREDICTION_BIAS, learned.bias, baseline.bias),
    )
    return tuple(
        MetricDifference(
            metric=metric,
            learned_value=learned_value,
            baseline_value=baseline_value,
            difference=learned_value - baseline_value,
        )
        for metric, learned_value, baseline_value in values
    )


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def summarize_coefficient_stability(
    windows: tuple[RollingWindowResult, ...],
) -> tuple[CoefficientStabilitySummary, ...]:
    """Summarize coefficients in the fitted model's canonical feature order."""

    if not windows:
        raise ValueError("Coefficient stability requires at least one window.")
    names = tuple(item.feature_name for item in windows[0].coefficients)
    if any(
        tuple(item.feature_name for item in window.coefficients) != names
        for window in windows
    ):
        raise ValueError("Rolling windows must use identical ordered model features.")
    summaries: list[CoefficientStabilitySummary] = []
    for index, name in enumerate(names):
        standardized = [
            window.coefficients[index].standardized_coefficient for window in windows
        ]
        raw = [
            window.coefficients[index].raw_scale_coefficient for window in windows
        ]
        signs = [_sign(value) for value in standardized]
        summaries.append(
            CoefficientStabilitySummary(
                feature_name=name,
                window_count=len(windows),
                standardized_minimum=min(standardized),
                standardized_maximum=max(standardized),
                standardized_mean=sum(standardized) / len(standardized),
                standardized_range=max(standardized) - min(standardized),
                raw_scale_minimum=min(raw),
                raw_scale_maximum=max(raw),
                raw_scale_mean=sum(raw) / len(raw),
                raw_scale_range=max(raw) - min(raw),
                sign_change_count=sum(
                    left != right
                    for left, right in zip(signs, signs[1:])
                ),
            )
        )
    return tuple(summaries)


def _period_for_window(
    config: RollingEvaluationConfig, window: RollingEvaluationWindow
) -> EvaluationPeriod:
    return EvaluationPeriod(
        start=config.training_start,
        end=window.evaluation_period.start - timedelta(microseconds=1),
    )


def _ordered_window_inputs(
    feature_table: pl.DataFrame,
    *,
    model_config: WRPoissonConfig,
    evaluation_config: BaselineEvaluationConfig,
    model_state: WRPoissonState,
    strongest: BaselineName,
) -> tuple[list[tuple[str, str]], list[float], list[float], list[float]]:
    from app.research.models import WRPoissonModel

    model = WRPoissonModel.from_state(model_state)
    _, evaluation = chronological_model_split(
        feature_table,
        training_period=evaluation_config.training_period,
        evaluation_period=evaluation_config.validation_period,
    )
    eligible = evaluation.filter(
        pl.all_horizontal(
            *(pl.col(name).is_not_null() for name in model_config.feature_names)
        )
    )
    keys = eligible.select("source_player_id", "game_id")
    shared, _ = build_governed_baseline_cohort(
        feature_table, config=evaluation_config, evaluation_keys=keys
    )
    shared_keys = set(shared)
    rows = [
        row
        for row in eligible.iter_rows(named=True)
        if (str(row["source_player_id"]), str(row["game_id"])) in shared_keys
    ]
    ordered_keys = [
        (str(row["source_player_id"]), str(row["game_id"])) for row in rows
    ]
    candidate_frame = pl.DataFrame(rows, schema=evaluation.schema)
    learned = list(model.predict(candidate_frame))
    actuals = [float(row[model_config.target_column]) for row in rows]
    baseline = [
        float(shared[key][strongest]["prediction"]) for key in ordered_keys
    ]
    if not (len(ordered_keys) == len(actuals) == len(learned) == len(baseline)):
        raise RuntimeError("Rolling learned and baseline cohorts are not aligned.")
    return ordered_keys, actuals, baseline, learned


def evaluate_wr_poisson_rolling(
    feature_table: pl.DataFrame,
    *,
    model_config: WRPoissonConfig,
    rolling_config: RollingEvaluationConfig,
    reproducibility: ReproducibilityMetadata,
    evaluated_at: datetime | None = None,
) -> RollingEvaluationScorecard:
    """Run deterministic expanding-window WR Poisson research evaluation."""

    validate_wr_feature_table(feature_table)
    if (
        canonical_feature_content_hash(feature_table)
        != reproducibility.canonical_feature_table_hash
    ):
        raise ValueError("Canonical feature-table hash does not match rolling input.")

    window_results: list[RollingWindowResult] = []
    pooled_keys: set[tuple[str, str]] = set()
    pooled_actuals: list[float] = []
    pooled_baseline: list[float] = []
    pooled_learned: list[float] = []
    for window in rolling_config.windows:
        training_period = _period_for_window(rolling_config, window)
        evaluation_config = rolling_config.baseline_config.model_copy(
            update={
                "training_period": training_period,
                "validation_period": window.evaluation_period,
            }
        )
        model, learned_scorecard = fit_and_evaluate_wr_poisson(
            feature_table,
            model_config=model_config,
            evaluation_config=evaluation_config,
            reproducibility=reproducibility,
            evaluated_at=evaluated_at,
        )
        strongest = learned_scorecard.candidate.governed_comparison_baseline
        baseline_scorecard = evaluate_wr_baselines(
            feature_table,
            config=evaluation_config,
            reproducibility=reproducibility,
            evaluated_at=evaluated_at,
            evaluation_keys=chronological_model_split(
                feature_table,
                training_period=training_period,
                evaluation_period=window.evaluation_period,
            )[1]
            .filter(
                pl.all_horizontal(
                    *(
                        pl.col(name).is_not_null()
                        for name in model_config.feature_names
                    )
                )
            )
            .select("source_player_id", "game_id"),
        )
        if (
            baseline_scorecard.scorecard_hash
            != learned_scorecard.baseline_scorecard_hash
        ):
            raise RuntimeError("Rolling governed baseline scorecard is inconsistent.")
        baseline_result = next(
            result
            for result in baseline_scorecard.results
            if result.baseline is strongest
        )
        keys, actuals, baseline, learned = _ordered_window_inputs(
            feature_table,
            model_config=model_config,
            evaluation_config=evaluation_config,
            model_state=model.state,
            strongest=strongest,
        )
        duplicate = pooled_keys.intersection(keys)
        if duplicate:
            raise ValueError("Rolling evaluation windows contain duplicate held-out rows.")
        pooled_keys.update(keys)
        pooled_actuals.extend(actuals)
        pooled_baseline.extend(baseline)
        pooled_learned.extend(learned)
        raw = raw_scale_coefficients(model.state)
        coefficients = tuple(
            CoefficientSnapshot(
                feature_name=name,
                standardized_coefficient=standardized,
                raw_scale_coefficient=raw_value,
            )
            for name, standardized, raw_value in zip(
                model_config.feature_names, model.state.coefficients, raw, strict=True
            )
        )
        window_results.append(
            RollingWindowResult(
                window_id=window.window_id,
                training_period=training_period,
                evaluation_period=window.evaluation_period,
                training_row_count=model.state.training.row_count,
                model_fingerprint=model.fingerprint,
                model_state=model.state,
                governed_comparison_baseline=strongest,
                shared_cohort_size=len(keys),
                shared_cohort_hash=canonical_hash({"ordered_player_games": keys}),
                baseline_scorecard_hash=baseline_scorecard.scorecard_hash,
                learned_metrics=learned_scorecard.candidate.metrics,
                baseline_metrics=baseline_result.metrics,
                metric_differences=calculate_metric_differences(
                    learned_scorecard.candidate.metrics, baseline_result.metrics
                ),
                learned_residuals=summarize_residuals(actuals, learned),
                baseline_residuals=summarize_residuals(actuals, baseline),
                prediction_bias=summarize_prediction_bias(actuals, baseline, learned),
                coefficients=coefficients,
            )
        )

    metric_settings = rolling_config.baseline_config
    aggregate_learned, _ = calculate_metrics(
        pooled_actuals,
        pooled_learned,
        coverage=1.0,
        calibration_line=metric_settings.calibration_line,
        calibration_bins=metric_settings.protocol.calibration_bins,
        poisson_epsilon=metric_settings.poisson_epsilon,
    )
    aggregate_baseline, _ = calculate_metrics(
        pooled_actuals,
        pooled_baseline,
        coverage=1.0,
        calibration_line=metric_settings.calibration_line,
        calibration_bins=metric_settings.protocol.calibration_bins,
        poisson_epsilon=metric_settings.poisson_epsilon,
    )
    intervals = tuple(
        paired_metric_bootstrap(
            pooled_actuals,
            pooled_baseline,
            pooled_learned,
            metric=metric,
            poisson_epsilon=metric_settings.poisson_epsilon,
            iterations=metric_settings.protocol.bootstrap_iterations,
            confidence_level=metric_settings.protocol.confidence_level,
            random_seed=metric_settings.protocol.random_seed,
        )
        for metric in ComparisonMetric
    )
    windows = tuple(window_results)
    recommendation = PromotionRecommendation(
        decision=ResearchDecision.RESEARCH,
        reasons=(
            "v0.6B provides rolling research diagnostics only.",
            "No production promotion or wagering execution is permitted.",
        ),
    )
    payload = {
        "schema_version": "1.0",
        "governance_version": GOVERNANCE_V1.version,
        "rolling_protocol_version": rolling_config.rolling_protocol_version,
        "configuration_hash": rolling_config.config_hash,
        "reproducibility": reproducibility.model_dump(mode="json"),
        "windows": [item.model_dump(mode="json") for item in windows],
        "aggregate_learned_metrics": aggregate_learned.model_dump(mode="json"),
        "aggregate_baseline_metrics": aggregate_baseline.model_dump(mode="json"),
        "aggregate_metric_differences": [
            item.model_dump(mode="json")
            for item in calculate_metric_differences(
                aggregate_learned, aggregate_baseline
            )
        ],
        "aggregate_confidence_intervals": [
            item.model_dump(mode="json") for item in intervals
        ],
        "coefficient_stability": [
            item.model_dump(mode="json")
            for item in summarize_coefficient_stability(windows)
        ],
        "recommendation": recommendation.model_dump(mode="json"),
    }
    return RollingEvaluationScorecard(
        **payload,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        scorecard_hash=canonical_hash(payload),
    )


def write_rolling_scorecard(
    scorecard: RollingEvaluationScorecard, path: Path
) -> Path:
    """Atomically write a canonical rolling scorecard."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(scorecard.model_dump(mode="json"), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
