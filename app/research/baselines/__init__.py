"""Deterministic research baselines for chronological evaluation."""

from app.research.baselines.wr_receptions import (
    BASELINE_SPECS,
    BaselineDatasetError,
    BaselineName,
    BaselineSpec,
    build_wr_baseline_predictions,
)

__all__ = [
    "BASELINE_SPECS",
    "BaselineDatasetError",
    "BaselineName",
    "BaselineSpec",
    "build_wr_baseline_predictions",
]
