import json
from pathlib import Path

from app import cli
from app.research.nflverse import NflverseAdapter, fixture_csv_loader


FIXTURES = Path(__file__).parent / "fixtures" / "nflverse"


def test_cli_parser_preserves_legacy_and_adds_v05a_commands():
    assert cli.build_parser().parse_args(["--demo"]).demo is True
    ingest = cli.build_parser().parse_args(["ingest-once", "--provider", "mock"])
    assert ingest.command == "ingest-once"
    assert ingest.provider == "mock"
    download = cli.build_parser().parse_args(["data-download", "--seasons", "2023", "2024"])
    assert download.command == "data-download"
    assert download.seasons == [2023, 2024]


def test_build_dataset_cli_uses_complete_cache_without_network(
    tmp_path: Path, monkeypatch, capsys
):
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "raw" / "nflverse"
    adapter = NflverseAdapter(
        seasons=[2023, 2024],
        cache_dir=cache_dir,
        manifest_dir=data_dir / "manifests",
        loaders={
            "player_stats": fixture_csv_loader(FIXTURES / "player_stats.csv"),
            "schedules": fixture_csv_loader(FIXTURES / "schedules.csv"),
        },
    )
    adapter.download(["player_stats", "schedules"])
    monkeypatch.setattr(cli.settings, "nfl_data_dir", str(data_dir))
    monkeypatch.setattr(cli.settings, "nfl_cache_dir", str(cache_dir))
    monkeypatch.setattr(
        NflverseAdapter,
        "_loader",
        lambda self, contract: (_ for _ in ()).throw(AssertionError("network loader requested")),
    )
    output = data_dir / "processed" / "wr.parquet"

    cli.main([
        "build-wr-dataset", "--seasons", "2023", "2024", "--output", str(output)
    ])

    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 8
    assert len(payload["manifest_hash"]) == 64
    assert len(payload["dataset_hash"]) == 64
    assert output.exists()
    assert output.with_suffix(".manifest.json").exists()


def test_build_feature_cli_uses_complete_cache_without_network(
    tmp_path: Path, monkeypatch, capsys
):
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "raw" / "nflverse"
    adapter = NflverseAdapter(
        seasons=[2023, 2024],
        cache_dir=cache_dir,
        manifest_dir=data_dir / "manifests",
        loaders={
            "player_stats": fixture_csv_loader(FIXTURES / "player_stats.csv"),
            "schedules": fixture_csv_loader(FIXTURES / "schedules.csv"),
        },
    )
    adapter.download(["player_stats", "schedules"])
    monkeypatch.setattr(cli.settings, "nfl_data_dir", str(data_dir))
    monkeypatch.setattr(cli.settings, "nfl_cache_dir", str(cache_dir))
    monkeypatch.setattr(
        NflverseAdapter,
        "_loader",
        lambda self, contract: (_ for _ in ()).throw(AssertionError("network loader requested")),
    )
    output = data_dir / "processed" / "wr_features.parquet"

    cli.main([
        "build-wr-features", "--seasons", "2023", "2024", "--output", str(output)
    ])

    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 8
    assert payload["features"] > 40
    assert len(payload["content_hash"]) == 64
    assert output.exists()
    assert output.with_suffix(".manifest.json").exists()
