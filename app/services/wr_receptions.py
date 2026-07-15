import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WRReceptionsProjection:
    model_label: str
    projected_targets: float
    projected_receptions: float
    floor: int
    median: int
    ceiling: int
    over_probability: float
    under_probability: float
    push_probability: float
    assumptions_used: dict[str, float]


def _poisson_pmf(value: int, rate: float) -> float:
    return math.exp(-rate) * rate**value / math.factorial(value)


def _poisson_cdf(value: int, rate: float) -> float:
    if value < 0:
        return 0.0
    return sum(_poisson_pmf(index, rate) for index in range(value + 1))


def _poisson_quantile(probability: float, rate: float) -> int:
    cumulative = 0.0
    value = 0
    while cumulative < probability and value < 1000:
        cumulative += _poisson_pmf(value, rate)
        if cumulative >= probability:
            return value
        value += 1
    return value


def project_wr_receptions(
    *, projected_team_pass_attempts: float, route_participation: float,
    targets_per_route_run: float, catch_probability: float, line: float,
    contextual_multipliers: dict[str, float] | None = None,
) -> WRReceptionsProjection:
    if projected_team_pass_attempts < 0:
        raise ValueError("Projected team pass attempts cannot be negative.")
    for name, value in {
        "route_participation": route_participation,
        "targets_per_route_run": targets_per_route_run,
        "catch_probability": catch_probability,
    }.items():
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1.")
    if line < 0:
        raise ValueError("Line cannot be negative.")
    multipliers = contextual_multipliers or {}
    if any(value <= 0 for value in multipliers.values()):
        raise ValueError("Contextual multipliers must be greater than zero.")

    context = math.prod(multipliers.values()) if multipliers else 1.0
    targets = projected_team_pass_attempts * route_participation * targets_per_route_run * context
    receptions = targets * catch_probability
    lower = math.floor(line)
    over = 1 - _poisson_cdf(lower, receptions)
    if float(line).is_integer():
        push = _poisson_pmf(int(line), receptions)
        under = _poisson_cdf(int(line) - 1, receptions)
    else:
        push = 0.0
        under = _poisson_cdf(lower, receptions)
    return WRReceptionsProjection(
        model_label="Baseline Poisson WR receptions model (not production-grade)",
        projected_targets=targets,
        projected_receptions=receptions,
        floor=_poisson_quantile(0.10, receptions),
        median=_poisson_quantile(0.50, receptions),
        ceiling=_poisson_quantile(0.90, receptions),
        over_probability=over,
        under_probability=under,
        push_probability=push,
        assumptions_used={
            "projected_team_pass_attempts": projected_team_pass_attempts,
            "route_participation": route_participation,
            "targets_per_route_run": targets_per_route_run,
            "catch_probability": catch_probability,
            **multipliers,
        },
    )
