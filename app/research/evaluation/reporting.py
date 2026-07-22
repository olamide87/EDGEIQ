"""Deterministic Markdown reporting for rolling WR research evaluation."""

from __future__ import annotations

from pathlib import Path

from app.research.evaluation.rolling import RollingEvaluationScorecard


def _number(value: float) -> str:
    return f"{value:.6f}"


def render_rolling_research_report(scorecard: RollingEvaluationScorecard) -> str:
    """Render a stable Markdown report without wall-clock metadata."""

    protocol = scorecard.aggregate_confidence_intervals[0]
    lines = [
        "# EDGEIQ WR Receptions Rolling Evaluation",
        "",
        "> **Status: RESEARCH.** v0.6B does not permit production promotion or wagering execution.",
        "",
        "## Reproducibility",
        "",
        f"- Scorecard hash: `{scorecard.scorecard_hash}`",
        f"- Configuration hash: `{scorecard.configuration_hash}`",
        f"- Feature-table hash: `{scorecard.reproducibility.canonical_feature_table_hash}`",
        f"- Feature-registry hash: `{scorecard.reproducibility.feature_registry_hash}`",
        f"- Git commit: `{scorecard.reproducibility.git_commit_sha}`",
        f"- Bootstrap seed: `{protocol.random_seed}`",
        f"- Bootstrap iterations: `{protocol.iterations}`",
        f"- Confidence level: `{protocol.confidence_level:.3f}`",
        "",
        "## Protocol",
        "",
        "Training begins at one fixed timestamp and expands through rows strictly before each evaluation window. Windows do not overlap. Learned and baseline predictions use the identical governed held-out player-game cohort. The strongest eligible baseline is selected independently in each window by lowest MAE, then baseline name. All differences are learned minus baseline; negative values favor the learned model for MAE, RMSE, and Poisson deviance. Signed bias is interpreted relative to zero.",
        "",
        "## Windows",
        "",
        "| Window | Training period | Evaluation period | Training rows | Held-out rows | Baseline | Cohort hash | Model fingerprint |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for window in scorecard.windows:
        lines.append(
            "| "
            + " | ".join(
                (
                    window.window_id,
                    f"{window.training_period.start.isoformat()} to {window.training_period.end.isoformat()}",
                    f"{window.evaluation_period.start.isoformat()} to {window.evaluation_period.end.isoformat()}",
                    str(window.training_row_count),
                    str(window.shared_cohort_size),
                    window.governed_comparison_baseline.value,
                    f"`{window.shared_cohort_hash}`",
                    f"`{window.model_fingerprint}`",
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Per-window metrics",
            "",
            "| Window | Metric | Learned | Baseline | Difference |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for window in scorecard.windows:
        for item in window.metric_differences:
            lines.append(
                f"| {window.window_id} | {item.metric.value} | {_number(item.learned_value)} | {_number(item.baseline_value)} | {_number(item.difference)} |"
            )

    intervals = {item.metric: item for item in scorecard.aggregate_confidence_intervals}
    lines.extend(
        [
            "",
            "## Aggregate comparison",
            "",
            "| Metric | Learned | Baseline | Difference | Confidence interval |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in scorecard.aggregate_metric_differences:
        interval = intervals[item.metric]
        lines.append(
            f"| {item.metric.value} | {_number(item.learned_value)} | {_number(item.baseline_value)} | {_number(item.difference)} | [{_number(interval.confidence_lower)}, {_number(interval.confidence_upper)}] |"
        )

    lines.extend(
        [
            "",
            "## Residual and prediction-bias diagnostics",
            "",
            "Residuals use prediction minus actual.",
            "",
            "| Window | Model | Mean | Minimum | Q10 | Q25 | Median | Q75 | Q90 | Maximum | Mean absolute |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for window in scorecard.windows:
        for label, summary in (
            ("learned", window.learned_residuals),
            ("baseline", window.baseline_residuals),
        ):
            lines.append(
                f"| {window.window_id} | {label} | {_number(summary.mean)} | {_number(summary.minimum)} | {_number(summary.q10)} | {_number(summary.q25)} | {_number(summary.median)} | {_number(summary.q75)} | {_number(summary.q90)} | {_number(summary.maximum)} | {_number(summary.mean_absolute)} |"
            )
        bias = window.prediction_bias
        lines.append(
            f"| {window.window_id} | bias comparison | {_number(bias.signed_difference)} | {_number(bias.absolute_bias_difference)} |  |  |  |  |  |  |  |"
        )

    lines.extend(
        [
            "",
            "## Coefficient stability",
            "",
            "| Feature | Windows | Standardized mean | Standardized range | Raw-scale mean | Raw-scale range | Sign changes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in scorecard.coefficient_stability:
        lines.append(
            f"| {item.feature_name} | {item.window_count} | {_number(item.standardized_mean)} | {_number(item.standardized_range)} | {_number(item.raw_scale_mean)} | {_number(item.raw_scale_range)} | {item.sign_change_count} |"
        )

    lines.extend(
        [
            "",
            "### Per-window coefficients",
            "",
            "| Window | Feature | Standardized | Raw scale |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for window in scorecard.windows:
        for item in window.coefficients:
            lines.append(
                f"| {window.window_id} | {item.feature_name} | {_number(item.standardized_coefficient)} | {_number(item.raw_scale_coefficient)} |"
            )

    lines.extend(
        [
            "",
            "## Governance conclusion",
            "",
            f"Decision: **{scorecard.recommendation.decision.value}**",
            "",
            *(f"- {reason}" for reason in scorecard.recommendation.reasons),
            "",
            "## Deferred work",
            "",
            "Calibration curves, prediction intervals, player-facing dashboards, automatic model selection, hyperparameter optimization, additional count-model families, and production promotion remain outside v0.6B.",
            "",
        ]
    )
    return "\n".join(lines)


def write_rolling_research_report(
    scorecard: RollingEvaluationScorecard, path: Path
) -> Path:
    """Atomically write deterministic Markdown research output."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            render_rolling_research_report(scorecard), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
