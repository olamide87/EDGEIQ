from abc import ABC, abstractmethod
from app.models import Offer


class OddsProvider(ABC):
    @abstractmethod
    async def fetch_nfl_player_props(self) -> list[Offer]:
        raise NotImplementedError
