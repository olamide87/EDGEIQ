from datetime import datetime, timedelta, timezone
import json
import math
import runpy

import polars as pl
import pytest
from pydantic import ValidationError

from app.research.baselines import build_wr_baseline_predictions
from app.research.evaluation import (
    BaselineEvaluationConfig,
    EvaluationPeriod,
    ReproducibilityMetadata,
    ResearchDecision,
    evaluate_wr_baselines,
    fit_and_evaluate_wr_poisson,
    write_learned_scorecard,
)
from app.research.features import (
    build_wr_feature_table,
    canonical_feature_content_hash,
)
from app.research.models import (
    DEFAULT_WR_POISSON_FEATURES,
    ModelFitError,
    ModelNotFittedError,
    ModelTrainingContext,
    WRPoissonConfig,
    WRPoissonModel,
    chronological_model_split,
)
from app.research.models.wr_receptions import _solve_linear_system
from feature_store.registry import WR_FEATURE_REGISTRY


def _context() -> ModelTrainingContext:
    return ModelTrainingContext(
        dataset_manifest_hash="a" * 64,
        feature_registry_hash=WR_FEATURE_REGISTRY.registry_hash,
        canonical_feature_table_hash="c" * 64,
        git_commit_sha="b" * 40,
    )


def _training_data(rows: int = 30) -> pl.DataFrame:
    kickoff = datetime(2023, 9, 1)
    return pl.DataFrame(
        {
            "kickoff": [kickoff + timedelta(days=index) for index in range(rows)],
            "game_id": [f"game-{index:02d}" for index in range(rows)],
            "source_player_id": [f"player-{index % 5}" for index in range(rows)],
            "receptions_roll3": [float(1 + index % 7) for index in range(rows)],
            "targets_roll3": [float(3 + index % 9) for index in range(rows)],
            "home_indicator": [float(index % 2) for index in range(rows)],
            "games_played_before": [float(index // 5) for index in range(rows)],
            "actual_receptions": [float(1 + (index * 3) % 8) for index in range(rows)],
        }
    )


def _fitted_model(frame: pl.DataFrame | None = None) -> WRPoissonModel:
    return WRPoissonModel().fit(
        _training_data() if frame is None else frame,
        context=_context(),
    )


def _feature_table() -> pl.DataFrame:
    namespace = runpy.run_path("tests/test_wr_features.py")
    stats, _, training = namespace["_feature_inputs"]()
    return build_wr_feature_table(training, stats)


def _evaluation_config() -> BaselineEvaluationConfig:
    return BaselineEvaluationConfig(
        training_period=EvaluationPeriod(
            start=datetime(2023, 9, 1, tzinfo=timezone.utc),
            end=datetime(2023, 10, 1, 23, 59, tzinfo=timezone.utc),
        ),
        validation_period=EvaluationPeriod(
            start=datetime(2024, 9, 8, tzinfo=timezone.utc),
            end=datetime(2024, 9, 16, tzinfo=timezone.utc),
        ),
        minimum_evaluation_rows=1,
    )


def _reproducibility(features: pl.DataFrame) -> ReproducibilityMetadata:
    return ReproducibilityMetadata(
        dataset_manifest_hash="a" * 64,
        feature_registry_hash=WR_FEATURE_REGISTRY.registry_hash,
        canonical_feature_table_hash=canonical_feature_content_hash(features),
        git_commit_sha="b" * 40,
    )


def test_fit_and_predict_are_deterministic_and_preserve_feature_order():
    training = _training_data()
    first = _fitted_model(training)
    second = _fitted_model(training.reverse())
    prediction_frame = training.select(reversed(DEFAULT_WR_POISSON_FEATURES))

    assert first.state == second.state
    assert first.predict(prediction_frame) == second.predict(prediction_frame)
    assert first.state.config.feature_names == DEFAULT_WR_POISSON_FEATURES
    assert first.state.training.converged is True
    assert first.state.training.row_count == training.height


def test_predict_requires_fitted_state_and_all_finite_features():
    model = WRPoissonModel()
    with pytest.raises(ModelNotFittedError, match="has not been fitted"):
        model.predict(_training_data().head(1))

    model = _fitted_model()
    with pytest.raises(ModelFitError, match="missing required columns: targets_roll3"):
        model.predict(_training_data().head(1).drop("targets_roll3"))
    for invalid in (math.nan, math.inf, "not-a-number"):
        frame = _training_data().head(1).with_columns(
            pl.lit(invalid).alias("targets_roll3")
        )
        with pytest.raises(ModelFitError, match="finite numeric"):
            model.predict(frame)


def test_fit_rejects_missing_duplicate_nonfinite_and_disabled_features():
    training = _training_data()
    with pytest.raises(ModelFitError, match="missing required columns"):
        WRPoissonModel().fit(training.drop("receptions_roll3"), context=_context())
    with pytest.raises(ModelFitError, match="duplicate player-game"):
        WRPoissonModel().fit(
            pl.concat([training, training.head(1)]),
            context=_context(),
        )
    with pytest.raises(ModelFitError, match="finite numeric"):
        WRPoissonModel().fit(
            training.with_columns(
                pl.when(pl.int_range(pl.len()) == 0)
                .then(math.inf)
                .otherwise(pl.col("targets_roll3"))
                .alias("targets_roll3")
            ),
            context=_context(),
        )
    with pytest.raises(ValidationError, match="not enabled"):
        WRPoissonConfig(feature_names=("same_game_targets",))


def test_wr_model_rejects_non_reception_target():
    with pytest.raises(ValidationError, match="requires target_column"):
        WRPoissonConfig(target_column="game_week")


@pytest.mark.parametrize(
    ("value", "message"),
    ((-1, "negative"), (1.5, "whole-number"), (math.nan, "finite numeric")),
)
def test_fit_rejects_invalid_targets(value: object, message: str):
    frame = _training_data().with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value))
        .otherwise(pl.col("actual_receptions"))
        .alias("actual_receptions")
    )
    with pytest.raises(ModelFitError, match=message):
        WRPoissonModel().fit(frame, context=_context())


def test_predictions_are_finite_nonnegative_and_inputs_are_not_mutated():
    training = _training_data()
    training_rows = training.to_dicts()
    training_schema = training.schema
    model = _fitted_model(training)
    prediction_frame = training.head(4)
    prediction_rows = prediction_frame.to_dicts()
    prediction_schema = prediction_frame.schema

    predictions = model.predict(prediction_frame)

    assert all(math.isfinite(value) and value >= 0 for value in predictions)
    assert training.to_dicts() == training_rows
    assert training.schema == training_schema
    assert prediction_frame.to_dicts() == prediction_rows
    assert prediction_frame.schema == prediction_schema


def test_zero_variance_features_are_deterministic():
    training = _training_data().with_columns(
        *(pl.lit(1.0).alias(name) for name in DEFAULT_WR_POISSON_FEATURES)
    )
    first = _fitted_model(training)
    second = _fitted_model(training.reverse())
    expected_mean = training.get_column("actual_receptions").mean()

    assert first.state.feature_scales == (1.0, 1.0, 1.0, 1.0)
    assert first.state.coefficients == pytest.approx((0.0, 0.0, 0.0, 0.0))
    assert first.state == second.state
    assert first.predict(training.head(3)) == second.predict(training.head(3))
    assert first.predict(training.head(1))[0] == pytest.approx(expected_mean)


def test_large_features_and_exponential_limits_cannot_overflow_silently():
    large_training = _training_data().with_columns(
        *(
            (pl.col(name) * 1e100).alias(name)
            for name in DEFAULT_WR_POISSON_FEATURES
        )
    )
    large_model = _fitted_model(large_training)
    large_predictions = large_model.predict(large_training.head(3))
    model = _fitted_model()
    extreme = _training_data().head(1).with_columns(
        pl.lit(1e300).alias("receptions_roll3"),
        pl.lit(1e300).alias("targets_roll3"),
    )
    prediction = model.predict(extreme)[0]

    assert all(math.isfinite(value) and value >= 0 for value in large_predictions)
    assert math.isfinite(prediction)
    assert prediction >= 0
    with pytest.raises(ModelFitError, match="exceeds the configured safe limit"):
        WRPoissonModel(WRPoissonConfig(linear_predictor_limit=1)).fit(
            _training_data(),
            context=_context(),
        )
    with pytest.raises(ValidationError, match="less than or equal to 700"):
        WRPoissonConfig(linear_predictor_limit=701)


def test_solver_reports_non_convergence_and_singular_systems():
    config = WRPoissonConfig(max_iterations=1, tolerance=1e-30)
    with pytest.raises(ModelFitError, match="did not converge"):
        WRPoissonModel(config).fit(_training_data(), context=_context())

    with pytest.raises(ModelFitError, match="singular Hessian"):
        _solve_linear_system(
            [[1.0, 2.0], [2.0, 4.0]],
            [1.0, 2.0],
            epsilon=1e-10,
        )


def test_chronological_split_is_stable_and_rejects_overlapping_periods():
    frame = _training_data(12).reverse()
    training_period = EvaluationPeriod(
        start=datetime(2023, 9, 1, tzinfo=timezone.utc),
        end=datetime(2023, 9, 6, tzinfo=timezone.utc),
    )
    evaluation_period = EvaluationPeriod(
        start=datetime(2023, 9, 7, tzinfo=timezone.utc),
        end=datetime(2023, 9, 12, tzinfo=timezone.utc),
    )

    training, evaluation = chronological_model_split(
        frame,
        training_period=training_period,
        evaluation_period=evaluation_period,
    )

    assert training.get_column("game_id").to_list() == [
        f"game-{index:02d}" for index in range(6)
    ]
    assert evaluation.get_column("game_id").to_list() == [
        f"game-{index:02d}" for index in range(6, 12)
    ]
    with pytest.raises(ModelFitError, match="must end before"):
        chronological_model_split(
            frame,
            training_period=training_period,
            evaluation_period=training_period,
        )
    naive_period = type(
        "NaivePeriod",
        (),
        {"start": datetime(2023, 9, 1), "end": datetime(2023, 9, 6)},
    )()
    with pytest.raises(ModelFitError, match="timezone-aware"):
        chronological_model_split(
            frame,
            training_period=naive_period,
            evaluation_period=evaluation_period,
        )


def test_model_fingerprint_and_serialization_are_canonical():
    first = _fitted_model()
    second = _fitted_model(_training_data().reverse())
    restored = WRPoissonModel.from_json(first.to_json())
    serialized = first.to_json()

    assert first.fingerprint == second.fingerprint == restored.fingerprint
    assert first.state.training.training_data_hash == second.state.training.training_data_hash
    assert restored.predict(_training_data().head(3)) == first.predict(
        _training_data().head(3)
    )
    assert "evaluated_at" not in serialized
    assert "captured_at" not in serialized
    assert "pytest" not in serialized

    tampered = json.loads(first.to_json())
    tampered["coefficients"][0] += 1
    with pytest.raises(ValidationError, match="fingerprint"):
        WRPoissonModel.from_json(json.dumps(tampered))


def test_learned_evaluation_uses_governed_metrics_and_strongest_baseline(tmp_path):
    features = _feature_table()
    evaluated_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    model, scorecard = fit_and_evaluate_wr_poisson(
        features,
        model_config=WRPoissonConfig(),
        evaluation_config=_evaluation_config(),
        reproducibility=_reproducibility(features),
        evaluated_at=evaluated_at,
    )

    assert scorecard.candidate.model_fingerprint == model.fingerprint
    assert model.state.training.row_count == 4
    assert scorecard.candidate.metrics.sample_count == scorecard.shared_cohort_size
    assert len(scorecard.candidate.calibration) == 10
    assert scorecard.candidate.comparison.iterations == 10_000
    assert scorecard.candidate.governed_comparison_baseline.value
    assert scorecard.candidate.candidate_kind == "learned_model"
    assert scorecard.candidate.model_name not in scorecard.baseline_candidates
    assert scorecard.governance_version == "1.0"
    assert scorecard.evaluation_protocol_version == "1.0"
    assert scorecard.recommendation.decision is ResearchDecision.RESEARCH
    assert "cannot receive PROMOTE" in scorecard.recommendation.reasons[-1]

    path = write_learned_scorecard(scorecard, tmp_path / "learned-scorecard.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scorecard_hash"] == scorecard.scorecard_hash
    assert not path.with_suffix(".json.tmp").exists()


def test_learned_and_baselines_use_identical_held_out_rows():
    features = _feature_table().with_columns(
        pl.when(
            (pl.col("season") == 2024)
            & (pl.col("week") == 2)
            & (pl.col("source_player_id") == "P1")
        )
        .then(None)
        .otherwise(pl.col("rest_days"))
        .alias("rest_days")
    )
    model_config = WRPoissonConfig(
        feature_names=(
            "receptions_roll3",
            "targets_roll3",
            "rest_days",
            "games_played_before",
        )
    )
    evaluated_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    metadata = _reproducibility(features)
    _, scorecard = fit_and_evaluate_wr_poisson(
        features,
        model_config=model_config,
        evaluation_config=_evaluation_config(),
        reproducibility=metadata,
        evaluated_at=evaluated_at,
    )
    evaluation_keys = features.filter(
        (pl.col("kickoff") >= datetime(2024, 9, 8))
        & (pl.col("kickoff") <= datetime(2024, 9, 16))
        & pl.all_horizontal(
            *(pl.col(name).is_not_null() for name in model_config.feature_names)
        )
    ).select("source_player_id", "game_id")
    baseline_scorecard = evaluate_wr_baselines(
        features,
        config=_evaluation_config(),
        reproducibility=metadata,
        evaluated_at=evaluated_at,
        evaluation_keys=evaluation_keys,
    )

    assert scorecard.baseline_scorecard_hash == baseline_scorecard.scorecard_hash
    assert scorecard.shared_cohort_size == 2
    assert scorecard.candidate.metrics.sample_count == 2
    assert all(result.metrics.sample_count == 2 for result in baseline_scorecard.results)
    assert (
        scorecard.candidate.governed_comparison_baseline
        is baseline_scorecard.strongest_eligible_baseline
    )


def test_learned_evaluation_reuses_selector_and_forces_research(monkeypatch):
    import app.research.evaluation.learned as learned

    calls = 0
    original = learned.select_strongest_baseline

    def tracked_selector(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(learned, "select_strongest_baseline", tracked_selector)
    features = _feature_table()
    _, scorecard = learned.fit_and_evaluate_wr_poisson(
        features,
        model_config=WRPoissonConfig(),
        evaluation_config=_evaluation_config(),
        reproducibility=_reproducibility(features),
    )
    all_metric_gates_pass = learned.LearnedMetricGates(
        lower_mae=True,
        statistically_significant_mae_improvement=True,
        equal_or_better_calibration=True,
        improved_poisson_deviance=True,
    )

    assert calls == 1
    assert scorecard.recommendation.decision is ResearchDecision.RESEARCH
    assert (
        learned._learned_recommendation(all_metric_gates_pass).decision
        is ResearchDecision.RESEARCH
    )


def test_learned_scorecard_is_deterministic_and_does_not_change_baselines():
    features = _feature_table()
    baseline_before = build_wr_baseline_predictions(features)
    first_model, first = fit_and_evaluate_wr_poisson(
        features,
        model_config=WRPoissonConfig(),
        evaluation_config=_evaluation_config(),
        reproducibility=_reproducibility(features),
        evaluated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    second_model, second = fit_and_evaluate_wr_poisson(
        features,
        model_config=WRPoissonConfig(),
        evaluation_config=_evaluation_config(),
        reproducibility=_reproducibility(features),
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert first_model.fingerprint == second_model.fingerprint
    assert first.scorecard_hash == second.scorecard_hash
    assert first.candidate == second.candidate
    assert build_wr_baseline_predictions(features).equals(baseline_before)
