from datetime import datetime, timezone
from app.models import Offer, Market, Side
from app.providers.base import OddsProvider


class MockOddsProvider(OddsProvider):
    async def fetch_nfl_player_props(self) -> list[Offer]:
        now = datetime.now(timezone.utc)
        return [
            Offer(event_id="demo-1", event_name="DET at CHI", bookmaker="FanDuel",
                  market=Market.PLAYER_RECEPTIONS, player="Amon-Ra St. Brown",
                  side=Side.OVER, line=6.5, american_odds=-118, captured_at=now),
            Offer(event_id="demo-1", event_name="DET at CHI", bookmaker="DraftKings",
                  market=Market.PLAYER_RECEPTIONS, player="Amon-Ra St. Brown",
                  side=Side.OVER, line=6.5, american_odds=-105, captured_at=now),
            Offer(event_id="demo-1", event_name="DET at CHI", bookmaker="BetMGM",
                  market=Market.PLAYER_RECEPTIONS, player="Amon-Ra St. Brown",
                  side=Side.OVER, line=7.5, american_odds=105, captured_at=now),
            Offer(event_id="demo-1", event_name="DET at CHI", bookmaker="Caesars",
                  market=Market.PLAYER_RECEPTIONS, player="Amon-Ra St. Brown",
                  side=Side.OVER, line=6.5, american_odds=-110, captured_at=now),
        ]
