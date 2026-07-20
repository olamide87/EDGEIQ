import math
import runpy

import polars as pl
import pytest

from app.research.baselines import (
    BASELINE_SPECS,
    BaselineDatasetError,
    BaselineName,
    build_wr_baseline_predictions,
)
from app.research.features import build_wr_feature_table


def _feature_table() -> pl.DataFrame:
    namespace = runpy.run_path("tests/test_wr_features.py")
    stats, _, training = namespace["_feature_inputs"]()
    return build_wr_feature_table(training, stats)


def _prediction(
    frame: pl.DataFrame,
    player_id: str,
    game_id: str,
    baseline: BaselineName,
) -> dict[str, object]:
    return frame.filter(
        (pl.col("source_player_id") == player_id)
        & (pl.col("game_id") == game_id)
        & (pl.col("baseline") == baseline.value)
    ).to_dicts()[0]


def test_baseline_registry_is_versioned_and_complete():
    assert [spec.name for spec in BASELINE_SPECS] == list(BaselineName)
    assert len({spec.name for spec in BASELINE_SPECS}) == len(BASELINE_SPECS)
    assert all(spec.implementation_version == "1.0.0" for spec in BASELINE_SPECS)
    assert next(spec for spec in BASELINE_SPECS if spec.name is BaselineName.POISSON).distribution == "poisson"


def test_baselines_use_only_completed_prior_games():
    features = _feature_table()
    predictions = build_wr_baseline_predictions(features)

    opener = _prediction(
        predictions, "P1", "2023_01_DAL_PHI", BaselineName.CAREER_AVERAGE
    )
    game_two = _prediction(
        predictions, "P1", "2023_02_PHI_DAL", BaselineName.CAREER_AVERAGE
    )
    assert opener["eligible"] is False
    assert opener["prediction"] is None
    assert game_two["prediction"] == 4
    assert game_two["history_count"] == 1

    assert _prediction(
        predictions, "P1", "2023_02_PHI_DAL", BaselineName.PREVIOUS_GAME
    )["prediction"] == 4
    assert _prediction(
        predictions, "P1", "2023_04_DAL_PHI", BaselineName.ROLLING_3
    )["prediction"] == pytest.approx(4.5)


def test_same_game_barrier_and_input_order_are_deterministic():
    features = _feature_table()
    baseline = build_wr_baseline_predictions(features)
    reversed_result = build_wr_baseline_predictions(features.reverse())
    assert baseline.to_dicts() == reversed_result.to_dicts()

    first_game = baseline.filter(pl.col("game_id") == "2023_01_DAL_PHI")
    league = first_game.filter(pl.col("baseline") == BaselineName.LEAGUE_MEAN.value)
    assert league.get_column("eligible").to_list() == [False, False]

    changed = features.with_columns(
        pl.when(pl.col("game_id") == "2023_01_DAL_PHI")
        .then(pl.col("actual_receptions") + 100)
        .otherwise(pl.col("actual_receptions"))
        .alias("actual_receptions")
    )
    changed_predictions = build_wr_baseline_predictions(changed)
    unchanged_columns = [
        "source_player_id",
        "game_id",
        "baseline",
        "prediction",
        "history_count",
        "eligible",
        "exclusion_reason",
    ]
    assert (
        baseline.filter(pl.col("game_id") == "2023_01_DAL_PHI").select(unchanged_columns).to_dicts()
        == changed_predictions.filter(pl.col("game_id") == "2023_01_DAL_PHI").select(unchanged_columns).to_dicts()
    )


def test_season_average_resets_while_career_average_carries_across_seasons():
    predictions = build_wr_baseline_predictions(_feature_table())
    game = "2024_01_DAL_PHI"

    season = _prediction(predictions, "P1", game, BaselineName.SEASON_TO_DATE)
    career = _prediction(predictions, "P1", game, BaselineName.CAREER_AVERAGE)
    assert season["eligible"] is False
    assert season["prediction"] is None
    assert career["prediction"] == pytest.approx((4 + 5 + 6 + 7) / 4)


def test_poisson_rate_uses_documented_deterministic_fallback_order():
    predictions = build_wr_baseline_predictions(_feature_table())

    game_two = _prediction(
        predictions, "P1", "2023_02_PHI_DAL", BaselineName.POISSON
    )
    new_season = _prediction(
        predictions, "P1", "2024_01_DAL_PHI", BaselineName.POISSON
    )
    assert game_two["prediction"] == 4
    assert game_two["distribution"] == "poisson"
    assert new_season["prediction"] == pytest.approx((4 + 5 + 6 + 7) / 4)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("actual_receptions", "bad", "finite numeric"),
        ("actual_receptions", math.inf, "finite numeric"),
        ("actual_receptions", -1, "negative"),
        ("receptions_roll3", math.nan, "finite numeric"),
    ),
)
def test_baseline_input_fails_explicitly_for_invalid_values(
    column: str,
    value: object,
    message: str,
):
    features = _feature_table()
    original = pl.col(column).cast(pl.String) if isinstance(value, str) else pl.col(column)
    invalid = features.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value))
        .otherwise(original)
        .alias(column)
    )
    with pytest.raises(BaselineDatasetError, match=message):
        build_wr_baseline_predictions(invalid)


def test_baseline_input_rejects_duplicates_missing_columns_and_duplicate_requests():
    features = _feature_table()
    with pytest.raises(BaselineDatasetError, match="duplicate player-game"):
        build_wr_baseline_predictions(pl.concat([features, features.head(1)]))
    with pytest.raises(BaselineDatasetError, match="missing required"):
        build_wr_baseline_predictions(features.drop("receptions_lag1"))
    with pytest.raises(BaselineDatasetError, match="unique"):
        build_wr_baseline_predictions(
            features,
            baselines=(BaselineName.ROLLING_3, BaselineName.ROLLING_3),
        )
