from __future__ import annotations

from typing import Any

import polars as pl

from app.research.features import FEATURE_COLUMNS, validate_wr_feature_table
from feature_store.registry import WR_FEATURE_REGISTRY


def audit_wr_feature_table(
    frame: pl.DataFrame,
    *,
    source_hashes: dict[str, str] | None = None,
    output_hash: str | None = None,
) -> dict[str, Any]:
    validate_wr_feature_table(frame)
    features: dict[str, Any] = {}
    for name in FEATURE_COLUMNS:
        series = frame.get_column(name)
        non_null = series.drop_nulls()
        features[name] = {
            "null_rate": series.null_count() / frame.height if frame.height else 0.0,
            "min": non_null.min() if len(non_null) else None,
            "max": non_null.max() if len(non_null) else None,
            "mean": non_null.mean() if len(non_null) else None,
            "median": non_null.median() if len(non_null) else None,
            "first_available_game": (
                frame.filter(pl.col(name).is_not_null()).get_column("game_id").first()
                if len(non_null) else None
            ),
        }
    tiers = (
        frame.with_columns(
            pl.when(pl.col("games_played_before") == 0).then(pl.lit("rookie_or_no_history"))
            .when(pl.col("games_played_before") < 3).then(pl.lit("one_to_two"))
            .when(pl.col("games_played_before") < 6).then(pl.lit("three_to_five"))
            .otherwise(pl.lit("six_plus"))
            .alias("history_tier")
        )
        .group_by("history_tier")
        .len()
        .sort("history_tier")
    )
    seasons = frame.group_by("season").len().sort("season")
    return {
        "row_count": frame.height,
        "feature_count": len(FEATURE_COLUMNS),
        "registry_version": WR_FEATURE_REGISTRY.version,
        "registry_hash": WR_FEATURE_REGISTRY.registry_hash,
        "source_hashes": dict(sorted((source_hashes or {}).items())),
        "output_hash": output_hash,
        "coverage_by_season": {
            str(row["season"]): row["len"] for row in seasons.iter_rows(named=True)
        },
        "coverage_by_history_tier": {
            row["history_tier"]: row["len"] for row in tiers.iter_rows(named=True)
        },
        "leakage_validation": {
            "status": "NOT_RUN",
            "checks_run": [],
            "reason": (
                "A materialized feature table cannot establish causal leakage invariance "
                "without rebuilding from controlled current-game and future-game mutations."
            ),
        },
        "features": features,
    }
