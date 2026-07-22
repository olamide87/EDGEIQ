from datetime import datetime, timedelta, timezone
import json
import runpy

import polars as pl
import pytest
from pydantic import ValidationError

from app.research.evaluation import (
    BaselineEvaluationConfig,
    ComparisonMetric,
    EvaluationPeriod,
    ReproducibilityMetadata,
    ResearchDecision,
    RollingEvaluationConfig,
    RollingEvaluationWindow,
    evaluate_wr_poisson_rolling,
    render_rolling_research_report,
    write_rolling_research_report,
    write_rolling_scorecard,
)
from app.research.evaluation.governance import EvaluationProtocol
from app.research.features import canonical_feature_content_hash
from app.research.models import WRPoissonConfig
from feature_store.registry import WR_FEATURE_REGISTRY


def _feature_table() -> pl.DataFrame:
    namespace = runpy.run_path("tests/test_wr_models.py")
    return namespace["_feature_table"]()


def _rolling_feature_table() -> pl.DataFrame:
    features = _feature_table()
    source = features.filter(
        (pl.col("season") == 2024) & (pl.col("week") == 2)
    )
    additions = []
    for week in (3, 4):
        additions.append(
            source.with_columns(
                pl.lit(week).cast(source.schema["week"]).alias("week"),
                pl.lit(week).cast(source.schema["game_week"]).alias("game_week"),
                pl.lit(f"2024_{week:02d}_DAL_PHI").alias("game_id"),
                (pl.col("kickoff") + timedelta(days=7 * (week - 2))).alias("kickoff"),
                (pl.col("actual_receptions") + (week % 2)).alias(
                    "actual_receptions"
                ),
            )
        )
    return pl.concat([features, *additions]).sort(
        "kickoff", "game_id", "source_player_id"
    )


def _metadata(features: pl.DataFrame) -> ReproducibilityMetadata:
    return ReproducibilityMetadata(
        dataset_manifest_hash="a" * 64,
        feature_registry_hash=WR_FEATURE_REGISTRY.registry_hash,
        canonical_feature_table_hash=canonical_feature_content_hash(features),
        git_commit_sha="b" * 40,
    )


def _rolling_config() -> RollingEvaluationConfig:
    baseline = BaselineEvaluationConfig(
        training_period=EvaluationPeriod(
            start=datetime(2023, 9, 1, tzinfo=timezone.utc),
            end=datetime(2023, 9, 30, tzinfo=timezone.utc),
        ),
        validation_period=EvaluationPeriod(
            start=datetime(2023, 10, 1, tzinfo=timezone.utc),
            end=datetime(2023, 10, 2, tzinfo=timezone.utc),
        ),
        minimum_evaluation_rows=1,
        protocol=EvaluationProtocol(bootstrap_iterations=30, random_seed=23),
    )
    return RollingEvaluationConfig(
        training_start=datetime(2023, 9, 1, tzinfo=timezone.utc),
        windows=(
            RollingEvaluationWindow(
                window_id="2024-week-03",
                evaluation_period=EvaluationPeriod(
                    start=datetime(2024, 9, 22, tzinfo=timezone.utc),
                    end=datetime(2024, 9, 23, tzinfo=timezone.utc),
                ),
            ),
            RollingEvaluationWindow(
                window_id="2024-week-04",
                evaluation_period=EvaluationPeriod(
                    start=datetime(2024, 9, 29, tzinfo=timezone.utc),
                    end=datetime(2024, 9, 30, tzinfo=timezone.utc),
                ),
            ),
        ),
        baseline_config=baseline,
    )


def test_rolling_config_rejects_unordered_overlapping_and_duplicate_windows():
    config = _rolling_config()
    with pytest.raises(ValidationError, match="canonical chronological order"):
        RollingEvaluationConfig(
            training_start=config.training_start,
            windows=tuple(reversed(config.windows)),
            baseline_config=config.baseline_config,
        )
    duplicate = config.windows[0].model_copy(
        update={"evaluation_period": config.windows[1].evaluation_period}
    )
    with pytest.raises(ValidationError, match="unique"):
        RollingEvaluationConfig(
            training_start=config.training_start,
            windows=(config.windows[0], duplicate),
            baseline_config=config.baseline_config,
        )
    overlap = RollingEvaluationWindow(
        window_id="overlap",
        evaluation_period=EvaluationPeriod(
            start=config.windows[0].evaluation_period.end,
            end=datetime(2024, 9, 24, tzinfo=timezone.utc),
        ),
    )
    with pytest.raises(ValidationError, match="must not overlap"):
        RollingEvaluationConfig(
            training_start=config.training_start,
            windows=(config.windows[0], overlap),
            baseline_config=config.baseline_config,
        )


def test_rolling_evaluation_is_expanding_aligned_and_research_only(tmp_path):
    features = _rolling_feature_table()
    config = _rolling_config()
    evaluated_at = datetime(2026, 7, 21, tzinfo=timezone.utc)

    first = evaluate_wr_poisson_rolling(
        features,
        model_config=WRPoissonConfig(),
        rolling_config=config,
        reproducibility=_metadata(features),
        evaluated_at=evaluated_at,
    )
    second = evaluate_wr_poisson_rolling(
        features,
        model_config=WRPoissonConfig(),
        rolling_config=config,
        reproducibility=_metadata(features),
        evaluated_at=evaluated_at.replace(hour=1),
    )

    assert first.scorecard_hash == second.scorecard_hash
    assert first.windows == second.windows
    assert first.recommendation.decision is ResearchDecision.RESEARCH
    assert len(first.windows) == 2
    assert first.windows[0].training_row_count < first.windows[1].training_row_count
    assert all(
        window.training_period.end < window.evaluation_period.start
        for window in first.windows
    )
    assert all(
        window.shared_cohort_size == window.learned_metrics.sample_count
        == window.baseline_metrics.sample_count
        for window in first.windows
    )
    assert all(len(window.shared_cohort_hash) == 64 for window in first.windows)
    assert all(len(window.baseline_scorecard_hash) == 64 for window in first.windows)
    assert all(
        tuple(item.metric for item in window.metric_differences)
        == tuple(ComparisonMetric)
        for window in first.windows
    )
    assert first.aggregate_learned_metrics.sample_count == sum(
        window.shared_cohort_size for window in first.windows
    )
    assert tuple(item.metric for item in first.aggregate_confidence_intervals) == tuple(
        ComparisonMetric
    )
    assert all(item.iterations == 30 for item in first.aggregate_confidence_intervals)
    weighted_window_mae = sum(
        window.learned_metrics.mae * window.shared_cohort_size
        for window in first.windows
    ) / first.aggregate_learned_metrics.sample_count
    assert first.aggregate_learned_metrics.mae == pytest.approx(weighted_window_mae)
    assert tuple(item.feature_name for item in first.coefficient_stability) == (
        WRPoissonConfig().feature_names
    )

    path = write_rolling_scorecard(first, tmp_path / "rolling.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scorecard_hash"] == first.scorecard_hash
    assert not path.with_suffix(".json.tmp").exists()


def test_rolling_evaluation_rejects_reproducibility_mismatch():
    features = _feature_table()
    metadata = _metadata(features).model_copy(
        update={"canonical_feature_table_hash": "0" * 64}
    )
    with pytest.raises(ValueError, match="Canonical feature-table hash"):
        evaluate_wr_poisson_rolling(
            features,
            model_config=WRPoissonConfig(),
            rolling_config=_rolling_config(),
            reproducibility=metadata,
        )


def test_markdown_report_is_deterministic_and_complete(tmp_path):
    features = _rolling_feature_table()
    first = evaluate_wr_poisson_rolling(
        features,
        model_config=WRPoissonConfig(),
        rolling_config=_rolling_config(),
        reproducibility=_metadata(features),
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    second = first.model_copy(
        update={"evaluated_at": datetime(2030, 1, 1, tzinfo=timezone.utc)}
    )

    first_report = render_rolling_research_report(first)
    second_report = render_rolling_research_report(second)

    assert first_report == second_report
    assert first_report.endswith("\n")
    assert "Status: RESEARCH" in first_report
    assert "mean_absolute_error" in first_report
    assert "mean_poisson_deviance" in first_report
    assert "Coefficient stability" in first_report
    assert all(window.window_id in first_report for window in first.windows)
    path = write_rolling_research_report(first, tmp_path / "rolling.md")
    assert path.read_text(encoding="utf-8") == first_report
    assert not path.with_suffix(".md.tmp").exists()
