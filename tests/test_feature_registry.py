import pytest
from pydantic import ValidationError

from feature_store.registry import (
    FEATURE_REGISTRY,
    MODEL_FEATURE_NAMES,
    WR_FEATURE_REGISTRY,
    EntityGrain,
    FeatureDefinition,
    FeatureRegistry,
    FeatureTiming,
    LeakageRisk,
    MissingValuePolicy,
    validate_feature_registry,
)


def test_feature_registry_is_complete_unique_and_machine_validated():
    registry = validate_feature_registry()
    assert registry.version == "wr-receptions-features-v1"
    assert len(registry.features) == len({feature.name for feature in registry.features})
    assert registry.registry_hash == WR_FEATURE_REGISTRY.registry_hash
    for feature in registry.features:
        dumped = feature.model_dump()
        assert {
            "name", "description", "source_dataset", "source_columns", "transformation",
            "entity_grain", "lookback_games", "minimum_history", "availability_timing",
            "availability_timestamp", "missing_value_policy", "leakage_risk",
            "enabled", "dtype", "version",
        } <= set(dumped)


def test_feature_registry_documents_scope_and_excludes_leakage():
    by_name = {feature.name: feature for feature in FEATURE_REGISTRY}
    assert by_name["targets_roll3"].lookback_games == 3
    assert by_name["targets_roll3"].leakage_risk is LeakageRisk.NONE
    assert by_name["same_game_targets"].leakage_risk is LeakageRisk.HIGH
    assert by_name["same_game_targets"].retained is False
    assert by_name["team_plays_roll3"].missing_value_policy is MissingValuePolicy.NOT_AVAILABLE
    assert by_name["games_played_before"].source_dataset == "wr_player_game"
    assert by_name["has_prior_history"].source_columns == ("game_id",)
    assert "same_game_targets" not in MODEL_FEATURE_NAMES
    assert "team_plays_roll3" not in MODEL_FEATURE_NAMES


def test_registry_rejects_duplicate_and_enabled_high_leakage_features():
    safe = FeatureDefinition(
        name="safe",
        description="safe test feature",
        source_dataset="fixture",
        source_columns=("value",),
        transformation="shift(value, 1)",
        entity_grain=EntityGrain.PLAYER_GAME,
        lookback_games=1,
        minimum_history=1,
        availability_timing=FeatureTiming.LAGGED,
        availability_timestamp="after_prior_game_final_and_before_current_kickoff",
        missing_value_policy=MissingValuePolicy.LEAVE_NULL,
        leakage_risk=LeakageRisk.NONE,
        enabled=True,
        dtype="Float64",
        version="1.0",
    )
    with pytest.raises(ValidationError, match="unique"):
        FeatureRegistry(features=(safe, safe))
    with pytest.raises(ValidationError, match="High-leakage"):
        FeatureDefinition.model_validate({
            **safe.model_dump(),
            "leakage_risk": LeakageRisk.HIGH,
        })


def test_registry_hash_changes_when_semantics_change():
    changed_feature = FEATURE_REGISTRY[0].model_copy(
        update={"transformation": "semantically different prior-game transformation"}
    )
    changed = FeatureRegistry(features=(changed_feature, *FEATURE_REGISTRY[1:]))
    assert changed.registry_hash != WR_FEATURE_REGISTRY.registry_hash
