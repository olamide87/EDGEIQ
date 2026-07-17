import argparse
import asyncio
import json
from pathlib import Path
from collections.abc import Sequence

from sqlalchemy import select

from app.line_shopper import rank_offers
from app.models import Market, Side
from app.providers.mock import MockOddsProvider
from app.providers.theoddsapi import TheOddsAPIProvider
from app.storage import append_snapshot
from app.database import SessionLocal
from app.db_models import ProviderHealth
from app.services.ingestion import IngestionService
from app.config import settings
from app.research.dataset import build_wr_training_table, write_training_dataset
from app.research.manifest import load_manifest
from app.research.nflverse import DATASET_CONTRACTS, DEFAULT_DATASETS, NflverseAdapter


async def run(provider_name: str) -> None:
    provider = MockOddsProvider() if provider_name == "mock" else TheOddsAPIProvider()
    offers = await provider.fetch_nfl_player_props()
    append_snapshot(offers)

    # Demo query; the next version will expose filters through FastAPI/UI.
    player = "Amon-Ra St. Brown"
    board = rank_offers(
        offers,
        player=player,
        market=Market.PLAYER_RECEPTIONS,
        side=Side.OVER,
    )

    if not board.offers:
        print("No matching offers found.")
        return

    print(f"\nBest available lines: {board.player} — {board.market.value} {board.side.value}\n")
    for ranked in board.offers:
        o = ranked.offer
        line_text = "" if o.line is None else f"{o.line:g}"
        print(
            f"{ranked.rank}. {o.bookmaker:15} "
            f"{o.side.value.upper()} {line_text:>5} "
            f"{o.american_odds:+d} "
            f"(implied {ranked.implied_probability:.1%})"
        )


async def ingest_once(provider_name: str) -> None:
    result = await IngestionService().run_provider(provider_name)
    print(json.dumps({
        "job_id": result.job_id,
        "correlation_id": result.correlation_id,
        "provider": result.provider,
        "status": result.status,
        "row_count": result.row_count,
        "duplicate_suppressed": result.duplicate_suppressed,
    }))


def show_provider_health() -> None:
    with SessionLocal() as session:
        rows = session.scalars(select(ProviderHealth).order_by(ProviderHealth.provider)).all()
        print(json.dumps([{
            "provider": row.provider,
            "status": row.status,
            "consecutive_failures": row.consecutive_failures,
            "average_latency_ms": float(row.average_latency_ms),
            "records_returned": row.records_returned,
        } for row in rows]))


def _seasons(values: list[int] | None) -> list[int]:
    return sorted(set(values or settings.configured_nfl_seasons))


def download_data(seasons: list[int] | None, datasets: list[str], force: bool) -> None:
    adapter = NflverseAdapter(
        seasons=_seasons(seasons),
        cache_dir=Path(settings.nfl_cache_dir),
        manifest_dir=Path(settings.nfl_data_dir) / "manifests",
    )
    _, manifest_path, manifest = adapter.download(datasets, force=force)
    print(json.dumps({
        "manifest": str(manifest_path),
        "manifest_hash": manifest.manifest_hash,
        "seasons": manifest.seasons,
        "datasets": datasets,
        "files": len(manifest.files),
    }))


def show_data_manifest(path: Path | None) -> None:
    if path is None:
        manifests = sorted(
            (Path(settings.nfl_data_dir) / "manifests").glob("nflverse-*.json"),
            key=lambda candidate: candidate.stat().st_mtime,
        )
        if not manifests:
            raise SystemExit("No nflverse manifests found. Run data-download first.")
        path = manifests[-1]
    manifest = load_manifest(path)
    print(manifest.model_dump_json(indent=2))


def build_wr_dataset(seasons: list[int] | None, output: Path) -> None:
    adapter = NflverseAdapter(
        seasons=_seasons(seasons),
        cache_dir=Path(settings.nfl_cache_dir),
        manifest_dir=Path(settings.nfl_data_dir) / "manifests",
    )
    frames, _, source_manifest = adapter.download(["player_stats", "schedules"])
    table = build_wr_training_table(frames["player_stats"], frames["schedules"])
    result = write_training_dataset(
        table,
        output_path=output,
        source_manifest_hash=source_manifest.manifest_hash,
    )
    print(json.dumps({
        "dataset": str(result.path),
        "manifest": str(result.manifest_path),
        "manifest_hash": result.manifest_hash,
        "dataset_hash": result.dataset_hash,
        "file_hash": result.file_hash,
        "rows": result.row_count,
    }))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--provider", choices=["mock", "theoddsapi"], default="mock")
    subparsers = parser.add_subparsers(dest="command")

    ingest_parser = subparsers.add_parser("ingest-once")
    ingest_parser.add_argument("--provider", choices=["mock", "theoddsapi"], default="mock")
    subparsers.add_parser("provider-health")

    download_parser = subparsers.add_parser("data-download")
    download_parser.add_argument("--seasons", type=int, nargs="+")
    download_parser.add_argument(
        "--datasets", nargs="+", choices=sorted(DATASET_CONTRACTS), default=list(DEFAULT_DATASETS)
    )
    download_parser.add_argument("--force", action="store_true")

    manifest_parser = subparsers.add_parser("data-manifest")
    manifest_parser.add_argument("--path", type=Path)

    dataset_parser = subparsers.add_parser("build-wr-dataset")
    dataset_parser.add_argument("--seasons", type=int, nargs="+")
    dataset_parser.add_argument(
        "--output", type=Path, default=Path("data/processed/wr_receptions.parquet")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "ingest-once":
        asyncio.run(ingest_once(args.provider))
    elif args.command == "provider-health":
        show_provider_health()
    elif args.command == "data-download":
        download_data(args.seasons, args.datasets, args.force)
    elif args.command == "data-manifest":
        show_data_manifest(args.path)
    elif args.command == "build-wr-dataset":
        build_wr_dataset(args.seasons, args.output)
    else:
        asyncio.run(run("mock" if args.demo else args.provider))


if __name__ == "__main__":
    main()
