import json
from pathlib import Path

import polars as pl
import pytest

from app.research.dataset import (
    TRAINING_COLUMNS,
    TrainingDatasetError,
    build_wr_training_table,
    write_training_dataset,
)


FIXTURES = Path(__file__).parent / "fixtures" / "nflverse"


def _frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    return (
        pl.read_csv(FIXTURES / "player_stats.csv", try_parse_dates=True),
        pl.read_csv(FIXTURES / "schedules.csv", try_parse_dates=True),
    )


def test_training_table_is_one_normalized_row_per_wr_game():
    table = build_wr_training_table(*_frames())

    assert table.columns == list(TRAINING_COLUMNS)
    assert table.height == 8
    assert table.select("source_player_id", "game_id").unique().height == table.height
    brown_names = table.filter(pl.col("source_player_id") == "00-0035676").get_column("canonical_player_name")
    assert brown_names.unique().to_list() == ["aj brown"]
    assert table.get_column("actual_receptions").to_list() == [7, 7, 4, 4, 5, 7, 6, 2]


def test_same_game_values_are_excluded_from_training_table():
    table = build_wr_training_table(*_frames())
    assert "targets" not in table.columns
    assert "receiving_yards" not in table.columns
    assert not any(name.startswith("feature_") for name in table.columns)


def test_training_content_hash_is_reproducible(tmp_path: Path):
    table = build_wr_training_table(*_frames())
    first = write_training_dataset(
        table, output_path=tmp_path / "one.parquet", source_manifest_hash="source-hash"
    )
    second = write_training_dataset(
        table.reverse(), output_path=tmp_path / "two.parquet", source_manifest_hash="source-hash"
    )
    assert first.dataset_hash == second.dataset_hash
    assert first.file_hash == second.file_hash
    assert first.manifest_hash == second.manifest_hash
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["content_sha256"] == first.dataset_hash
    assert manifest["manifest_hash"] == first.manifest_hash
    assert manifest["target"] == "actual_receptions"
    assert manifest["predictor_columns"] == []


def test_training_table_is_independent_of_source_row_order():
    stats, schedules = _frames()
    expected = build_wr_training_table(stats, schedules)
    actual = build_wr_training_table(
        stats.sample(fraction=1.0, shuffle=True, seed=7),
        schedules.sample(fraction=1.0, shuffle=True, seed=11),
    )
    assert actual.equals(expected)


@pytest.mark.parametrize("column", ["player_id", "player_display_name"])
def test_missing_player_identity_fails_clearly(column: str):
    stats, schedules = _frames()
    stats = stats.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(None).otherwise(pl.col(column)).alias(column)
    )
    with pytest.raises(TrainingDatasetError, match="source player IDs and names"):
        build_wr_training_table(stats, schedules)


def test_duplicate_player_game_rows_fail_clearly():
    stats, schedules = _frames()
    stats = pl.concat([stats, stats.head(1)])
    with pytest.raises(TrainingDatasetError, match="Duplicate player-game"):
        build_wr_training_table(stats, schedules)


def test_missing_schedule_join_fails_instead_of_dropping_rows():
    stats, schedules = _frames()
    with pytest.raises(TrainingDatasetError, match="Schedule join failed"):
        build_wr_training_table(stats, schedules.filter(pl.col("season") == 2023))


def test_schema_drift_fails_clearly():
    stats, schedules = _frames()
    with pytest.raises(TrainingDatasetError, match="missing player_stats"):
        build_wr_training_table(stats.drop("receptions"), schedules)
