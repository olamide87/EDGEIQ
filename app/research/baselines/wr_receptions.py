"""Deterministic point-in-time baselines for WR receptions."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field


class BaselineDatasetError(ValueError):
    """Raised when baseline input cannot be evaluated safely."""


class BaselineName(StrEnum):
    """Stable baseline identities used in scorecards and registries."""

    LEAGUE_MEAN = "league_mean"
    PREVIOUS_GAME = "previous_game"
    ROLLING_3 = "rolling_3"
    ROLLING_5 = "rolling_5"
    SEASON_TO_DATE = "season_to_date"
    CAREER_AVERAGE = "career_average"
    POISSON = "poisson"


class BaselineSpec(BaseModel):
    """Immutable definition of one deterministic baseline."""

    model_config = ConfigDict(frozen=True)

    name: BaselineName
    level: str = Field(pattern=r"^L\d+$")
    implementation_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    distribution: str
    minimum_history: int = Field(ge=1)
    description: str = Field(min_length=1)


BASELINE_SPECS: tuple[BaselineSpec, ...] = (
    BaselineSpec(
        name=BaselineName.LEAGUE_MEAN,
        level="L0",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Mean receptions across all completed prior WR player-games.",
    ),
    BaselineSpec(
        name=BaselineName.PREVIOUS_GAME,
        level="L1",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Receptions in the player's previous completed game.",
    ),
    BaselineSpec(
        name=BaselineName.ROLLING_3,
        level="L2",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Mean receptions over up to three prior player-games.",
    ),
    BaselineSpec(
        name=BaselineName.ROLLING_5,
        level="L3",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Mean receptions over up to five prior player-games.",
    ),
    BaselineSpec(
        name=BaselineName.SEASON_TO_DATE,
        level="L4",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Mean receptions in the current season before kickoff.",
    ),
    BaselineSpec(
        name=BaselineName.CAREER_AVERAGE,
        level="L4",
        implementation_version="1.0.0",
        distribution="point",
        minimum_history=1,
        description="Mean receptions across the player's completed prior games.",
    ),
    BaselineSpec(
        name=BaselineName.POISSON,
        level="L5",
        implementation_version="1.0.0",
        distribution="poisson",
        minimum_history=1,
        description=(
            "Poisson rate from season-to-date mean, then rolling five, career, "
            "and league history as deterministic fallbacks."
        ),
    ),
)

_SPEC_BY_NAME = {spec.name: spec for spec in BASELINE_SPECS}
_REQUIRED_COLUMNS = (
    "source_player_id",
    "game_id",
    "season",
    "kickoff",
    "actual_receptions",
    "receptions_lag1",
    "receptions_roll3",
    "receptions_roll5",
    "receptions_season_mean",
)
_FEATURE_COLUMNS = (
    "receptions_lag1",
    "receptions_roll3",
    "receptions_roll5",
    "receptions_season_mean",
)


def _validate_input(frame: pl.DataFrame) -> pl.DataFrame:
    missing = sorted(set(_REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise BaselineDatasetError(
            f"feature_table is missing required columns: {', '.join(missing)}."
        )
    selected = frame.select(_REQUIRED_COLUMNS).sort(
        "kickoff", "game_id", "source_player_id"
    )
    for column in ("source_player_id", "game_id"):
        if selected.filter(
            pl.col(column).is_null()
            | (pl.col(column).cast(pl.String).str.strip_chars() == "")
        ).height:
            raise BaselineDatasetError(f"feature_table contains a null or empty {column}.")
    if selected.get_column("kickoff").null_count():
        raise BaselineDatasetError("feature_table contains a null kickoff.")
    duplicate = (
        selected.group_by("source_player_id", "game_id")
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicate.height:
        raise BaselineDatasetError("feature_table contains duplicate player-game rows.")

    numeric_columns = ("actual_receptions", *_FEATURE_COLUMNS)
    for column in numeric_columns:
        normalized = selected.with_columns(
            pl.col(column).cast(pl.Float64, strict=False).alias("__numeric")
        )
        invalid = normalized.filter(
            pl.col(column).is_not_null()
            & (pl.col("__numeric").is_null() | ~pl.col("__numeric").is_finite())
        )
        if invalid.height:
            raise BaselineDatasetError(
                f"feature_table.{column} must contain finite numeric values or null."
            )
        if normalized.filter(pl.col("__numeric") < 0).height:
            raise BaselineDatasetError(
                f"feature_table.{column} cannot contain negative values."
            )
        selected = normalized.with_columns(pl.col("__numeric").alias(column)).drop(
            "__numeric"
        )
    if selected.get_column("actual_receptions").null_count():
        raise BaselineDatasetError("feature_table.actual_receptions cannot be null.")
    return selected


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _prediction_row(
    row: dict[str, Any],
    *,
    spec: BaselineSpec,
    prediction: float | None,
    history_count: int,
) -> dict[str, Any]:
    eligible = prediction is not None and history_count >= spec.minimum_history
    return {
        "source_player_id": str(row["source_player_id"]),
        "game_id": str(row["game_id"]),
        "season": int(row["season"]),
        "kickoff": row["kickoff"],
        "actual_receptions": float(row["actual_receptions"]),
        "baseline": spec.name.value,
        "baseline_level": spec.level,
        "implementation_version": spec.implementation_version,
        "distribution": spec.distribution,
        "prediction": float(prediction) if eligible else None,
        "history_count": history_count,
        "eligible": eligible,
        "exclusion_reason": None if eligible else "insufficient_history",
    }


def build_wr_baseline_predictions(
    feature_table: pl.DataFrame,
    *,
    baselines: tuple[BaselineName, ...] = tuple(BaselineName),
) -> pl.DataFrame:
    """Build long-form predictions without observing the current game's outcome.

    Every row for a game is predicted before any outcome from that game updates
    league or player history. Input order therefore cannot create teammate or
    opponent leakage.
    """

    if not baselines:
        raise BaselineDatasetError("At least one baseline must be requested.")
    if len(baselines) != len(set(baselines)):
        raise BaselineDatasetError("Requested baseline names must be unique.")

    frame = _validate_input(feature_table)
    player_history: dict[str, list[float]] = defaultdict(list)
    league_history: list[float] = []
    output: list[dict[str, Any]] = []

    for game in frame.partition_by("game_id", maintain_order=True):
        pending_updates: list[tuple[str, float]] = []
        league_mean = _mean(league_history)
        league_count = len(league_history)

        for row in game.iter_rows(named=True):
            player_id = str(row["source_player_id"])
            career = player_history[player_id]
            career_mean = _mean(career)
            feature_values = {
                BaselineName.PREVIOUS_GAME: row["receptions_lag1"],
                BaselineName.ROLLING_3: row["receptions_roll3"],
                BaselineName.ROLLING_5: row["receptions_roll5"],
                BaselineName.SEASON_TO_DATE: row["receptions_season_mean"],
            }
            poisson_rate = next(
                (
                    float(value)
                    for value in (
                        row["receptions_season_mean"],
                        row["receptions_roll5"],
                        career_mean,
                        league_mean,
                    )
                    if value is not None
                ),
                None,
            )

            for name in baselines:
                spec = _SPEC_BY_NAME[name]
                if name is BaselineName.LEAGUE_MEAN:
                    prediction, history_count = league_mean, league_count
                elif name is BaselineName.CAREER_AVERAGE:
                    prediction, history_count = career_mean, len(career)
                elif name is BaselineName.POISSON:
                    prediction = poisson_rate
                    history_count = max(
                        len(career),
                        1 if row["receptions_season_mean"] is not None else 0,
                        1 if row["receptions_roll5"] is not None else 0,
                        league_count,
                    )
                else:
                    prediction = feature_values[name]
                    history_count = len(career)
                output.append(
                    _prediction_row(
                        row,
                        spec=spec,
                        prediction=prediction,
                        history_count=history_count,
                    )
                )
            pending_updates.append((player_id, float(row["actual_receptions"])))

        for player_id, actual in pending_updates:
            player_history[player_id].append(actual)
            league_history.append(actual)

    if not output:
        return pl.DataFrame(
            schema={
                "source_player_id": pl.String,
                "game_id": pl.String,
                "season": pl.Int32,
                "kickoff": frame.schema["kickoff"],
                "actual_receptions": pl.Float64,
                "baseline": pl.String,
                "baseline_level": pl.String,
                "implementation_version": pl.String,
                "distribution": pl.String,
                "prediction": pl.Float64,
                "history_count": pl.UInt32,
                "eligible": pl.Boolean,
                "exclusion_reason": pl.String,
            }
        )
    result = pl.DataFrame(output).with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("actual_receptions").cast(pl.Float64),
        pl.col("prediction").cast(pl.Float64),
        pl.col("history_count").cast(pl.UInt32),
    )
    return result.sort("kickoff", "game_id", "source_player_id", "baseline")
