"""Governed metric calculations for non-negative count predictions."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field


class CalibrationBin(BaseModel):
    """One pre-registered probability bin."""

    model_config = ConfigDict(frozen=True)

    lower: float
    upper: float
    count: int = Field(ge=0)
    mean_probability: float | None
    observed_frequency: float | None
    absolute_gap: float | None


class MetricSummary(BaseModel):
    """Promotion-critical and diagnostic metrics for one cohort."""

    model_config = ConfigDict(frozen=True)

    mae: float = Field(ge=0)
    calibration_error: float = Field(ge=0, le=1)
    poisson_deviance: float = Field(ge=0)
    rmse: float = Field(ge=0)
    bias: float
    coverage: float = Field(ge=0, le=1)
    prediction_variance: float = Field(ge=0)
    sample_count: int = Field(ge=1)


def poisson_over_probability(rate: float, line: float) -> float:
    """Return P(X > line) for a Poisson count with the supplied rate."""

    if not math.isfinite(rate) or rate < 0:
        raise ValueError("Poisson rate must be finite and non-negative.")
    if not math.isfinite(line) or line < 0:
        raise ValueError("Calibration line must be finite and non-negative.")
    cutoff = math.floor(line)
    if rate == 0:
        return 0.0
    probability = math.exp(-rate)
    cumulative = probability
    for count in range(1, cutoff + 1):
        probability *= rate / count
        cumulative += probability
    return min(1.0, max(0.0, 1.0 - cumulative))


def calibration_table(
    actuals: list[float],
    predictions: list[float],
    *,
    line: float,
    bin_count: int,
) -> tuple[tuple[CalibrationBin, ...], float]:
    """Calculate fixed-width calibration bins and ECE."""

    if len(actuals) != len(predictions) or not actuals:
        raise ValueError("Calibration requires equal, non-empty actual and prediction lists.")
    if bin_count < 2:
        raise ValueError("Calibration requires at least two bins.")

    bucketed: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
    for actual, prediction in zip(actuals, predictions, strict=True):
        probability = poisson_over_probability(prediction, line)
        observed = 1.0 if actual > line else 0.0
        index = min(int(probability * bin_count), bin_count - 1)
        bucketed[index].append((probability, observed))

    bins: list[CalibrationBin] = []
    weighted_gap = 0.0
    for index, values in enumerate(bucketed):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        if values:
            mean_probability = sum(value[0] for value in values) / len(values)
            observed_frequency = sum(value[1] for value in values) / len(values)
            gap = abs(mean_probability - observed_frequency)
            weighted_gap += len(values) * gap
        else:
            mean_probability = None
            observed_frequency = None
            gap = None
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(values),
                mean_probability=mean_probability,
                observed_frequency=observed_frequency,
                absolute_gap=gap,
            )
        )
    return tuple(bins), weighted_gap / len(actuals)


def mean_poisson_deviance(
    actuals: list[float],
    predictions: list[float],
    *,
    epsilon: float,
) -> float:
    """Calculate mean Poisson deviance with a registered positive floor."""

    if epsilon <= 0 or not math.isfinite(epsilon):
        raise ValueError("Poisson epsilon must be finite and positive.")
    terms: list[float] = []
    for actual, prediction in zip(actuals, predictions, strict=True):
        rate = max(prediction, epsilon)
        if actual == 0:
            terms.append(2 * rate)
        else:
            terms.append(2 * (actual * math.log(actual / rate) - (actual - rate)))
    return sum(terms) / len(terms)


def calculate_metrics(
    actuals: list[float],
    predictions: list[float],
    *,
    coverage: float,
    calibration_line: float,
    calibration_bins: int,
    poisson_epsilon: float,
) -> tuple[MetricSummary, tuple[CalibrationBin, ...]]:
    """Calculate the complete Governance v1.0 metric set."""

    if len(actuals) != len(predictions) or not actuals:
        raise ValueError("Metrics require equal, non-empty actual and prediction lists.")
    if not 0 <= coverage <= 1:
        raise ValueError("Coverage must be between zero and one.")
    if any(
        not math.isfinite(value) or value < 0
        for value in (*actuals, *predictions)
    ):
        raise ValueError("Actuals and predictions must be finite and non-negative.")

    errors = [
        prediction - actual
        for actual, prediction in zip(actuals, predictions, strict=True)
    ]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    bias = sum(errors) / len(errors)
    prediction_mean = sum(predictions) / len(predictions)
    variance = (
        sum((prediction - prediction_mean) ** 2 for prediction in predictions)
        / len(predictions)
    )
    bins, calibration_error = calibration_table(
        actuals,
        predictions,
        line=calibration_line,
        bin_count=calibration_bins,
    )
    deviance = mean_poisson_deviance(
        actuals,
        predictions,
        epsilon=poisson_epsilon,
    )
    return (
        MetricSummary(
            mae=mae,
            calibration_error=calibration_error,
            poisson_deviance=deviance,
            rmse=rmse,
            bias=bias,
            coverage=coverage,
            prediction_variance=variance,
            sample_count=len(actuals),
        ),
        bins,
    )
