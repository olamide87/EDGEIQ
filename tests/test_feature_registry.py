from feature_store.registry import FEATURE_REGISTRY, MODEL_FEATURE_NAMES, LeakageRisk


def test_feature_registry_documents_lookback_and_excludes_leakage():
    by_name = {feature.name: feature for feature in FEATURE_REGISTRY}
    assert by_name["targets_roll3"].lookback_games == 3
    assert by_name["targets_roll3"].leakage_risk is LeakageRisk.NONE
    assert by_name["same_game_targets"].leakage_risk is LeakageRisk.HIGH
    assert by_name["same_game_targets"].retained is False
    assert "same_game_targets" not in MODEL_FEATURE_NAMES
