"""Deterministic penalized Poisson regression for WR receptions.

The implementation intentionally uses only the Python standard library and
Polars because EDGE IQ does not currently declare a numerical-modeling
dependency. It is a small research baseline for learned-model evaluation, not a
production projection system.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping, Protocol

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.research.manifest import canonical_hash
from feature_store.registry import FeatureTiming, LeakageRisk, WR_FEATURE_REGISTRY


DEFAULT_WR_POISSON_FEATURES: tuple[str, ...] = (
    "receptions_roll3",
    "targets_roll3",
    "home_indicator",
    "games_played_before",
)


class ModelFitError(ValueError):
    """Raised when model inputs or numerical fitting are invalid."""


class ModelNotFittedError(RuntimeError):
    """Raised when fitted state is requested before training."""


class PeriodLike(Protocol):
    """Structural period interface shared with governed evaluation config."""

    start: datetime
    end: datetime


class WRPoissonConfig(BaseModel):
    """Immutable, explicit hyperparameters and feature order."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    model_name: str = "wr_receptions_poisson_regression"
    model_version: str = "0.1.0"
    feature_names: tuple[str, ...] = DEFAULT_WR_POISSON_FEATURES
    target_column: str = "actual_receptions"
    l2_penalty: float = Field(default=1.0, gt=0)
    max_iterations: int = Field(default=100, ge=1)
    tolerance: float = Field(default=1e-10, gt=0)
    linear_predictor_limit: float = Field(default=20.0, gt=0, le=700)
    solver_epsilon: float = Field(default=1e-10, gt=0)
    minimum_training_rows: int = Field(default=4, ge=2)

    @model_validator(mode="after")
    def validate_feature_contract(self) -> "WRPoissonConfig":
        if self.target_column != "actual_receptions":
            raise ValueError(
                "WR Poisson model version 0.1.0 requires target_column "
                "'actual_receptions'."
            )
        if not self.feature_names:
            raise ValueError("At least one model feature is required.")
        if len(self.feature_names) != len(set(self.feature_names)):
            raise ValueError("Model feature names must be unique and ordered.")
        for name in self.feature_names:
            try:
                feature = WR_FEATURE_REGISTRY.by_name(name)
            except KeyError as exc:
                raise ValueError(f"Unknown WR feature {name!r}.") from exc
            if not feature.enabled:
                raise ValueError(f"WR feature {name!r} is not enabled.")
            if feature.availability_timing is FeatureTiming.POSTGAME:
                raise ValueError(f"WR feature {name!r} is postgame-only.")
            if feature.leakage_risk is LeakageRisk.HIGH:
                raise ValueError(f"WR feature {name!r} has high leakage risk.")
        return self


class ModelTrainingContext(BaseModel):
    """Versioned source identities associated with a fit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_feature_table_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    git_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def current_registry_required(self) -> "ModelTrainingContext":
        if self.feature_registry_hash != WR_FEATURE_REGISTRY.registry_hash:
            raise ValueError("Training context feature registry hash is not current.")
        return self


class ModelTrainingMetadata(BaseModel):
    """Deterministic information about the fitted training cohort."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_count: int = Field(ge=1)
    period_start: datetime
    period_end: datetime
    training_data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    iterations: int = Field(ge=1)
    converged: bool
    context: ModelTrainingContext


class WRPoissonState(BaseModel):
    """Canonical serializable fitted state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: WRPoissonConfig
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]
    training: ModelTrainingMetadata
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_state(self) -> "WRPoissonState":
        expected = len(self.config.feature_names)
        if not (
            len(self.feature_means)
            == len(self.feature_scales)
            == len(self.coefficients)
            == expected
        ):
            raise ValueError("Fitted arrays must match the ordered feature list.")
        numeric = (
            *self.feature_means,
            *self.feature_scales,
            self.intercept,
            *self.coefficients,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("Fitted state must contain only finite values.")
        if any(value <= 0 for value in self.feature_scales):
            raise ValueError("Fitted feature scales must be positive.")
        if self.fingerprint != _state_fingerprint(
            self.model_dump(mode="json", exclude={"fingerprint"})
        ):
            raise ValueError("Model fingerprint does not match fitted state.")
        return self


def raw_scale_coefficients(state: WRPoissonState) -> tuple[float, ...]:
    """Transform standardized fitted coefficients to original feature units."""

    return tuple(
        coefficient / scale
        for coefficient, scale in zip(
            state.coefficients, state.feature_scales, strict=True
        )
    )


def _state_fingerprint(payload: dict[str, Any]) -> str:
    return canonical_hash(payload)


def _coerce_numeric_columns(
    frame: pl.DataFrame,
    columns: tuple[str, ...],
    *,
    label: str,
) -> pl.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ModelFitError(f"{label} is missing required columns: {', '.join(missing)}.")
    result = frame
    for column in columns:
        temporary = f"__edgeiq_model_numeric_{column}"
        try:
            converted = result.with_columns(
                pl.col(column).cast(pl.Float64, strict=False).alias(temporary)
            )
        except Exception as exc:
            raise ModelFitError(
                f"{label}.{column} must contain finite numeric values."
            ) from exc
        invalid = converted.filter(
            pl.col(column).is_null()
            | pl.col(temporary).is_null()
            | ~pl.col(temporary).is_finite()
        )
        if invalid.height:
            raise ModelFitError(
                f"{label}.{column} must contain finite numeric values without nulls."
            )
        result = converted.with_columns(pl.col(temporary).alias(column)).drop(temporary)
    return result


def _ordered_training_frame(frame: pl.DataFrame, config: WRPoissonConfig) -> pl.DataFrame:
    ordering = ("kickoff", "game_id", "source_player_id")
    required = (*ordering, *config.feature_names, config.target_column)
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ModelFitError(
            f"training_data is missing required columns: {', '.join(missing)}."
        )
    selected = frame.select(required)
    if selected.get_column("kickoff").null_count():
        raise ModelFitError("training_data.kickoff cannot contain nulls.")
    for column in ("game_id", "source_player_id"):
        if selected.filter(
            pl.col(column).is_null()
            | (pl.col(column).cast(pl.String).str.strip_chars() == "")
        ).height:
            raise ModelFitError(f"training_data.{column} cannot contain null or empty values.")
    duplicate = (
        selected.group_by("source_player_id", "game_id")
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicate.height:
        raise ModelFitError("training_data contains duplicate player-game rows.")
    selected = _coerce_numeric_columns(
        selected,
        (*config.feature_names, config.target_column),
        label="training_data",
    )
    targets = selected.get_column(config.target_column)
    if selected.filter(pl.col(config.target_column) < 0).height:
        raise ModelFitError("training_data targets cannot be negative.")
    if any(value != math.floor(value) for value in targets.to_list()):
        raise ModelFitError("training_data targets must be whole-number counts.")
    if selected.height < config.minimum_training_rows:
        raise ModelFitError(
            f"training_data requires at least {config.minimum_training_rows} rows."
        )
    return selected.sort(*ordering)


def _ordered_prediction_frame(frame: pl.DataFrame, config: WRPoissonConfig) -> pl.DataFrame:
    return _coerce_numeric_columns(
        frame.select(config.feature_names)
        if set(config.feature_names) <= set(frame.columns)
        else frame,
        config.feature_names,
        label="prediction_data",
    ).select(config.feature_names)


def _solve_linear_system(
    matrix: list[list[float]],
    vector: list[float],
    *,
    epsilon: float,
) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= epsilon:
            raise ModelFitError("Poisson solver encountered a singular Hessian.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for index in range(column, size + 1):
            augmented[column][index] /= divisor
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            for index in range(column, size + 1):
                augmented[row][index] -= factor * augmented[column][index]
    return [augmented[index][size] for index in range(size)]


def _objective(
    design: list[list[float]],
    targets: list[float],
    parameters: list[float],
    config: WRPoissonConfig,
) -> float:
    value = 0.0
    for row, target in zip(design, targets, strict=True):
        eta = sum(
            coefficient * item
            for coefficient, item in zip(parameters, row, strict=True)
        )
        if not math.isfinite(eta) or eta > config.linear_predictor_limit:
            return math.inf
        value += math.exp(eta) - target * eta
    value += 0.5 * config.l2_penalty * sum(item * item for item in parameters[1:])
    return value


class WRPoissonModel:
    """Stateful deterministic Poisson estimator with canonical fitted state."""

    def __init__(self, config: WRPoissonConfig | None = None) -> None:
        self.config = config or WRPoissonConfig()
        self._state: WRPoissonState | None = None

    @property
    def is_fitted(self) -> bool:
        return self._state is not None

    @property
    def state(self) -> WRPoissonState:
        if self._state is None:
            raise ModelNotFittedError("WR Poisson model has not been fitted.")
        return self._state

    @property
    def fingerprint(self) -> str:
        return self.state.fingerprint

    def fit(
        self,
        training_data: pl.DataFrame,
        *,
        context: ModelTrainingContext,
    ) -> "WRPoissonModel":
        ordered = _ordered_training_frame(training_data, self.config)
        feature_rows = ordered.select(self.config.feature_names).rows()
        targets = [float(value) for value in ordered.get_column(self.config.target_column)]
        row_count = len(feature_rows)
        feature_count = len(self.config.feature_names)
        means = tuple(
            sum(float(row[index]) for row in feature_rows) / row_count
            for index in range(feature_count)
        )
        scales_list: list[float] = []
        for index, mean in enumerate(means):
            variance = sum(
                (float(row[index]) - mean) ** 2 for row in feature_rows
            ) / row_count
            scale = math.sqrt(variance)
            scales_list.append(scale if scale > self.config.solver_epsilon else 1.0)
        scales = tuple(scales_list)
        design = [
            [1.0]
            + [
                (float(row[index]) - means[index]) / scales[index]
                for index in range(feature_count)
            ]
            for row in feature_rows
        ]
        target_mean = sum(targets) / row_count
        parameters = [math.log(max(target_mean, self.config.solver_epsilon))] + [
            0.0
        ] * feature_count
        if parameters[0] > self.config.linear_predictor_limit:
            raise ModelFitError(
                "Initial Poisson linear predictor exceeds the configured safe limit."
            )
        converged = False
        iterations = 0
        for iteration in range(1, self.config.max_iterations + 1):
            iterations = iteration
            dimension = feature_count + 1
            gradient = [0.0] * dimension
            hessian = [[0.0] * dimension for _ in range(dimension)]
            for row, target in zip(design, targets, strict=True):
                eta = sum(
                    coefficient * item
                    for coefficient, item in zip(parameters, row, strict=True)
                )
                if not math.isfinite(eta) or eta > self.config.linear_predictor_limit:
                    raise ModelFitError(
                        "Poisson solver produced an unsafe linear predictor."
                    )
                expected = math.exp(eta)
                residual = target - expected
                for left in range(dimension):
                    gradient[left] += row[left] * residual
                    for right in range(dimension):
                        hessian[left][right] += row[left] * expected * row[right]
            hessian[0][0] += self.config.solver_epsilon
            for index in range(1, dimension):
                gradient[index] -= self.config.l2_penalty * parameters[index]
                hessian[index][index] += self.config.l2_penalty
            delta = _solve_linear_system(
                hessian,
                gradient,
                epsilon=self.config.solver_epsilon,
            )
            current_objective = _objective(design, targets, parameters, self.config)
            step = 1.0
            candidate = parameters
            while step >= self.config.solver_epsilon:
                attempted = [
                    value + step * change
                    for value, change in zip(parameters, delta, strict=True)
                ]
                if _objective(design, targets, attempted, self.config) <= current_objective:
                    candidate = attempted
                    break
                step /= 2
            if candidate is parameters:
                raise ModelFitError("Poisson solver could not find a stable update.")
            parameters = candidate
            if max(abs(step * value) for value in delta) <= self.config.tolerance:
                converged = True
                break
        if not converged:
            raise ModelFitError(
                f"Poisson solver did not converge within {self.config.max_iterations} iterations."
            )

        training_payload = {
            "schema": {name: str(dtype) for name, dtype in ordered.schema.items()},
            "rows": ordered.to_dicts(),
        }
        training = ModelTrainingMetadata(
            row_count=ordered.height,
            period_start=_as_utc(ordered.get_column("kickoff").min()),
            period_end=_as_utc(ordered.get_column("kickoff").max()),
            training_data_hash=canonical_hash(training_payload),
            iterations=iterations,
            converged=True,
            context=context,
        )
        state_payload = {
            "config": self.config.model_dump(mode="json"),
            "feature_means": means,
            "feature_scales": scales,
            "intercept": parameters[0],
            "coefficients": tuple(parameters[1:]),
            "training": training.model_dump(mode="json"),
        }
        self._state = WRPoissonState(
            **state_payload,
            fingerprint=_state_fingerprint(state_payload),
        )
        return self

    def predict(self, prediction_data: pl.DataFrame) -> tuple[float, ...]:
        state = self.state
        frame = _ordered_prediction_frame(prediction_data, state.config)
        predictions: list[float] = []
        for row in frame.rows():
            standardized = [
                (float(row[index]) - state.feature_means[index])
                / state.feature_scales[index]
                for index in range(len(state.config.feature_names))
            ]
            eta = state.intercept + sum(
                coefficient * value
                for coefficient, value in zip(
                    state.coefficients,
                    standardized,
                    strict=True,
                )
            )
            if not math.isfinite(eta):
                raise ModelFitError("Poisson model produced a non-finite linear predictor.")
            prediction = math.exp(min(eta, state.config.linear_predictor_limit))
            if not math.isfinite(prediction) or prediction < 0:
                raise ModelFitError("Poisson model produced an invalid prediction.")
            predictions.append(prediction)
        return tuple(predictions)

    def predict_one(self, features: Mapping[str, float]) -> float:
        missing = sorted(set(self.config.feature_names) - set(features))
        if missing:
            raise ModelFitError(
                f"prediction_data is missing required columns: {', '.join(missing)}."
            )
        frame = pl.DataFrame(
            {name: [features[name]] for name in self.config.feature_names}
        )
        return self.predict(frame)[0]

    def to_json(self) -> str:
        return self.state.model_dump_json()

    @classmethod
    def from_state(cls, state: WRPoissonState) -> "WRPoissonModel":
        model = cls(state.config)
        model._state = state
        return model

    @classmethod
    def from_json(cls, payload: str) -> "WRPoissonModel":
        return cls.from_state(WRPoissonState.model_validate_json(payload))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _period_boundaries(period: PeriodLike, dtype: pl.DataType) -> tuple[datetime, datetime]:
    start = period.start
    end = period.end
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ModelFitError("Chronological periods must use timezone-aware timestamps.")
    if isinstance(dtype, pl.Datetime) and dtype.time_zone is None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def chronological_model_split(
    feature_table: pl.DataFrame,
    *,
    training_period: PeriodLike,
    evaluation_period: PeriodLike,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return stable, non-overlapping chronological model cohorts."""

    required = ("kickoff", "game_id", "source_player_id")
    missing = sorted(set(required) - set(feature_table.columns))
    if missing:
        raise ModelFitError(
            f"feature_table is missing split columns: {', '.join(missing)}."
        )
    if feature_table.get_column("kickoff").null_count():
        raise ModelFitError("feature_table.kickoff cannot contain nulls.")
    dtype = feature_table.schema["kickoff"]
    training_start, training_end = _period_boundaries(training_period, dtype)
    evaluation_start, evaluation_end = _period_boundaries(evaluation_period, dtype)
    if training_end >= evaluation_start:
        raise ModelFitError("Training period must end before evaluation begins.")
    ordering = ("kickoff", "game_id", "source_player_id")
    training = feature_table.filter(
        (pl.col("kickoff") >= training_start) & (pl.col("kickoff") <= training_end)
    ).sort(*ordering)
    evaluation = feature_table.filter(
        (pl.col("kickoff") >= evaluation_start)
        & (pl.col("kickoff") <= evaluation_end)
    ).sort(*ordering)
    if not training.height:
        raise ModelFitError("Chronological training cohort is empty.")
    if not evaluation.height:
        raise ModelFitError("Chronological evaluation cohort is empty.")
    return training, evaluation
