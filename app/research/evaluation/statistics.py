"""Deterministic paired statistical comparisons."""

from __future__ import annotations

import math
import random

from pydantic import BaseModel, ConfigDict, Field


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
