import pytest
from pydantic import ValidationError

from app.research.evaluation import (
    GOVERNANCE_V1,
    EvaluationProtocol,
    GovernancePolicy,
    MetricDirection,
    MetricName,
    MetricRole,
    ResearchDecision,
)


def test_governance_v1_has_exact_primary_and_diagnostic_metrics():
    primary = {
        metric.name
        for metric in GOVERNANCE_V1.metrics
        if metric.role is MetricRole.PRIMARY
    }
    diagnostic = {
        metric.name
        for metric in GOVERNANCE_V1.metrics
        if metric.role is MetricRole.DIAGNOSTIC
    }

    assert primary == {
        MetricName.MAE,
        MetricName.CALIBRATION_ERROR,
        MetricName.POISSON_DEVIANCE,
    }
    assert diagnostic == {
        MetricName.RMSE,
        MetricName.BIAS,
        MetricName.COVERAGE,
        MetricName.PREDICTION_VARIANCE,
        MetricName.SAMPLE_COUNT,
    }
    assert GOVERNANCE_V1.metric(MetricName.MAE).direction is MetricDirection.LOWER
    assert GOVERNANCE_V1.metric(MetricName.BIAS).direction is MetricDirection.TARGET_ZERO


def test_evaluation_protocol_v1_is_chronological_and_pre_registered():
    protocol = GOVERNANCE_V1.protocol

    assert protocol.validation_method == "chronological_held_out"
    assert protocol.significance_test == "paired_bootstrap"
    assert protocol.confidence_level == 0.95
    assert protocol.bootstrap_iterations == 10_000
    assert isinstance(protocol.random_seed, int)

    with pytest.raises(ValidationError, match="chronological"):
        EvaluationProtocol(validation_method="random_split")
    with pytest.raises(ValidationError, match="MAE"):
        EvaluationProtocol(primary_metric=MetricName.RMSE)


def test_promotion_contract_and_research_decisions_are_explicit():
    promotion = GOVERNANCE_V1.promotion

    assert promotion.strongest_eligible_baseline is True
    assert promotion.significant_mae_improvement is True
    assert promotion.equal_or_better_calibration is True
    assert promotion.improved_poisson_deviance is True
    assert promotion.predefined_subgroups_pass is True
    assert promotion.reproducible_artifacts is True
    assert promotion.final_decision is ResearchDecision.PROMOTE
    assert GOVERNANCE_V1.allowed_decisions == (
        ResearchDecision.PROMOTE,
        ResearchDecision.RESEARCH,
        ResearchDecision.REVISE,
        ResearchDecision.REJECT,
    )


def test_governance_contract_is_frozen_and_rejects_missing_metrics():
    with pytest.raises(ValidationError, match="frozen"):
        GOVERNANCE_V1.version = "2.0"

    with pytest.raises(ValidationError, match="every governed metric"):
        GovernancePolicy(
            version="1.0",
            protocol=EvaluationProtocol(),
            metrics=GOVERNANCE_V1.metrics[:-1],
            promotion=GOVERNANCE_V1.promotion,
            allowed_decisions=tuple(ResearchDecision),
        )
