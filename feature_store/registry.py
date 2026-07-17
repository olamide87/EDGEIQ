from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FeatureTiming(StrEnum):
    PREGAME = "pregame"
    LAGGED = "lagged"


class LeakageRisk(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    dtype: str
    source: str
    timing: FeatureTiming
    description: str
    lookback_games: int = 0
    leakage_risk: LeakageRisk = LeakageRisk.NONE
    retained: bool = True


def _lagged(name: str, source: str, description: str, lookback_games: int = 1) -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        dtype="float64",
        source=source,
        timing=FeatureTiming.LAGGED,
        description=description,
        lookback_games=lookback_games,
    )


FEATURE_REGISTRY: tuple[FeatureDefinition, ...] = (
    _lagged("receptions_lag1", "player_stats", "Receptions in the player's prior game."),
    _lagged("targets_lag1", "player_stats", "Targets in the player's prior game."),
    _lagged("receptions_roll3", "player_stats", "Mean receptions over the prior three games.", 3),
    _lagged("receptions_roll5", "player_stats", "Mean receptions over the prior five games.", 5),
    _lagged("receptions_roll8", "player_stats", "Mean receptions over the prior eight games.", 8),
    _lagged("targets_roll3", "player_stats", "Mean targets over the prior three games.", 3),
    _lagged("targets_roll5", "player_stats", "Mean targets over the prior five games.", 5),
    _lagged("target_share_roll5", "player_stats", "Mean target share over the prior five games.", 5),
    _lagged("catch_rate_roll5", "player_stats", "Catch rate over the prior five games.", 5),
    _lagged("snap_share_lag1", "snap_counts", "Offensive snap share in the prior game."),
    _lagged("snap_share_roll3", "snap_counts", "Mean offensive snap share over the prior three games.", 3),
    _lagged("team_pass_attempts_roll3", "player_stats", "Team pass-attempt mean over prior games.", 3),
    _lagged("opponent_wr_receptions_allowed_roll3", "player_stats", "Opponent WR receptions allowed over prior games.", 3),
    FeatureDefinition(name="is_home", dtype="int8", source="schedules", timing=FeatureTiming.PREGAME,
                      description="One when the player's team is the scheduled home team."),
    FeatureDefinition(name="rest_days", dtype="float64", source="schedules", timing=FeatureTiming.PREGAME,
                      description="Days since the player's previous game.", lookback_games=1),
    FeatureDefinition(name="season", dtype="int32", source="schedules", timing=FeatureTiming.PREGAME,
                      description="NFL season."),
    FeatureDefinition(name="week", dtype="int32", source="schedules", timing=FeatureTiming.PREGAME,
                      description="NFL week."),
    FeatureDefinition(
        name="same_game_targets",
        dtype="float64",
        source="player_stats",
        timing=FeatureTiming.PREGAME,
        description="Current-game targets; documented only to prohibit it from prediction features.",
        leakage_risk=LeakageRisk.HIGH,
        retained=False,
    ),
)


MODEL_FEATURE_NAMES: tuple[str, ...] = tuple(
    feature.name for feature in FEATURE_REGISTRY if feature.retained
)
