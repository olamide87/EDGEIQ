from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
import json

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class FeatureTiming(StrEnum):
    PREGAME = "pregame"
    LAGGED = "lagged"


class LeakageRisk(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class MissingValuePolicy(StrEnum):
    LEAVE_NULL = "leave_null"
    FILL_ZERO = "fill_zero"
    FORWARD_FILL = "forward_fill"
    POSITION_FALLBACK = "position_fallback"
    NOT_AVAILABLE = "not_available"


class EntityGrain(StrEnum):
    PLAYER_GAME = "player_game"
    TEAM_GAME = "team_game"
    OPPONENT_GAME = "opponent_game"


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_dataset: str = Field(
        min_length=1, validation_alias=AliasChoices("source_dataset", "source")
    )
    source_columns: tuple[str, ...]
    transformation: str = Field(min_length=1)
    entity_grain: EntityGrain
    lookback_games: int = Field(ge=0)
    minimum_history: int = Field(ge=0)
    availability_timing: FeatureTiming = Field(
        validation_alias=AliasChoices("availability_timing", "timing")
    )
    availability_timestamp: str = Field(min_length=1)
    missing_value_policy: MissingValuePolicy
    leakage_risk: LeakageRisk
    enabled: bool = Field(validation_alias=AliasChoices("enabled", "retained"))
    dtype: str = Field(min_length=1)
    version: str = Field(min_length=1)
    carry_across_seasons: bool = False

    @model_validator(mode="after")
    def validate_safety(self) -> "FeatureDefinition":
        if self.enabled and self.leakage_risk is LeakageRisk.HIGH:
            raise ValueError("High-leakage features cannot be enabled.")
        if self.enabled and self.missing_value_policy is MissingValuePolicy.NOT_AVAILABLE:
            raise ValueError("Unavailable features cannot be enabled.")
        if self.availability_timing is FeatureTiming.LAGGED and self.lookback_games < 1:
            raise ValueError("Lagged features require a lookback of at least one game.")
        return self

    # Compatibility aliases retained for the original v0.5A registry API.
    @property
    def source(self) -> str:
        return self.source_dataset

    @property
    def timing(self) -> FeatureTiming:
        return self.availability_timing

    @property
    def retained(self) -> bool:
        return self.enabled


class FeatureRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "wr_receptions"
    version: str = "wr-receptions-features-v1"
    features: tuple[FeatureDefinition, ...]

    @model_validator(mode="after")
    def validate_unique_names(self) -> "FeatureRegistry":
        names = [feature.name for feature in self.features]
        if len(names) != len(set(names)):
            raise ValueError("Feature names must be unique.")
        return self

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return tuple(feature.name for feature in self.features if feature.enabled)

    @property
    def registry_hash(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    def by_name(self, name: str) -> FeatureDefinition:
        for feature in self.features:
            if feature.name == name:
                return feature
        raise KeyError(name)


def _feature(
    name: str,
    description: str,
    source_dataset: str,
    source_columns: tuple[str, ...],
    transformation: str,
    *,
    grain: EntityGrain = EntityGrain.PLAYER_GAME,
    lookback: int = 1,
    minimum_history: int = 1,
    timing: FeatureTiming = FeatureTiming.LAGGED,
    missing: MissingValuePolicy = MissingValuePolicy.LEAVE_NULL,
    risk: LeakageRisk = LeakageRisk.NONE,
    enabled: bool = True,
    dtype: str = "Float64",
    carry_across_seasons: bool = True,
) -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        description=description,
        source_dataset=source_dataset,
        source_columns=source_columns,
        transformation=transformation,
        entity_grain=grain,
        lookback_games=lookback,
        minimum_history=minimum_history,
        availability_timing=timing,
        availability_timestamp=(
            "after_prior_game_final_and_before_current_kickoff"
            if timing is FeatureTiming.LAGGED
            else "before_current_kickoff"
        ),
        missing_value_policy=missing,
        leakage_risk=risk,
        enabled=enabled,
        dtype=dtype,
        version="1.0",
        carry_across_seasons=carry_across_seasons,
    )


def _rolling_history_features() -> list[FeatureDefinition]:
    result: list[FeatureDefinition] = []
    for source, prefix in (
        ("receptions", "receptions"),
        ("targets", "targets"),
        ("receiving_yards", "receiving_yards"),
    ):
        result.append(_feature(
            f"{prefix}_lag1", f"{source.replace('_', ' ').title()} in the prior completed game.",
            "player_stats", (source,), f"shift({source}, 1) by source_player_id",
        ))
        for window in (3, 5, 8):
            result.append(_feature(
                f"{prefix}_roll{window}",
                f"Mean {source.replace('_', ' ')} over up to {window} prior completed games.",
                "player_stats", (source,),
                f"rolling_mean(shift({source}, 1), window={window}, min_history=1)",
                lookback=window,
            ))
    for window in (3, 5, 8):
        result.extend((
            _feature(
                f"catch_rate_roll{window}",
                f"Receptions divided by targets over up to {window} prior completed games.",
                "player_stats", ("receptions", "targets"),
                f"rolling_sum(shift(receptions, 1), {window}) / "
                f"rolling_sum(shift(targets, 1), {window})",
                lookback=window,
            ),
            _feature(
                f"target_share_roll{window}",
                f"Mean player targets divided by team pass attempts over up to {window} prior games.",
                "player_stats", ("targets", "attempts"),
                f"rolling_mean(shift(targets / team_pass_attempts, 1), window={window})",
                lookback=window,
            ),
        ))
    return result


def _context_features() -> list[FeatureDefinition]:
    features: list[FeatureDefinition] = []
    for metric, label, source_columns in (
        ("team_pass_attempts", "team pass attempts", ("attempts",)),
        ("team_completions", "team completions", ("completions",)),
        ("team_completion_rate", "team completion rate", ("completions", "attempts")),
        ("team_target_concentration", "team WR target concentration", ("targets",)),
    ):
        for window in (3, 5):
            features.append(_feature(
                f"{metric}_roll{window}",
                f"Mean {label} over prior games in the same season.",
                "player_stats", source_columns,
                f"team rolling_mean(shift({metric}, 1), window={window})",
                grain=EntityGrain.TEAM_GAME,
                lookback=window,
                carry_across_seasons=False,
            ))
    for metric, label in (
        ("opponent_pass_attempts_allowed", "opponent pass attempts allowed"),
        ("opponent_completions_allowed", "opponent completions allowed"),
        ("opponent_wr_receptions_allowed", "opponent WR receptions allowed"),
        ("opponent_wr_targets_allowed", "opponent WR targets allowed"),
    ):
        for window in (3, 5):
            features.append(_feature(
                f"{metric}_roll{window}",
                f"Mean {label} over the opponent's prior games in the same season.",
                "player_stats", ("attempts", "completions", "receptions", "targets"),
                f"defense rolling_mean(shift({metric}, 1), window={window})",
                grain=EntityGrain.OPPONENT_GAME,
                lookback=window,
                carry_across_seasons=False,
            ))
    return features


FEATURE_REGISTRY: tuple[FeatureDefinition, ...] = tuple([
    *_rolling_history_features(),
    _feature(
        "receptions_season_mean", "Mean receptions before kickoff in the current season.",
        "player_stats", ("receptions",), "expanding_mean(shift(receptions, 1)) by player and season",
        lookback=1, carry_across_seasons=False,
    ),
    _feature(
        "targets_season_mean", "Mean targets before kickoff in the current season.",
        "player_stats", ("targets",), "expanding_mean(shift(targets, 1)) by player and season",
        lookback=1, carry_across_seasons=False,
    ),
    _feature(
        "receiving_yards_season_mean", "Mean receiving yards before kickoff in the current season.",
        "player_stats", ("receiving_yards",),
        "expanding_mean(shift(receiving_yards, 1)) by player and season",
        lookback=1, carry_across_seasons=False,
    ),
    _feature(
        "games_played_before", "Completed player games available before kickoff.",
        "wr_player_game", ("game_id",), "cumulative prior non-null game count",
        dtype="UInt32", missing=MissingValuePolicy.FILL_ZERO,
    ),
    _feature(
        "snap_share_lag1", "Offensive snap share in the prior completed game when identity mapping exists.",
        "snap_counts", ("source_player_id", "game_id", "snap_share"),
        "shift(snap_share, 1) by source_player_id",
    ),
    _feature(
        "snap_share_roll3", "Mean offensive snap share over up to three prior completed games.",
        "snap_counts", ("source_player_id", "game_id", "snap_share"),
        "rolling_mean(shift(snap_share, 1), window=3)", lookback=3,
    ),
    _feature(
        "snap_share_roll5", "Mean offensive snap share over up to five prior completed games.",
        "snap_counts", ("source_player_id", "game_id", "snap_share"),
        "rolling_mean(shift(snap_share, 1), window=5)", lookback=5,
    ),
    _feature(
        "snap_share_missing", "One when prior snap-share history is unavailable.",
        "snap_counts", ("snap_share",), "is_null(snap_share_lag1)",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int8",
    ),
    _feature(
        "route_participation_lag1",
        "Prior-game route participation proxy from a pre-aggregated, source-ID keyed input.",
        "participation", ("source_player_id", "game_id", "route_participation"),
        "shift(route_participation, 1) by source_player_id",
    ),
    _feature(
        "route_participation_roll3",
        "Mean route participation proxy over up to three prior completed games.",
        "participation", ("source_player_id", "game_id", "route_participation"),
        "rolling_mean(shift(route_participation, 1), window=3)", lookback=3,
    ),
    _feature(
        "route_participation_roll5",
        "Mean route participation proxy over up to five prior completed games.",
        "participation", ("source_player_id", "game_id", "route_participation"),
        "rolling_mean(shift(route_participation, 1), window=5)", lookback=5,
    ),
    _feature(
        "route_participation_missing", "One when prior route-participation history is unavailable.",
        "participation", ("route_participation",), "is_null(route_participation_lag1)",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int8",
    ),
    *_context_features(),
    _feature(
        "home_indicator", "One when the player's team is the scheduled home team.",
        "schedules", ("is_home",), "copy pregame schedule flag",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int8",
    ),
    _feature(
        "rest_days", "Days since the player's previous recorded game.",
        "schedules", ("kickoff",), "kickoff - prior player kickoff in days",
        timing=FeatureTiming.PREGAME, lookback=1,
    ),
    _feature(
        "game_week", "NFL week known before kickoff.",
        "schedules", ("week",), "copy scheduled week",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int32",
    ),
    _feature(
        "season_year", "NFL season known before kickoff.",
        "schedules", ("season",), "copy scheduled season",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int32",
    ),
    _feature(
        "has_prior_history", "One when at least one prior player game exists.",
        "wr_player_game", ("game_id",), "games_played_before > 0",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.FILL_ZERO, dtype="Int8",
    ),
    _feature(
        "team_plays_roll3", "Prior three-game team plays, unavailable in the v0.5A source contract.",
        "team_stats", ("plays",), "not implemented",
        grain=EntityGrain.TEAM_GAME, lookback=3, missing=MissingValuePolicy.NOT_AVAILABLE,
        enabled=False, carry_across_seasons=False,
    ),
    _feature(
        "team_plays_roll5", "Prior five-game team plays, unavailable in the v0.5A source contract.",
        "team_stats", ("plays",), "not implemented",
        grain=EntityGrain.TEAM_GAME, lookback=5, missing=MissingValuePolicy.NOT_AVAILABLE,
        enabled=False, carry_across_seasons=False,
    ),
    _feature(
        "player_age", "Pregame player age; no reliable timestamped source is joined in v0.5B.",
        "rosters", ("birth_date",), "not implemented", timing=FeatureTiming.PREGAME,
        lookback=0, minimum_history=0, missing=MissingValuePolicy.NOT_AVAILABLE, enabled=False,
    ),
    _feature(
        "prior_injury_designation",
        "Prior injury designation; disabled until source publication timestamps are validated.",
        "injuries", ("report_status", "captured_at"), "not implemented",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        missing=MissingValuePolicy.NOT_AVAILABLE, enabled=False, dtype="String",
    ),
    _feature(
        "same_game_targets",
        "Current-game targets, documented only as a prohibited leakage example.",
        "player_stats", ("targets",), "prohibited current-game value",
        timing=FeatureTiming.PREGAME, lookback=0, minimum_history=0,
        risk=LeakageRisk.HIGH, enabled=False, missing=MissingValuePolicy.LEAVE_NULL,
    ),
])

WR_FEATURE_REGISTRY = FeatureRegistry(features=FEATURE_REGISTRY)
MODEL_FEATURE_NAMES: tuple[str, ...] = WR_FEATURE_REGISTRY.enabled_names


def validate_feature_registry() -> FeatureRegistry:
    """Validate the machine-readable registry and return its immutable instance."""
    return FeatureRegistry.model_validate(WR_FEATURE_REGISTRY.model_dump())
