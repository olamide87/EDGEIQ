from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from app.cli import main
from app.research.dataset import build_wr_training_table
from app.research.feature_audit import audit_wr_feature_table
from app.research.features import (
    FEATURE_COLUMNS,
    FeatureDatasetError,
    build_wr_feature_table,
    canonical_feature_content_hash,
    load_and_validate_wr_feature_dataset,
    validate_wr_feature_table,
    write_wr_feature_dataset,
)
from feature_store.registry import FeatureRegistry, WR_FEATURE_REGISTRY


def _synthetic_inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    games = [
        (2023, 1, "2023_01_DAL_PHI", "2023-09-10", "PHI", "DAL"),
        (2023, 2, "2023_02_PHI_DAL", "2023-09-17", "DAL", "PHI"),
        (2023, 4, "2023_04_DAL_PHI", "2023-10-01", "PHI", "DAL"),
        (2023, 5, "2023_05_PHI_DAL", "2023-10-08", "DAL", "PHI"),
        (2024, 1, "2024_01_DAL_PHI", "2024-09-08", "PHI", "DAL"),
        (2024, 2, "2024_02_PHI_DAL", "2024-09-15", "DAL", "PHI"),
    ]
    schedules = pl.DataFrame(
        [
            {
                "season": season,
                "week": week,
                "game_type": "REG",
                "game_id": game_id,
                "gameday": gameday,
                "gametime": "12:00",
                "home_team": home,
                "away_team": away,
            }
            for season, week, game_id, gameday, home, away in games
        ]
    )
    rows: list[dict[str, object]] = []
    for index, (season, week, _, _, _, _) in enumerate(games):
        p1_team = "PHI" if index < 3 else "DAL"
        receivers = [
            ("P1", "Trade Receiver", p1_team, 4 + index, 7 + index, 50 + index * 10),
            ("P2", "Dallas Receiver", "DAL", 3 + index, 6 + index, 40 + index * 8),
        ]
        if index >= 3:
            receivers.append(("P3", "Rookie Receiver", "PHI", 2 + index, 5 + index, 30 + index * 7))
        for player_id, name, team, receptions, targets, yards in receivers:
            rows.append({
                "season": season, "week": week, "season_type": "REG",
                "player_id": player_id, "player_display_name": name,
                "position": "WR", "recent_team": team,
                "receptions": receptions, "targets": targets,
                "receiving_yards": yards, "attempts": 0, "completions": 0,
            })
        for team, attempts, completions in (
            ("PHI", 30 + index, 20 + index),
            ("DAL", 36 + index, 24 + index),
        ):
            rows.append({
                "season": season, "week": week, "season_type": "REG",
                "player_id": f"QB-{team}", "player_display_name": f"{team} Quarterback",
                "position": "QB", "recent_team": team,
                "receptions": 0, "targets": 0, "receiving_yards": 0,
                "attempts": attempts, "completions": completions,
            })
    return pl.DataFrame(rows), schedules


def _feature_inputs() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    stats, schedules = _synthetic_inputs()
    training = build_wr_training_table(stats, schedules)
    return stats, schedules, training


def _row(frame: pl.DataFrame, player: str, game: str) -> dict[str, object]:
    return frame.filter(
        (pl.col("source_player_id") == player) & (pl.col("game_id") == game)
    ).to_dicts()[0]


def test_shifted_rolling_cumulative_target_share_and_opponent_features():
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    game_two = _row(features, "P1", "2023_02_PHI_DAL")
    assert game_two["receptions_lag1"] == 4
    assert game_two["receptions_roll3"] == 4
    assert game_two["receptions_season_mean"] == 4
    assert game_two["games_played_before"] == 1
    assert game_two["target_share_roll3"] == pytest.approx(7 / 30)
    assert game_two["team_pass_attempts_roll3"] == 30
    assert game_two["team_completion_rate_roll3"] == pytest.approx(20 / 30)
    assert game_two["opponent_pass_attempts_allowed_roll3"] == 30
    assert game_two["opponent_wr_targets_allowed_roll3"] == 7


def test_season_boundaries_rookies_trades_and_bye_weeks():
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    after_bye = _row(features, "P1", "2023_04_DAL_PHI")
    assert after_bye["rest_days"] == 14
    after_trade = _row(features, "P1", "2023_05_PHI_DAL")
    assert after_trade["receptions_lag1"] == 6
    new_season = _row(features, "P1", "2024_01_DAL_PHI")
    assert new_season["receptions_lag1"] == 7
    assert new_season["receptions_season_mean"] is None
    assert new_season["team_pass_attempts_roll3"] is None
    assert new_season["opponent_wr_targets_allowed_roll3"] is None
    rookie = _row(features, "P3", "2023_05_PHI_DAL")
    assert rookie["games_played_before"] == 0
    assert rookie["has_prior_history"] == 0
    assert rookie["receptions_lag1"] is None


def test_multiple_receivers_share_team_context_without_sharing_player_history():
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    traded = _row(features, "P1", "2023_05_PHI_DAL")
    teammate = _row(features, "P2", "2023_05_PHI_DAL")
    assert traded["team_pass_attempts_roll3"] == teammate["team_pass_attempts_roll3"]
    assert (
        traded["opponent_wr_targets_allowed_roll3"]
        == teammate["opponent_wr_targets_allowed_roll3"]
    )
    assert traded["receptions_lag1"] == 6
    assert teammate["receptions_lag1"] == 5


def test_missing_usage_is_explicit_and_optional_usage_is_shifted():
    stats, _, training = _feature_inputs()
    no_usage = build_wr_feature_table(training, stats)
    assert no_usage.get_column("snap_share_missing").to_list() == [1] * no_usage.height
    usage = training.select("source_player_id", "game_id").with_columns(
        pl.lit(0.75).alias("snap_share"),
        pl.lit(0.6).alias("route_participation"),
    )
    features = build_wr_feature_table(
        training, stats, snap_counts=usage,
        participation=usage.rename({"snap_share": "unused"}),
    )
    first = _row(features, "P1", "2023_01_DAL_PHI")
    second = _row(features, "P1", "2023_02_PHI_DAL")
    assert first["snap_share_lag1"] is None
    assert second["snap_share_lag1"] == 0.75
    assert second["route_participation_lag1"] == 0.6
    assert second["snap_share_missing"] == 0


def test_legitimate_null_optional_usage_remains_missing():
    stats, _, training = _feature_inputs()
    usage = training.select("source_player_id", "game_id").with_columns(
        pl.lit(None, dtype=pl.Float64).alias("snap_share"),
        pl.lit(None, dtype=pl.Float64).alias("route_participation"),
    )
    features = build_wr_feature_table(
        training,
        stats,
        snap_counts=usage.select("source_player_id", "game_id", "snap_share"),
        participation=usage.select(
            "source_player_id", "game_id", "route_participation"
        ),
    )
    assert features.get_column("snap_share_lag1").null_count() == features.height
    assert features.get_column("route_participation_lag1").null_count() == features.height
    assert features.get_column("snap_share_missing").to_list() == [1] * features.height
    assert features.get_column("route_participation_missing").to_list() == [1] * features.height


@pytest.mark.parametrize(
    ("argument_name", "value_column"),
    (
        ("snap_counts", "snap_share"),
        ("participation", "route_participation"),
    ),
)
def test_malformed_non_null_optional_usage_is_rejected(
    argument_name: str,
    value_column: str,
):
    stats, _, training = _feature_inputs()
    usage = training.select("source_player_id", "game_id").with_columns(
        pl.lit("not-a-number").alias(value_column)
    )
    with pytest.raises(FeatureDatasetError, match="must contain numeric values or null"):
        build_wr_feature_table(training, stats, **{argument_name: usage})


def test_current_and_future_outcomes_cannot_change_available_features():
    stats, _, training = _feature_inputs()
    baseline = build_wr_feature_table(training, stats)
    target_game = "2023_02_PHI_DAL"
    changed_stats = stats.with_columns(
        pl.when((pl.col("player_id") == "P1") & (pl.col("season") == 2023) & (pl.col("week") == 2))
        .then(pl.lit(8)).otherwise(pl.col("receptions")).alias("receptions")
    )
    changed_training = training.with_columns(
        pl.when((pl.col("source_player_id") == "P1") & (pl.col("game_id") == target_game))
        .then(pl.lit(8)).otherwise(pl.col("actual_receptions")).alias("actual_receptions")
    )
    current_changed = build_wr_feature_table(changed_training, changed_stats)
    baseline_row = _row(baseline, "P1", target_game)
    changed_row = _row(current_changed, "P1", target_game)
    assert {name: baseline_row[name] for name in FEATURE_COLUMNS} == {
        name: changed_row[name] for name in FEATURE_COLUMNS
    }

    future_stats = stats.with_columns(
        pl.when((pl.col("player_id") == "P1") & (pl.col("season") == 2024) & (pl.col("week") == 2))
        .then(pl.lit(25)).otherwise(pl.col("targets")).alias("targets")
    )
    future_changed = build_wr_feature_table(training, future_stats)
    past_games = baseline.filter(pl.col("kickoff") < pl.datetime(2024, 9, 15, 12))
    changed_past = future_changed.filter(pl.col("kickoff") < pl.datetime(2024, 9, 15, 12))
    assert past_games.to_dicts() == changed_past.to_dicts()


def test_current_game_team_and_opponent_mutations_leave_entire_game_features_unchanged():
    stats, _, training = _feature_inputs()
    baseline = build_wr_feature_table(training, stats)
    in_game = (pl.col("season") == 2023) & (pl.col("week") == 2)
    is_wr = pl.col("position") == "WR"
    changed_stats = stats.with_columns(
        pl.when(in_game & is_wr).then(pl.col("receptions") + 1)
        .otherwise(pl.col("receptions")).alias("receptions"),
        pl.when(in_game & is_wr).then(pl.col("targets") + 3)
        .otherwise(pl.col("targets")).alias("targets"),
        pl.when(in_game & is_wr).then(pl.col("receiving_yards") + 20)
        .otherwise(pl.col("receiving_yards")).alias("receiving_yards"),
        pl.when(in_game & ~is_wr).then(pl.col("attempts") + 10)
        .otherwise(pl.col("attempts")).alias("attempts"),
        pl.when(in_game & ~is_wr).then(pl.col("completions") + 5)
        .otherwise(pl.col("completions")).alias("completions"),
    )
    changed = build_wr_feature_table(training, changed_stats)
    game_id = "2023_02_PHI_DAL"
    baseline_game = baseline.filter(pl.col("game_id") == game_id).select(FEATURE_COLUMNS)
    changed_game = changed.filter(pl.col("game_id") == game_id).select(FEATURE_COLUMNS)
    assert baseline_game.to_dicts() == changed_game.to_dicts()


def test_zero_target_history_has_explicit_denominator_behavior():
    stats, schedules, _ = _feature_inputs()
    first_game_wr = (
        (pl.col("season") == 2023)
        & (pl.col("week") == 1)
        & (pl.col("position") == "WR")
    )
    zeroed = stats.with_columns(
        pl.when(first_game_wr).then(pl.lit(0)).otherwise(pl.col("receptions")).alias("receptions"),
        pl.when(first_game_wr).then(pl.lit(0)).otherwise(pl.col("targets")).alias("targets"),
    )
    training = build_wr_training_table(zeroed, schedules)
    features = build_wr_feature_table(training, zeroed)
    second = _row(features, "P1", "2023_02_PHI_DAL")
    assert second["catch_rate_roll3"] is None
    assert second["target_share_roll3"] == 0
    assert second["team_target_concentration_roll3"] is None
    assert second["opponent_wr_targets_allowed_roll3"] == 0


def test_two_games_in_same_week_do_not_share_team_or_opponent_history():
    stats, schedules, _ = _feature_inputs()
    extra_schedule = pl.DataFrame([{
        "season": 2023, "week": 2, "game_type": "REG",
        "game_id": "2023_02_NYJ_NYG", "gameday": "2023-09-17", "gametime": "15:00",
        "home_team": "NYG", "away_team": "NYJ",
    }])
    extra_stats = pl.DataFrame([
        {
            "season": 2023, "week": 2, "season_type": "REG", "player_id": "P-NYG",
            "player_display_name": "Giants Receiver", "position": "WR", "recent_team": "NYG",
            "receptions": 4, "targets": 6, "receiving_yards": 50, "attempts": 0,
            "completions": 0,
        },
        {
            "season": 2023, "week": 2, "season_type": "REG", "player_id": "P-NYJ",
            "player_display_name": "Jets Receiver", "position": "WR", "recent_team": "NYJ",
            "receptions": 3, "targets": 5, "receiving_yards": 40, "attempts": 0,
            "completions": 0,
        },
        {
            "season": 2023, "week": 2, "season_type": "REG", "player_id": "QB-NYG",
            "player_display_name": "Giants Quarterback", "position": "QB", "recent_team": "NYG",
            "receptions": 0, "targets": 0, "receiving_yards": 0, "attempts": 28,
            "completions": 18,
        },
        {
            "season": 2023, "week": 2, "season_type": "REG", "player_id": "QB-NYJ",
            "player_display_name": "Jets Quarterback", "position": "QB", "recent_team": "NYJ",
            "receptions": 0, "targets": 0, "receiving_yards": 0, "attempts": 32,
            "completions": 21,
        },
    ])
    combined_stats = pl.concat([stats, extra_stats], how="diagonal_relaxed")
    combined_schedules = pl.concat([schedules, extra_schedule], how="diagonal_relaxed")
    training = build_wr_training_table(combined_stats, combined_schedules)
    features = build_wr_feature_table(training, combined_stats)
    first_nyg = _row(features, "P-NYG", "2023_02_NYJ_NYG")
    assert first_nyg["team_pass_attempts_roll3"] is None
    assert first_nyg["opponent_pass_attempts_allowed_roll3"] is None
    assert _row(features, "P1", "2023_02_PHI_DAL")["team_pass_attempts_roll3"] == 30


def test_source_order_is_irrelevant_and_hash_is_deterministic():
    stats, _, training = _feature_inputs()
    first = build_wr_feature_table(training.reverse(), stats.reverse())
    second = build_wr_feature_table(training, stats)
    assert first.to_dicts() == second.to_dicts()
    assert canonical_feature_content_hash(first) == canonical_feature_content_hash(second)


def test_duplicate_rows_and_malformed_optional_usage_are_rejected():
    stats, _, training = _feature_inputs()
    with pytest.raises(FeatureDatasetError, match="duplicate"):
        build_wr_feature_table(pl.concat([training, training.head(1)]), stats)
    with pytest.raises(FeatureDatasetError, match="missing required columns"):
        build_wr_feature_table(training, stats.drop("targets"))
    with pytest.raises(FeatureDatasetError, match="null or empty source_player_id"):
        build_wr_feature_table(
            training.with_columns(
                pl.when(pl.int_range(pl.len()) == 0)
                .then(pl.lit(None))
                .otherwise(pl.col("source_player_id"))
                .alias("source_player_id")
            ),
            stats,
        )
    usage = training.head(1).select("source_player_id", "game_id").with_columns(
        pl.lit(1.2).alias("snap_share")
    )
    with pytest.raises(FeatureDatasetError, match="at most 1"):
        build_wr_feature_table(training, stats, snap_counts=usage)
    with pytest.raises(FeatureDatasetError, match="null kickoff"):
        build_wr_feature_table(
            training.with_columns(
                pl.when(pl.int_range(pl.len()) == 0).then(pl.lit(None))
                .otherwise(pl.col("kickoff")).alias("kickoff")
            ),
            stats,
        )


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("attempts", "not-a-number", "must contain numeric values or null"),
        ("completions", "not-a-number", "must contain numeric values or null"),
        ("attempts", -1, "must be at least 0"),
        ("completions", -1, "must be at least 0"),
    ),
)
def test_invalid_team_passing_values_fail_explicitly(
    column: str,
    value: object,
    message: str,
):
    stats, _, training = _feature_inputs()
    original = pl.col(column).cast(pl.String) if isinstance(value, str) else pl.col(column)
    invalid = stats.with_columns(
        pl.when(pl.col("player_id") == "QB-PHI")
        .then(pl.lit(value))
        .otherwise(original)
        .alias(column)
    )
    with pytest.raises(FeatureDatasetError, match=message):
        build_wr_feature_table(training, invalid)


def test_completions_greater_than_attempts_fail_explicitly():
    stats, _, training = _feature_inputs()
    invalid = stats.with_columns(
        pl.when(pl.col("player_id") == "QB-PHI")
        .then(pl.lit(5))
        .otherwise(pl.col("attempts"))
        .alias("attempts"),
        pl.when(pl.col("player_id") == "QB-PHI")
        .then(pl.lit(6))
        .otherwise(pl.col("completions"))
        .alias("completions"),
    )
    with pytest.raises(FeatureDatasetError, match="completions cannot exceed attempts"):
        build_wr_feature_table(training, invalid)


def test_output_contract_rejects_wrong_dtype_disabled_columns_and_registry_mismatch():
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    with pytest.raises(FeatureDatasetError, match="dtype"):
        validate_wr_feature_table(
            features.with_columns(pl.col("receptions_lag1").cast(pl.Int64))
        )
    with pytest.raises(FeatureDatasetError, match="exactly match"):
        validate_wr_feature_table(features.with_columns(pl.lit(1).alias("same_game_targets")))
    changed_first = WR_FEATURE_REGISTRY.features[0].model_copy(update={"enabled": False})
    mismatched = FeatureRegistry(
        features=(changed_first, *WR_FEATURE_REGISTRY.features[1:])
    )
    with pytest.raises(FeatureDatasetError, match="enabled registry"):
        validate_wr_feature_table(features, registry=mismatched)


def test_atomic_write_manifest_hashes_validation_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    path = tmp_path / "wr_features.parquet"
    first = write_wr_feature_dataset(
        features, output_path=path, source_manifest_hashes={"source": "abc"}
    )
    second = write_wr_feature_dataset(
        features, output_path=path, source_manifest_hashes={"source": "abc"}
    )
    assert first.content_hash == second.content_hash
    assert first.manifest_hash == second.manifest_hash
    assert not path.with_suffix(".parquet.tmp").exists()
    assert not path.with_suffix(".manifest.json.tmp").exists()
    validated = load_and_validate_wr_feature_dataset(path)
    assert validated["content_hash"] == first.content_hash
    audit = audit_wr_feature_table(
        features, source_hashes={"source": "abc"}, output_hash=first.content_hash
    )
    assert audit["row_count"] == features.height
    assert audit["feature_count"] == len(FEATURE_COLUMNS)
    assert audit["leakage_validation"]["status"] == "NOT_RUN"
    assert audit["leakage_validation"]["checks_run"] == []
    assert list(audit["features"]) == list(FEATURE_COLUMNS)
    assert list(audit["source_hashes"]) == ["source"]

    changed_source = write_wr_feature_dataset(
        features, output_path=path, source_manifest_hashes={"source": "changed"}
    )
    assert changed_source.content_hash == first.content_hash
    assert changed_source.manifest_hash != first.manifest_hash

    stable_bytes = path.read_bytes()
    original_write = pl.DataFrame.write_parquet

    def fail_write(self: pl.DataFrame, destination: Path, *args: object, **kwargs: object) -> None:
        Path(destination).write_bytes(b"incomplete")
        raise OSError("synthetic write failure")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", fail_write)
    with pytest.raises(OSError, match="synthetic"):
        write_wr_feature_dataset(
            features, output_path=path, source_manifest_hashes={"source": "failure"}
        )
    assert path.read_bytes() == stable_bytes
    assert not path.with_suffix(".parquet.tmp").exists()
    monkeypatch.setattr(pl.DataFrame, "write_parquet", original_write)


def test_deliberately_leaky_table_cannot_receive_false_audit_pass():
    stats, _, training = _feature_inputs()
    features = build_wr_feature_table(training, stats)
    leaky = features.with_columns(
        pl.col("actual_receptions").cast(pl.Float64).alias("receptions_lag1")
    )
    audit = audit_wr_feature_table(leaky)
    assert leaky.get_column("receptions_lag1").to_list() == leaky.get_column(
        "actual_receptions"
    ).cast(pl.Float64).to_list()
    assert audit["leakage_validation"]["status"] == "NOT_RUN"
    assert audit["leakage_validation"]["status"] != "PASS"


def test_feature_cli_registry_and_validation(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    main(["feature-registry"])
    registry = json.loads(capsys.readouterr().out)
    assert registry["version"] == "wr-receptions-features-v1"

    stats, _, training = _feature_inputs()
    path = tmp_path / "wr_features.parquet"
    write_wr_feature_dataset(
        build_wr_feature_table(training, stats),
        output_path=path,
        source_manifest_hashes={"fixture": "offline"},
    )
    main(["validate-wr-features", "--path", str(path)])
    report = json.loads(capsys.readouterr().out)
    assert report["rows"] == training.height
