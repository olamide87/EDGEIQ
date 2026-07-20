"""Build and audit the committed offline WR feature fixture without model training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.research.dataset import build_wr_training_table
from app.research.feature_audit import audit_wr_feature_table
from app.research.features import build_wr_feature_table, write_wr_feature_dataset
from app.research.manifest import sha256_file


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "nflverse"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research" / "reports" / "v05b_fixture_features.parquet",
    )
    args = parser.parse_args()
    stats_path = FIXTURE_DIR / "player_stats.csv"
    schedules_path = FIXTURE_DIR / "schedules.csv"
    player_stats = pl.read_csv(stats_path)
    schedules = pl.read_csv(schedules_path)
    training = build_wr_training_table(player_stats, schedules)
    features = build_wr_feature_table(training, player_stats)
    source_hashes = {
        "player_stats_fixture": sha256_file(stats_path),
        "schedules_fixture": sha256_file(schedules_path),
    }
    result = write_wr_feature_dataset(
        features,
        output_path=args.output,
        source_manifest_hashes=source_hashes,
    )
    report = audit_wr_feature_table(
        features,
        source_hashes=source_hashes,
        output_hash=result.content_hash,
    )
    report.update({
        "dataset_path": str(result.path),
        "manifest_path": str(result.manifest_path),
        "manifest_hash": result.manifest_hash,
        "file_hash": result.file_hash,
    })
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
