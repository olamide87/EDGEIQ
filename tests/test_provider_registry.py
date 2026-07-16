import pytest

from app.providers.mock import MockOddsProvider
from app.providers.registry import ProviderRegistry


def test_provider_registry_is_extensible_and_case_insensitive():
    registry = ProviderRegistry()
    registry.register("Authorized", MockOddsProvider)
    assert isinstance(registry.get("authorized"), MockOddsProvider)
    assert registry.keys() == ["authorized"]


def test_provider_registry_rejects_unknown_provider():
    with pytest.raises(KeyError, match="Unknown odds provider"):
        ProviderRegistry().get("missing")
