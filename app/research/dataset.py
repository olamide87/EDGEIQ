from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import polars as pl

from app.research.manifest import canonical_hash, sha256_file
from app.services.player_aliases import normalize_player_name


class TrainingDatasetError(RuntimeError):
    pass


TRAINING_SCHEMA_VERSION = "wr-player-game-v1"
TRAINING_COLUMNS: tuple[str, ...] = (
    "season", "week", "game_id", "kickoff", "source_player_id",
    "raw_player_name", "canonical_player_name", "position", "team", "opponent",
    "is_home", "actual_receptions",
)


@dataclass(frozen=True)
class TrainingDatasetResult:
    path: Path
    manifest_path: Path
    row_count: int
    dataset_hash: str
    file_hash: str
    manifest_hash: str


def _kickoff_expression() -> pl.Expr:
    return (
        pl.concat_str(
            [pl.col("gameday").cast(pl.String), pl.lit(" "), pl.col("gametime").fill_null("00:00").cast(pl.String)]
        )
        .str.to_datetime(strict=False)
        .alias("kickoff")
    )


def build_wr_training_table(
    player_stats: pl.DataFrame,
    schedules: pl.DataFrame,
) -> pl.DataFrame:
    required_stats = {
        "season", "week", "player_id", "player_display_name", "position",
        "receptions",
    }
    required_schedules = {"season", "week", "game_id", "gameday", "home_team", "away_team"}
    missing_stats = sorted(required_stats - set(player_stats.columns))
    missing_schedules = sorted(required_schedules - set(schedules.columns))
    team_column = "team" if "team" in player_stats.columns else "recent_team"
    if team_column not in player_stats.columns:
        missing_stats.append("team or recent_team")
    if missing_stats or missing_schedules:
        raise TrainingDatasetError(
            f"Cannot build WR table; missing player_stats={missing_stats}, schedules={missing_schedules}."
        )

    stats = player_stats.filter(pl.col("position").cast(pl.String).str.to_uppercase() == "WR")
    if "season_type" in stats.columns:
        stats = stats.filter(pl.col("season_type") == "REG")
    invalid_identity = stats.filter(
        pl.col("player_id").is_null()
        | (pl.col("player_id").cast(pl.String).str.strip_chars() == "")
        | pl.col("player_display_name").is_null()
        | (pl.col("player_display_name").cast(pl.String).str.strip_chars() == "")
    )
    if invalid_identity.height:
        raise TrainingDatasetError("WR rows must contain non-empty source player IDs and names.")
    if stats.filter(pl.col(team_column).is_null()).height:
        raise TrainingDatasetError("WR rows must contain a team identifier.")
    if stats.filter(pl.col("receptions").is_null() | (pl.col("receptions") < 0)).height:
        raise TrainingDatasetError("WR rows must contain non-negative actual receptions.")

    stats = stats.with_columns(
        pl.col(team_column).alias("team"),
        pl.col("player_id").cast(pl.String).alias("source_player_id"),
        pl.col("player_display_name").alias("raw_player_name"),
        pl.col("player_display_name").map_elements(
            normalize_player_name, return_dtype=pl.String
        ).alias("canonical_player_name"),
        pl.col("receptions").cast(pl.Int64).alias("actual_receptions"),
    )

    schedule = schedules
    if "game_type" in schedule.columns:
        schedule = schedule.filter(pl.col("game_type") == "REG")
    if "gametime" not in schedule.columns:
        schedule = schedule.with_columns(pl.lit("00:00").alias("gametime"))
    home = schedule.select(
        "season", "week", "game_id", _kickoff_expression(),
        pl.col("home_team").alias("team"), pl.col("away_team").alias("opponent"),
        pl.lit(1, dtype=pl.Int8).alias("is_home"),
    )
    away = schedule.select(
        "season", "week", "game_id", _kickoff_expression(),
        pl.col("away_team").alias("team"), pl.col("home_team").alias("opponent"),
        pl.lit(0, dtype=pl.Int8).alias("is_home"),
    )
    team_schedule = pl.concat([home, away])
    ambiguous_schedule = team_schedule.group_by("season", "week", "team").len().filter(
        pl.col("len") > 1
    )
    if ambiguous_schedule.height:
        raise TrainingDatasetError("Schedule contains multiple games for the same team and week.")
    result = stats.join(team_schedule, on=["season", "week", "team"], how="left")
    if result.get_column("game_id").null_count():
        examples = result.filter(pl.col("game_id").is_null()).select("season", "week", "team").head(5)
        raise TrainingDatasetError(f"Schedule join failed for WR rows: {examples.to_dicts()}.")
    duplicate_keys = result.group_by("source_player_id", "game_id").len().filter(pl.col("len") > 1)
    if duplicate_keys.height:
        raise TrainingDatasetError("Duplicate player-game rows found after schedule normalization.")
    return result.select(TRAINING_COLUMNS).sort("kickoff", "game_id", "source_player_id")


def write_training_dataset(
    frame: pl.DataFrame,
    *,
    output_path: Path,
    source_manifest_hash: str,
) -> TrainingDatasetResult:
    missing = sorted(set(TRAINING_COLUMNS) - set(frame.columns))
    if missing:
        raise TrainingDatasetError(f"Cannot write WR dataset; missing columns: {', '.join(missing)}.")
    frame = frame.select(TRAINING_COLUMNS).sort("kickoff", "game_id", "source_player_id")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(output_path)
    dataset_hash = sha256_file(output_path)
    stable_content_hash = canonical_hash({
        "schema": {name: str(dtype) for name, dtype in frame.schema.items()},
        "rows": frame.to_dicts(),
    })
    manifest_payload = {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "source_manifest_hash": source_manifest_hash,
        "row_count": frame.height,
        "seasons": sorted(frame.get_column("season").unique().to_list()),
        "columns": list(TRAINING_COLUMNS),
        "file_sha256": dataset_hash,
        "content_sha256": stable_content_hash,
        "target": "actual_receptions",
        "predictor_columns": [],
    }
    manifest_hash = canonical_hash(manifest_payload)
    manifest = {
        **manifest_payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_hash": manifest_hash,
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return TrainingDatasetResult(
        output_path, manifest_path, frame.height, stable_content_hash, dataset_hash, manifest_hash
    )
