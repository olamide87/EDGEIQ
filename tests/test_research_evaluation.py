from datetime import datetime, timezone
import json
import runpy

import polars as pl
import pytest

from app.research.evaluation import (
    BaselineEvaluationConfig,
    EvaluationPeriod,
    ReproducibilityMetadata,
    ResearchDecision,
    calculate_metrics,
    evaluate_wr_baselines,
    paired_mae_bootstrap,
    poisson_over_probability,
    write_baseline_scorecard,
)
from app.research.features import (
    build_wr_feature_table,
    canonical_feature_content_hash,
)
from feature_store.registry import WR_FEATURE_REGISTRY


def _feature_table() -> pl.DataFrame:
    namespace = runpy.run_path("tests/test_wr_features.py")
    stats, _, training = namespace["_feature_inputs"]()
    return build_wr_feature_table(training, stats)


def _config() -> BaselineEvaluationConfig:
    return BaselineEvaluationConfig(
        training_period=EvaluationPeriod(
            start=datetime(2023, 9, 1, tzinfo=timezone.utc),
            end=datetime(2023, 9, 16, tzinfo=timezone.utc),
        ),
        validation_period=EvaluationPeriod(
            start=datetime(2023, 9, 17, tzinfo=timezone.utc),
            end=datetime(2024, 12, 31, tzinfo=timezone.utc),
        ),
        calibration_bins=5,
        minimum_evaluation_rows=1,
    )


def _metadata(features: pl.DataFrame) -> ReproducibilityMetadata:
    return ReproducibilityMetadata(
        dataset_manifest_hash="a" * 64,
        feature_registry_hash=WR_FEATURE_REGISTRY.registry_hash,
        canonical_feature_table_hash=canonical_feature_content_hash(features),
        git_commit_sha="b" * 40,
    )


def test_count_metrics_calibration_and_poisson_probability_are_explicit():
    metrics, bins = calculate_metrics(
        [1.0, 3.0, 5.0],
        [2.0, 3.0, 4.0],
        coverage=0.75,
        calibration_line=2.5,
        calibration_bins=5,
        poisson_epsilon=1e-12,
    )

    assert metrics.mae == pytest.approx(2 / 3)
    assert metrics.rmse == pytest.approx((2 / 3) ** 0.5)
    assert metrics.bias == 0
    assert metrics.coverage == 0.75
    assert metrics.sample_count == 3
    assert 0 <= metrics.calibration_error <= 1
    assert len(bins) == 5
    assert sum(item.count for item in bins) == 3
    assert poisson_over_probability(0, 4.5) == 0
    assert 0 < poisson_over_probability(4, 4.5) < 1


def test_paired_bootstrap_is_seeded_and_reports_significant_improvement():
    actuals = [1.0, 2.0, 3.0, 4.0] * 4
    reference = [value + 3 for value in actuals]
    candidate = list(actuals)
    first = paired_mae_bootstrap(
        actuals,
        reference,
        candidate,
        iterations=1_000,
        confidence_level=0.95,
        random_seed=42,
    )
    second = paired_mae_bootstrap(
        actuals,
        reference,
        candidate,
        iterations=1_000,
        confidence_level=0.95,
        random_seed=42,
    )

    assert first == second
    assert first.difference == 3
    assert first.confidence_lower == 3
    assert first.effect_size == 1
    assert first.effect_size_definition == "relative_mae_improvement"
    assert first.statistically_significant_improvement is True


def test_scorecard_is_deterministic_and_contains_governed_research_artifacts(tmp_path):
    features = _feature_table()
    evaluated_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    first = evaluate_wr_baselines(
        features,
        config=_config(),
        reproducibility=_metadata(features),
        evaluated_at=evaluated_at,
    )
    second = evaluate_wr_baselines(
        features,
        config=_config(),
        reproducibility=_metadata(features),
        evaluated_at=evaluated_at.replace(hour=1),
    )

    assert first.scorecard_hash == second.scorecard_hash
    assert first.configuration_hash == _config().config_hash
    assert first.shared_cohort_size > 0
    assert len(first.results) == 7
    assert sum(result.status == "STRONGEST_BASELINE" for result in first.results) == 1
    assert all(
        result.metrics.sample_count == first.shared_cohort_size
        for result in first.results
    )
    assert all(len(result.calibration) == 5 for result in first.results)
    assert first.recommendation.decision is ResearchDecision.RESEARCH
    assert set(first.failure_report.segments) == {
        "rookies",
        "veterans",
        "low_volume",
        "high_volume",
        "early_season",
        "late_season",
        "home",
        "away",
        "after_bye",
    }
    assert first.failure_report.missing_feature_frequencies
    assert first.failure_report.disabled_features

    path = write_baseline_scorecard(first, tmp_path / "scorecard.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scorecard_hash"] == first.scorecard_hash
    assert not path.with_suffix(".json.tmp").exists()


def test_scorecard_rejects_reproducibility_mismatch_and_empty_validation_cohort():
    features = _feature_table()
    metadata = _metadata(features).model_copy(
        update={"canonical_feature_table_hash": "0" * 64}
    )
    with pytest.raises(ValueError, match="Canonical feature-table hash"):
        evaluate_wr_baselines(features, config=_config(), reproducibility=metadata)

    empty_config = _config().model_copy(
        update={
            "validation_period": EvaluationPeriod(
                start=datetime(2030, 1, 1, tzinfo=timezone.utc),
                end=datetime(2030, 12, 31, tzinfo=timezone.utc),
            )
        }
    )
    with pytest.raises(ValueError, match="Shared baseline cohort"):
        evaluate_wr_baselines(
            features,
            config=empty_config,
            reproducibility=_metadata(features),
        )
