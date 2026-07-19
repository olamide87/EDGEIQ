from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from app.research.manifest import canonical_hash, sha256_file
from feature_store.registry import MODEL_FEATURE_NAMES, WR_FEATURE_REGISTRY, FeatureRegistry


class FeatureDatasetError(RuntimeError):
    """Raised when a point-in-time feature table cannot be built or validated."""


FEATURE_SCHEMA_VERSION = "wr-player-game-features-v1"
IDENTIFIER_COLUMNS: tuple[str, ...] = (
    "source_player_id",
    "canonical_player_name",
    "game_id",
)
METADATA_COLUMNS: tuple[str, ...] = (
    "season",
    "week",
    "kickoff",
    "raw_player_name",
    "position",
    "team",
    "opponent",
    "is_home",
)
TARGET_COLUMNS: tuple[str, ...] = ("actual_receptions",)
FEATURE_COLUMNS: tuple[str, ...] = MODEL_FEATURE_NAMES
FEATURE_TABLE_COLUMNS: tuple[str, ...] = (
    *IDENTIFIER_COLUMNS,
    *METADATA_COLUMNS,
    *FEATURE_COLUMNS,
    *TARGET_COLUMNS,
)
PRIMARY_KEY: tuple[str, ...] = ("source_player_id", "game_id")


@dataclass(frozen=True)
class FeatureDatasetResult:
    path: Path
    manifest_path: Path
    row_count: int
    content_hash: str
    file_hash: str
    manifest_hash: str


def _required(frame: pl.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise FeatureDatasetError(f"{label} is missing required columns: {', '.join(missing)}.")


def _validate_primary_keys(frame: pl.DataFrame, label: str) -> None:
    for column in PRIMARY_KEY:
        values = frame.get_column(column)
        invalid = values.is_null()
        if values.dtype == pl.String:
            invalid = invalid | (values.str.strip_chars() == "")
        if invalid.any():
            raise FeatureDatasetError(f"{label} contains a null or empty {column}.")
    duplicate = frame.group_by(PRIMARY_KEY).len().filter(pl.col("len") > 1)
    if duplicate.height:
        example = duplicate.select(PRIMARY_KEY).head(1).to_dicts()[0]
        raise FeatureDatasetError(f"{label} contains duplicate player-game rows: {example}.")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mean(values: list[float | None], window: int) -> float | None:
    observed = values[-window:]
    if not observed or any(value is None for value in observed):
        return None
    return sum(value for value in observed if value is not None) / len(observed)


def _ratio(numerators: list[float | None], denominators: list[float | None], window: int) -> float | None:
    pairs = [
        (numerator, denominator)
        for numerator, denominator in zip(numerators[-window:], denominators[-window:], strict=True)
        if numerator is not None and denominator is not None
    ]
    denominator = sum(value for _, value in pairs)
    if not pairs or denominator <= 0:
        return None
    return sum(value for value, _ in pairs) / denominator


def _prepare_player_stats(player_stats: pl.DataFrame) -> tuple[pl.DataFrame, str, str]:
    _required(
        player_stats,
        ("season", "week", "position", "receptions", "targets", "receiving_yards"),
        "player_stats",
    )
    player_column = "player_id" if "player_id" in player_stats.columns else "source_player_id"
    team_column = "team" if "team" in player_stats.columns else "recent_team"
    _required(player_stats, (player_column, team_column), "player_stats")
    stats = player_stats
    if "season_type" in stats.columns:
        stats = stats.filter(pl.col("season_type") == "REG")
    return stats, player_column, team_column


def _optional_value(
    mapping: dict[tuple[str, str], float | None],
    player_id: str,
    game_id: str,
) -> float | None:
    return mapping.get((player_id, game_id))


def _prepare_optional_usage(
    frame: pl.DataFrame | None,
    value_column: str,
    label: str,
) -> dict[tuple[str, str], float | None]:
    if frame is None:
        return {}
    player_column = "source_player_id" if "source_player_id" in frame.columns else "player_id"
    _required(frame, (player_column, "game_id", value_column), label)
    normalized = frame.select(
        pl.col(player_column).cast(pl.String).alias("source_player_id"),
        pl.col("game_id").cast(pl.String),
        pl.col(value_column).cast(pl.Float64, strict=False),
    )
    duplicate = normalized.group_by(PRIMARY_KEY).len().filter(pl.col("len") > 1)
    if duplicate.height:
        raise FeatureDatasetError(f"{label} contains duplicate player-game rows.")
    invalid = normalized.filter(
        pl.col(value_column).is_not_null()
        & ((pl.col(value_column) < 0) | (pl.col(value_column) > 1))
    )
    if invalid.height:
        raise FeatureDatasetError(f"{label}.{value_column} must be between zero and one.")
    return {
        (str(row["source_player_id"]), str(row["game_id"])): _number(row[value_column])
        for row in normalized.iter_rows(named=True)
    }


def _polars_dtype(dtype: str) -> pl.DataType:
    resolved = {
        "Float64": pl.Float64,
        "UInt32": pl.UInt32,
        "Int8": pl.Int8,
        "Int32": pl.Int32,
    }.get(dtype)
    if resolved is None:
        raise FeatureDatasetError(f"Unsupported registered dtype {dtype!r}.")
    return resolved


def _cast_output(frame: pl.DataFrame) -> pl.DataFrame:
    casts: list[pl.Expr] = []
    for feature in WR_FEATURE_REGISTRY.features:
        if not feature.enabled:
            continue
        casts.append(pl.col(feature.name).cast(_polars_dtype(feature.dtype), strict=True))
    return frame.with_columns(casts)


def build_wr_feature_table(
    training_table: pl.DataFrame,
    player_stats: pl.DataFrame,
    *,
    snap_counts: pl.DataFrame | None = None,
    participation: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build pre-kickoff WR features without reading current or future outcomes.

    Player rolling history carries across seasons. Season-to-date, team, and
    opponent histories reset at each season boundary.
    """
    _required(
        training_table,
        (
            *IDENTIFIER_COLUMNS,
            *METADATA_COLUMNS,
            *TARGET_COLUMNS,
        ),
        "training_table",
    )
    training = training_table.select(
        *IDENTIFIER_COLUMNS, *METADATA_COLUMNS, *TARGET_COLUMNS
    ).sort("kickoff", "game_id", "source_player_id")
    _validate_primary_keys(training, "training_table")
    if training.get_column("kickoff").null_count():
        raise FeatureDatasetError("training_table contains a null kickoff.")

    stats, player_column, team_column = _prepare_player_stats(player_stats)
    wr_stats = (
        stats
        .filter(pl.col("position").cast(pl.String).str.to_uppercase() == "WR")
        .select(
            pl.col(player_column).cast(pl.String).alias("source_player_id"),
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col(team_column).cast(pl.String).alias("team"),
            pl.col("receptions").cast(pl.Float64, strict=False),
            pl.col("targets").cast(pl.Float64, strict=False),
            pl.col("receiving_yards").cast(pl.Float64, strict=False),
        )
    )
    duplicate_stats = (
        wr_stats.group_by("source_player_id", "season", "week", "team")
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicate_stats.height:
        raise FeatureDatasetError("player_stats contains duplicate WR player-week-team rows.")
    invalid_stats = wr_stats.filter(
        pl.any_horizontal(
            pl.col("receptions").is_null() | (pl.col("receptions") < 0),
            pl.col("targets").is_null() | (pl.col("targets") < 0),
            pl.col("receiving_yards").is_null() | (pl.col("receiving_yards") < 0),
            pl.col("receptions") > pl.col("targets"),
        )
    )
    if invalid_stats.height:
        raise FeatureDatasetError(
            "WR receptions, targets, and receiving yards must be non-negative, "
            "and receptions cannot exceed targets."
        )

    joined = training.join(
        wr_stats,
        on=["source_player_id", "season", "week", "team"],
        how="left",
        validate="1:1",
    )
    if joined.get_column("targets").null_count():
        example = (
            joined.filter(pl.col("targets").is_null())
            .select("source_player_id", "season", "week", "team")
            .head(1)
            .to_dicts()[0]
        )
        raise FeatureDatasetError(f"player_stats join failed for training row: {example}.")

    schedule_map = (
        training.select("season", "week", "game_id", "kickoff", "team", "opponent")
        .unique()
    )
    if schedule_map.group_by("season", "week", "team").len().filter(pl.col("len") > 1).height:
        raise FeatureDatasetError("training_table has ambiguous team-week schedule mappings.")

    numeric_columns = [column for column in ("attempts", "completions") if column in stats.columns]
    team_parts = stats.select(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col(team_column).cast(pl.String).alias("team"),
        pl.col("position").cast(pl.String).str.to_uppercase().alias("position"),
        pl.col("targets").cast(pl.Float64, strict=False).fill_null(0).alias("targets"),
        *[pl.col(column).cast(pl.Float64, strict=False).fill_null(0) for column in numeric_columns],
    )
    aggregations: list[pl.Expr] = [
        pl.col("targets").filter(pl.col("position") == "WR").sum().alias("wr_targets"),
        pl.col("targets").filter(pl.col("position") == "WR").max().alias("max_wr_targets"),
    ]
    for column in numeric_columns:
        aggregations.append(pl.col(column).sum().alias(column))
    team_game = (
        team_parts.group_by("season", "week", "team").agg(aggregations)
        .join(schedule_map, on=["season", "week", "team"], how="inner", validate="1:1")
        .with_columns(
            pl.when(pl.col("wr_targets") > 0)
            .then(pl.col("max_wr_targets") / pl.col("wr_targets"))
            .otherwise(None)
            .alias("team_target_concentration"),
        )
        .sort("kickoff", "game_id", "team")
    )
    if "attempts" not in team_game.columns:
        team_game = team_game.with_columns(pl.lit(None, dtype=pl.Float64).alias("attempts"))
    if "completions" not in team_game.columns:
        team_game = team_game.with_columns(pl.lit(None, dtype=pl.Float64).alias("completions"))
    team_game = team_game.with_columns(
        pl.when(pl.col("attempts") > 0)
        .then(pl.col("completions") / pl.col("attempts"))
        .otherwise(None)
        .alias("team_completion_rate")
    )
    team_context = {
        (int(row["season"]), str(row["game_id"]), str(row["team"])): row
        for row in team_game.iter_rows(named=True)
    }
    joined = joined.sort("kickoff", "game_id", "source_player_id")

    snap_values = _prepare_optional_usage(snap_counts, "snap_share", "snap_counts")
    route_values = _prepare_optional_usage(
        participation, "route_participation", "participation"
    )
    player_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    season_player_history: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    team_history: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    defense_history: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    output_rows: list[dict[str, Any]] = []

    games = joined.partition_by("game_id", maintain_order=True)
    for game_rows in games:
        game_id = str(game_rows.get_column("game_id")[0])
        season = int(game_rows.get_column("season")[0])
        event_player_updates: list[tuple[str, dict[str, Any]]] = []
        event_team_keys: set[tuple[int, str, str]] = set()

        for row in game_rows.iter_rows(named=True):
            player_id = str(row["source_player_id"])
            history = player_history[player_id]
            season_history = season_player_history[(player_id, season)]
            receptions = [item["receptions"] for item in history]
            targets = [item["targets"] for item in history]
            yards = [item["receiving_yards"] for item in history]
            shares = [item["target_share"] for item in history]
            snaps = [item["snap_share"] for item in history]
            routes = [item["route_participation"] for item in history]

            context_key = (season, game_id, str(row["team"]))
            context = team_context.get(context_key)
            team_prior = team_history[(season, str(row["team"]))]
            opponent_prior = defense_history[(season, str(row["opponent"]))]
            prior_kickoff = history[-1]["kickoff"] if history else None
            rest_days = (
                (row["kickoff"] - prior_kickoff).total_seconds() / 86_400
                if prior_kickoff is not None
                else None
            )
            features: dict[str, Any] = {
                "receptions_lag1": receptions[-1] if receptions else None,
                "targets_lag1": targets[-1] if targets else None,
                "receiving_yards_lag1": yards[-1] if yards else None,
                "receptions_season_mean": _mean(
                    [item["receptions"] for item in season_history], len(season_history)
                ) if season_history else None,
                "targets_season_mean": _mean(
                    [item["targets"] for item in season_history], len(season_history)
                ) if season_history else None,
                "receiving_yards_season_mean": _mean(
                    [item["receiving_yards"] for item in season_history], len(season_history)
                ) if season_history else None,
                "games_played_before": len(history),
                "snap_share_lag1": snaps[-1] if snaps else None,
                "route_participation_lag1": routes[-1] if routes else None,
                "home_indicator": int(row["is_home"]),
                "rest_days": rest_days,
                "game_week": int(row["week"]),
                "season_year": season,
                "has_prior_history": int(bool(history)),
            }
            for window in (3, 5, 8):
                features[f"receptions_roll{window}"] = _mean(receptions, window)
                features[f"targets_roll{window}"] = _mean(targets, window)
                features[f"receiving_yards_roll{window}"] = _mean(yards, window)
                features[f"catch_rate_roll{window}"] = _ratio(receptions, targets, window)
                features[f"target_share_roll{window}"] = _mean(shares, window)
            for window in (3, 5):
                features[f"snap_share_roll{window}"] = _mean(snaps, window)
                features[f"route_participation_roll{window}"] = _mean(routes, window)
                features[f"team_pass_attempts_roll{window}"] = _mean(
                    [item["attempts"] for item in team_prior], window
                )
                features[f"team_completions_roll{window}"] = _mean(
                    [item["completions"] for item in team_prior], window
                )
                features[f"team_completion_rate_roll{window}"] = _mean(
                    [item["team_completion_rate"] for item in team_prior], window
                )
                features[f"team_target_concentration_roll{window}"] = _mean(
                    [item["team_target_concentration"] for item in team_prior], window
                )
                for metric in (
                    "pass_attempts_allowed",
                    "completions_allowed",
                    "wr_receptions_allowed",
                    "wr_targets_allowed",
                ):
                    features[f"opponent_{metric}_roll{window}"] = _mean(
                        [item[metric] for item in opponent_prior], window
                    )
            features["snap_share_missing"] = int(features["snap_share_lag1"] is None)
            features["route_participation_missing"] = int(
                features["route_participation_lag1"] is None
            )
            output_rows.append({
                **{column: row[column] for column in IDENTIFIER_COLUMNS},
                **{column: row[column] for column in METADATA_COLUMNS},
                **features,
                "actual_receptions": row["actual_receptions"],
            })

            attempts = _number(context["attempts"]) if context else None
            target_share = (
                _number(row["targets"]) / attempts
                if attempts is not None and attempts > 0
                else None
            )
            event_player_updates.append((player_id, {
                "season": season,
                "kickoff": row["kickoff"],
                "receptions": _number(row["receptions"]),
                "targets": _number(row["targets"]),
                "receiving_yards": _number(row["receiving_yards"]),
                "target_share": target_share,
                "snap_share": _optional_value(snap_values, player_id, game_id),
                "route_participation": _optional_value(route_values, player_id, game_id),
            }))
            event_team_keys.add(context_key)

        # Update histories only after every prediction row in the game is materialized.
        for player_id, update in event_player_updates:
            player_history[player_id].append(update)
            season_player_history[(player_id, season)].append(update)
        for context_key in sorted(event_team_keys):
            context = team_context.get(context_key)
            if context is None:
                continue
            team = str(context["team"])
            opponent = str(context["opponent"])
            offense_update = {
                "attempts": _number(context["attempts"]),
                "completions": _number(context["completions"]),
                "team_completion_rate": _number(context["team_completion_rate"]),
                "team_target_concentration": _number(context["team_target_concentration"]),
            }
            team_history[(season, team)].append(offense_update)
            wr_game = game_rows.filter(pl.col("team") == team)
            defense_history[(season, opponent)].append({
                "pass_attempts_allowed": offense_update["attempts"],
                "completions_allowed": offense_update["completions"],
                "wr_receptions_allowed": float(wr_game.get_column("receptions").sum())
                if wr_game.height else None,
                "wr_targets_allowed": float(wr_game.get_column("targets").sum())
                if wr_game.height else None,
            })

    output = pl.DataFrame(output_rows).select(FEATURE_TABLE_COLUMNS)
    output = _cast_output(output).sort("kickoff", "game_id", "source_player_id")
    validate_wr_feature_table(output)
    return output


def validate_wr_feature_table(
    frame: pl.DataFrame,
    *,
    registry: FeatureRegistry = WR_FEATURE_REGISTRY,
) -> None:
    _required(frame, FEATURE_TABLE_COLUMNS, "feature_table")
    if tuple(frame.columns) != FEATURE_TABLE_COLUMNS:
        extra = sorted(set(frame.columns) - set(FEATURE_TABLE_COLUMNS))
        missing = sorted(set(FEATURE_TABLE_COLUMNS) - set(frame.columns))
        raise FeatureDatasetError(
            "feature_table columns must exactly match the canonical identifier, metadata, "
            f"feature, and target order; extra={extra}, missing={missing}."
        )
    _validate_primary_keys(frame, "feature_table")
    if frame.get_column("kickoff").null_count():
        raise FeatureDatasetError("feature_table contains null kickoff values.")
    if tuple(FEATURE_COLUMNS) != registry.enabled_names:
        raise FeatureDatasetError("Feature table columns do not match the enabled registry.")
    for feature_name in FEATURE_COLUMNS:
        feature = registry.by_name(feature_name)
        expected_dtype = _polars_dtype(feature.dtype)
        actual_dtype = frame.schema[feature_name]
        if actual_dtype != expected_dtype:
            raise FeatureDatasetError(
                f"feature_table.{feature_name} has dtype {actual_dtype}; "
                f"registry requires {expected_dtype}."
            )
    if frame.sort("kickoff", "game_id", "source_player_id").to_dicts() != frame.to_dicts():
        raise FeatureDatasetError("feature_table is not in canonical chronological order.")


def canonical_feature_content_hash(frame: pl.DataFrame) -> str:
    validate_wr_feature_table(frame)
    canonical = frame.select(FEATURE_TABLE_COLUMNS).sort(
        "kickoff", "game_id", "source_player_id"
    )
    return canonical_hash({
        "schema": {name: str(dtype) for name, dtype in canonical.schema.items()},
        "rows": canonical.to_dicts(),
    })


def write_wr_feature_dataset(
    frame: pl.DataFrame,
    *,
    output_path: Path,
    source_manifest_hashes: dict[str, str],
    registry: FeatureRegistry = WR_FEATURE_REGISTRY,
) -> FeatureDatasetResult:
    validate_wr_feature_table(frame, registry=registry)
    canonical = frame.select(FEATURE_TABLE_COLUMNS).sort(
        "kickoff", "game_id", "source_player_id"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        canonical.write_parquet(temporary_path)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    file_hash = sha256_file(output_path)
    content_hash = canonical_feature_content_hash(canonical)
    payload = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "registry_version": registry.version,
        "registry_hash": registry.registry_hash,
        "source_manifest_hashes": dict(sorted(source_manifest_hashes.items())),
        "row_count": canonical.height,
        "seasons": sorted(canonical.get_column("season").unique().to_list()),
        "identifier_columns": list(IDENTIFIER_COLUMNS),
        "metadata_columns": list(METADATA_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "target_columns": list(TARGET_COLUMNS),
        "content_sha256": content_hash,
        "file_sha256": file_hash,
    }
    manifest_hash = canonical_hash(payload)
    manifest = {
        **payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_hash": manifest_hash,
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_manifest.replace(manifest_path)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    return FeatureDatasetResult(
        path=output_path,
        manifest_path=manifest_path,
        row_count=canonical.height,
        content_hash=content_hash,
        file_hash=file_hash,
        manifest_hash=manifest_hash,
    )


def load_and_validate_wr_feature_dataset(path: Path) -> dict[str, Any]:
    try:
        frame = pl.read_parquet(path)
    except Exception as exc:
        raise FeatureDatasetError(f"Cannot read feature table {path}: {exc}") from exc
    validate_wr_feature_table(frame)
    manifest_path = path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        raise FeatureDatasetError(f"Feature manifest does not exist: {manifest_path}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded_manifest_hash = manifest.pop("manifest_hash", "")
    manifest.pop("created_at", None)
    expected_manifest_hash = canonical_hash(manifest)
    if recorded_manifest_hash != expected_manifest_hash:
        raise FeatureDatasetError("Feature manifest hash does not match its contents.")
    if manifest.get("content_sha256") != canonical_feature_content_hash(frame):
        raise FeatureDatasetError("Feature table canonical content hash does not match its manifest.")
    if manifest.get("file_sha256") != sha256_file(path):
        raise FeatureDatasetError("Feature table file hash does not match its manifest.")
    if manifest.get("registry_hash") != WR_FEATURE_REGISTRY.registry_hash:
        raise FeatureDatasetError("Feature table was built with a different feature registry.")
    return {
        "rows": frame.height,
        "features": len(FEATURE_COLUMNS),
        "content_hash": manifest["content_sha256"],
        "file_hash": manifest["file_sha256"],
        "manifest_hash": recorded_manifest_hash,
        "registry_version": manifest["registry_version"],
    }
