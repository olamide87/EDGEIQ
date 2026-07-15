from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceComponents:
    data_quality: float = 1.0
    sample_size: float = 1.0
    role_stability: float = 1.0
    injury_certainty: float = 1.0
    matchup_certainty: float = 1.0
    market_stability: float = 1.0

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1.")


@dataclass(frozen=True)
class ConfidenceWeights:
    data_quality: float = 0.25
    sample_size: float = 0.20
    role_stability: float = 0.15
    injury_certainty: float = 0.15
    matchup_certainty: float = 0.10
    market_stability: float = 0.15

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.__dict__.values()):
            raise ValueError("Confidence weights cannot be negative.")
        if sum(self.__dict__.values()) <= 0:
            raise ValueError("At least one confidence weight must be positive.")


def calculate_overall_confidence(
    components: ConfidenceComponents, weights: ConfidenceWeights
) -> float:
    values = components.__dict__
    weight_values = weights.__dict__
    total_weight = sum(weight_values.values())
    return sum(values[name] * weight_values[name] for name in values) / total_weight
