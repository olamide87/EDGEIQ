from collections.abc import Callable

from app.providers.base import OddsProvider
from app.providers.mock import MockOddsProvider
from app.providers.theoddsapi import TheOddsAPIProvider

ProviderFactory = Callable[[], OddsProvider]


class ProviderRegistry:
    """Registry for authorized provider adapters behind the existing interface."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, key: str, factory: ProviderFactory) -> None:
        normalized = key.strip().casefold()
        if not normalized:
            raise ValueError("Provider key cannot be empty.")
        self._factories[normalized] = factory

    def get(self, key: str) -> OddsProvider:
        normalized = key.strip().casefold()
        try:
            return self._factories[normalized]()
        except KeyError as exc:
            raise KeyError(f"Unknown odds provider: {key}") from exc

    def keys(self) -> list[str]:
        return sorted(self._factories)


provider_registry = ProviderRegistry()
provider_registry.register(MockOddsProvider.key, MockOddsProvider)
provider_registry.register(TheOddsAPIProvider.key, TheOddsAPIProvider)
