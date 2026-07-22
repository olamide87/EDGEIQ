"""Deterministic paired statistical comparisons."""

from __future__ import annotations

import math
import random
from enum import StrEnum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.research.evaluation.metrics import mean_poisson_deviance


class ComparisonMetric(StrEnum):
    """Metrics supported by paired learned-versus-baseline comparisons."""

    MAE = "mean_absolute_error"
    RMSE = "root_mean_squared_error"
    POISSON_DEVIANCE = "mean_poisson_deviance"
    MEAN_PREDICTION_BIAS = "mean_prediction_bias"


class MetricDifferenceInterval(BaseModel):
    """Percentile interval for learned-minus-baseline metric difference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: ComparisonMetric
    difference: float
    confidence_lower: float
    confidence_upper: float
    confidence_level: float = Field(gt=0, lt=1)
    sample_count: int = Field(ge=1)
    iterations: int = Field(ge=1)
    random_seed: int


class BootstrapComparison(BaseModel):
    """Paired MAE comparison in reference-minus-candidate direction."""

    model_config = ConfigDict(frozen=True)

    metric: str = "mean_absolute_error"
    difference: float
    confidence_lower: float
    confidence_upper: float
    confidence_level: float = Field(gt=0, lt=1)
    effect_size: float
    effect_size_definition: str = "relative_mae_improvement"
    sample_count: int = Field(ge=1)
    iterations: int = Field(ge=1)
    random_seed: int
    statistically_significant_improvement: bool


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_mae_bootstrap(
    actuals: list[float],
    reference_predictions: list[float],
    candidate_predictions: list[float],
    *,
    iterations: int,
    confidence_level: float,
    random_seed: int,
) -> BootstrapComparison:
    """Compare paired absolute losses using a deterministic percentile bootstrap."""

    if not actuals or not (
        len(actuals) == len(reference_predictions) == len(candidate_predictions)
    ):
        raise ValueError("Paired bootstrap requires equal, non-empty inputs.")
    if iterations < 1:
        raise ValueError("Bootstrap iterations must be positive.")
    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between zero and one.")

    improvements = [
        abs(actual - reference) - abs(actual - candidate)
        for actual, reference, candidate in zip(
            actuals,
            reference_predictions,
            candidate_predictions,
            strict=True,
        )
    ]
    observed = sum(improvements) / len(improvements)
    reference_mae = sum(
        abs(actual - reference)
        for actual, reference in zip(actuals, reference_predictions, strict=True)
    ) / len(actuals)
    rng = random.Random(random_seed)
    sample_size = len(improvements)
    bootstrap_means = [
        sum(rng.choices(improvements, k=sample_size)) / sample_size
        for _ in range(iterations)
    ]
    alpha = 1 - confidence_level
    lower = _quantile(bootstrap_means, alpha / 2)
    upper = _quantile(bootstrap_means, 1 - alpha / 2)
    effect_size = observed / reference_mae if reference_mae > 0 else 0.0
    return BootstrapComparison(
        difference=observed,
        confidence_lower=lower,
        confidence_upper=upper,
        confidence_level=confidence_level,
        effect_size=effect_size,
        sample_count=sample_size,
        iterations=iterations,
        random_seed=random_seed,
        statistically_significant_improvement=lower > 0,
    )


def _metric_value(
    actuals: Sequence[float],
    predictions: Sequence[float],
    *,
    metric: ComparisonMetric,
    poisson_epsilon: float,
) -> float:
    errors = [
        prediction - actual
        for actual, prediction in zip(actuals, predictions, strict=True)
    ]
    if metric is ComparisonMetric.MAE:
        return sum(abs(error) for error in errors) / len(errors)
    if metric is ComparisonMetric.RMSE:
        return math.sqrt(sum(error * error for error in errors) / len(errors))
    if metric is ComparisonMetric.POISSON_DEVIANCE:
        return mean_poisson_deviance(
            list(actuals), list(predictions), epsilon=poisson_epsilon
        )
    if metric is ComparisonMetric.MEAN_PREDICTION_BIAS:
        return sum(errors) / len(errors)
    raise ValueError(f"Unsupported comparison metric: {metric!r}.")


def paired_metric_bootstrap(
    actuals: Sequence[float],
    baseline_predictions: Sequence[float],
    learned_predictions: Sequence[float],
    *,
    metric: ComparisonMetric,
    poisson_epsilon: float,
    iterations: int,
    confidence_level: float,
    random_seed: int,
) -> MetricDifferenceInterval:
    """Bootstrap a paired learned-minus-baseline metric difference."""

    if not actuals or not (
        len(actuals) == len(baseline_predictions) == len(learned_predictions)
    ):
        raise ValueError("Paired bootstrap requires equal, non-empty inputs.")
    if iterations < 1:
        raise ValueError("Bootstrap iterations must be positive.")
    if not 0 < confidence_level < 1:
        raise ValueError("Confidence level must be between zero and one.")
    if poisson_epsilon <= 0 or not math.isfinite(poisson_epsilon):
        raise ValueError("Poisson epsilon must be finite and positive.")
    if any(
        not math.isfinite(value) or value < 0
        for value in (*actuals, *baseline_predictions, *learned_predictions)
    ):
        raise ValueError("Bootstrap inputs must be finite and non-negative.")

    def difference(indices: Sequence[int]) -> float:
        sampled_actuals = [actuals[index] for index in indices]
        sampled_baseline = [baseline_predictions[index] for index in indices]
        sampled_learned = [learned_predictions[index] for index in indices]
        return _metric_value(
            sampled_actuals,
            sampled_learned,
            metric=metric,
            poisson_epsilon=poisson_epsilon,
        ) - _metric_value(
            sampled_actuals,
            sampled_baseline,
            metric=metric,
            poisson_epsilon=poisson_epsilon,
        )

    sample_count = len(actuals)
    observed = difference(range(sample_count))
    rng = random.Random(random_seed)
    bootstrap_differences = [
        difference(rng.choices(range(sample_count), k=sample_count))
        for _ in range(iterations)
    ]
    alpha = 1 - confidence_level
    return MetricDifferenceInterval(
        metric=metric,
        difference=observed,
        confidence_lower=_quantile(bootstrap_differences, alpha / 2),
        confidence_upper=_quantile(bootstrap_differences, 1 - alpha / 2),
        confidence_level=confidence_level,
        sample_count=sample_count,
        iterations=iterations,
        random_seed=random_seed,
    )
