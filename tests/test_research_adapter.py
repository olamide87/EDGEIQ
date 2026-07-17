from pathlib import Path

import polars as pl
import pytest

from app.research.manifest import load_manifest
from app.research.nflverse import (
    DATASET_CONTRACTS,
    DatasetSchemaError,
    DatasetUnavailableError,
    NflverseAdapter,
    fixture_csv_loader,
)


FIXTURES = Path(__file__).parent / "fixtures" / "nflverse"


def _adapter(tmp_path: Path) -> NflverseAdapter:
    return NflverseAdapter(
        seasons=[2023, 2024],
        cache_dir=tmp_path / "data" / "raw" / "nflverse",
        manifest_dir=tmp_path / "data" / "manifests",
        loaders={
            "player_stats": fixture_csv_loader(FIXTURES / "player_stats.csv"),
            "schedules": fixture_csv_loader(FIXTURES / "schedules.csv"),
            "rosters": fixture_csv_loader(FIXTURES / "rosters.csv"),
        },
    )


def test_adapter_caches_fixture_data_and_writes_verified_manifest(tmp_path: Path):
    adapter = _adapter(tmp_path)
    frames, manifest_path, manifest = adapter.download(["player_stats", "schedules"])

    assert frames["player_stats"].height == 8
    assert len(manifest.files) == 4
    assert all(item.sha256 and item.row_count > 0 for item in manifest.files)
    assert load_manifest(manifest_path).manifest_hash == manifest.manifest_hash
    assert {source.dataset for source in manifest.sources} == {"player_stats", "schedules"}

    cached = NflverseAdapter(
        seasons=[2023, 2024],
        cache_dir=adapter.cache_dir,
        manifest_dir=adapter.manifest_dir,
        loaders={"player_stats": lambda _: (_ for _ in ()).throw(AssertionError("network loader called"))},
    ).fetch("player_stats")
    assert cached.height == 8


def test_independent_fixture_downloads_have_identical_manifest_hashes(tmp_path: Path):
    first = _adapter(tmp_path / "first").download(["player_stats", "schedules"])[2]
    second = _adapter(tmp_path / "second").download(["schedules", "player_stats"])[2]
    assert first.manifest_hash == second.manifest_hash
    assert [item.sha256 for item in first.files] == [item.sha256 for item in second.files]


@pytest.mark.parametrize("season", [0, 1919, 2101, True])
def test_adapter_rejects_invalid_seasons(tmp_path: Path, season: int):
    with pytest.raises(ValueError, match="four-digit NFL seasons"):
        NflverseAdapter(seasons=[season], cache_dir=tmp_path / "raw")


def test_adapter_rejects_empty_dataset_request(tmp_path: Path):
    with pytest.raises(ValueError, match="At least one dataset"):
        _adapter(tmp_path).download([])


def test_manifest_changes_when_source_content_changes(tmp_path: Path):
    adapter = _adapter(tmp_path)
    first = adapter.download(["player_stats"])[2]
    changed = pl.read_csv(FIXTURES / "player_stats.csv").with_columns(
        pl.when((pl.col("season") == 2024) & (pl.col("week") == 2))
        .then(pl.col("receptions") + 1)
        .otherwise(pl.col("receptions"))
        .alias("receptions")
    )
    adapter._loaders["player_stats"] = lambda seasons: changed.filter(
        pl.col("season").is_in(seasons)
    )
    second = adapter.download(["player_stats"], force=True)[2]
    assert first.manifest_hash != second.manifest_hash
    assert [item.sha256 for item in first.files] != [item.sha256 for item in second.files]


def test_adapter_fails_clearly_for_schema_drift_and_unknown_dataset(tmp_path: Path):
    adapter = NflverseAdapter(
        seasons=[2024],
        cache_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        loaders={"player_stats": lambda _: pl.DataFrame({"season": [2024]})},
    )
    with pytest.raises(DatasetSchemaError, match="missing required columns"):
        adapter.fetch("player_stats")
    with pytest.raises(DatasetUnavailableError, match="Unsupported dataset"):
        adapter.fetch("not_real")


def test_adapter_fails_when_requested_season_is_absent(tmp_path: Path):
    adapter = NflverseAdapter(
        seasons=[2022],
        cache_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        loaders={"schedules": fixture_csv_loader(FIXTURES / "schedules.csv")},
    )
    with pytest.raises(DatasetUnavailableError, match="no rows for season 2022"):
        adapter.fetch("schedules")


def test_adapter_filters_each_requested_season_and_accepts_current_team_column(tmp_path: Path):
    current = pl.read_csv(FIXTURES / "player_stats.csv").rename({"recent_team": "team"})
    adapter = NflverseAdapter(
        seasons=[2024],
        cache_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        loaders={"player_stats": lambda seasons: current.filter(pl.col("season").is_in(seasons))},
    )
    frame = adapter.fetch("player_stats")
    assert frame.get_column("season").unique().to_list() == [2024]
    assert "team" in frame.columns


def test_invalid_cached_parquet_and_wrong_cached_season_fail_clearly(tmp_path: Path):
    cache = tmp_path / "raw" / "schedules"
    cache.mkdir(parents=True)
    (cache / "2024.parquet").write_text("not parquet", encoding="utf-8")
    adapter = NflverseAdapter(
        seasons=[2024], cache_dir=tmp_path / "raw", manifest_dir=tmp_path / "manifests"
    )
    with pytest.raises(DatasetSchemaError, match="not valid Parquet"):
        adapter.fetch("schedules")

    pl.read_csv(FIXTURES / "schedules.csv").filter(pl.col("season") == 2023).write_parquet(
        cache / "2024.parquet"
    )
    with pytest.raises(DatasetSchemaError, match="expected 2024"):
        adapter.fetch("schedules")


def test_participation_dataset_without_season_column_is_partitioned_by_request(tmp_path: Path):
    def load_participation(seasons: list[int]) -> pl.DataFrame:
        season = seasons[0]
        return pl.DataFrame({
            "nflverse_game_id": [f"{season}_01_ARI_SF"],
            "play_id": [1],
        })

    adapter = NflverseAdapter(
        seasons=[2022, 2023],
        cache_dir=tmp_path / "raw",
        manifest_dir=tmp_path / "manifests",
        loaders={"participation": load_participation},
    )
    frame, _, manifest = adapter.download(["participation"])
    assert frame["participation"].height == 2
    assert [item.season for item in manifest.files] == [2022, 2023]
    assert "NFL NextGenStats" in manifest.sources[0].attribution
    assert "FTN Data" in manifest.sources[0].attribution


def test_depth_chart_contract_accepts_historical_and_current_schema_variants():
    contract = DATASET_CONTRACTS["depth_charts"]
    NflverseAdapter.validate(
        contract,
        pl.DataFrame({"season": [2024], "week": [1], "gsis_id": ["00-1"]}),
    )
    NflverseAdapter.validate(
        contract,
        pl.DataFrame({"dt": ["2025-09-01T12:00:00Z"], "team": ["PHI"], "gsis_id": ["00-1"]}),
    )
    with pytest.raises(DatasetSchemaError, match="one of these column sets"):
        NflverseAdapter.validate(contract, pl.DataFrame({"gsis_id": ["00-1"]}))


def test_manifest_tampering_is_detected(tmp_path: Path):
    _, manifest_path, _ = _adapter(tmp_path).download(["schedules"])
    text = manifest_path.read_text(encoding="utf-8").replace('"row_count": 2', '"row_count": 999', 1)
    manifest_path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_manifest(manifest_path)
