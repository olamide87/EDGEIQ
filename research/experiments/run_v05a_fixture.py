"""Run the complete v0.5A pipeline against project-authored offline fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.research.dataset import build_wr_training_table, write_training_dataset
from app.research.manifest import sha256_file
from app.research.nflverse import NflverseAdapter, fixture_csv_loader


FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "nflverse"


def run(output_root: Path) -> dict[str, object]:
    adapter = NflverseAdapter(
        seasons=[2023, 2024],
        cache_dir=output_root / "raw" / "nflverse",
        manifest_dir=output_root / "manifests",
        loaders={
            "player_stats": fixture_csv_loader(FIXTURE_ROOT / "player_stats.csv"),
            "schedules": fixture_csv_loader(FIXTURE_ROOT / "schedules.csv"),
        },
    )
    frames, manifest_path, manifest = adapter.download(["player_stats", "schedules"])
    table = build_wr_training_table(frames["player_stats"], frames["schedules"])
    result = write_training_dataset(
        table,
        output_path=output_root / "processed" / "wr_receptions.parquet",
        source_manifest_hash=manifest.manifest_hash,
    )
    return {
        "row_count": result.row_count,
        "schema": {name: str(dtype) for name, dtype in table.schema.items()},
        "manifest_hash": manifest.manifest_hash,
        "processed_manifest_hash": result.manifest_hash,
        "manifest_path": str(manifest_path),
        "source_file_hashes": [item.sha256 for item in manifest.files],
        "processed_content_hash": result.dataset_hash,
        "processed_file_hash": sha256_file(result.path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
