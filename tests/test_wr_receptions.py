import pytest

from app.services.wr_receptions import project_wr_receptions


def test_baseline_wr_projection_uses_poisson_count_model():
    result = project_wr_receptions(
        projected_team_pass_attempts=35,
        route_participation=0.9,
        targets_per_route_run=0.25,
        catch_probability=0.7,
        line=5.5,
        contextual_multipliers={"matchup": 1.05},
    )
    assert "not production-grade" in result.model_label
    assert result.projected_targets == pytest.approx(8.26875)
    assert result.projected_receptions == pytest.approx(5.788125)
    assert result.over_probability + result.under_probability == pytest.approx(1)
    assert result.floor <= result.median <= result.ceiling


def test_integer_line_reports_push_probability():
    result = project_wr_receptions(
        projected_team_pass_attempts=30,
        route_participation=0.8,
        targets_per_route_run=0.2,
        catch_probability=0.75,
        line=4,
    )
    assert result.push_probability > 0
    assert result.over_probability + result.under_probability + result.push_probability == pytest.approx(1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"projected_team_pass_attempts": -1},
        {"route_participation": 1.1},
        {"targets_per_route_run": -0.1},
        {"catch_probability": 1.1},
        {"line": -0.5},
        {"contextual_multipliers": {"injury": 0}},
    ],
)
def test_baseline_wr_projection_validates_inputs(overrides):
    values = dict(
        projected_team_pass_attempts=30,
        route_participation=0.8,
        targets_per_route_run=0.2,
        catch_probability=0.75,
        line=4.5,
    )
    values.update(overrides)
    with pytest.raises(ValueError):
        project_wr_receptions(**values)
