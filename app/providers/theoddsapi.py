from datetime import datetime
import httpx

from app.config import settings
from app.models import Offer, Market, Side
from app.providers.base import OddsProvider


MARKET_MAP = {
    "player_pass_yds": Market.QB_PASSING_YARDS,
    "player_pass_tds": Market.QB_PASSING_TDS,
    "player_pass_interceptions": Market.QB_INTERCEPTIONS,
    "player_receptions": Market.PLAYER_RECEPTIONS,
    "player_anytime_td": Market.ANYTIME_TD,
}

SIDE_MAP = {
    "over": Side.OVER,
    "under": Side.UNDER,
    "yes": Side.YES,
    "no": Side.NO,
}


class TheOddsAPIProvider(OddsProvider):
    base_url = "https://api.the-odds-api.com/v4"

    async def fetch_nfl_player_props(self) -> list[Offer]:
        if not settings.odds_api_key:
            raise RuntimeError("ODDS_API_KEY is missing.")

        async with httpx.AsyncClient(timeout=30) as client:
            events_response = await client.get(
                f"{self.base_url}/sports/americanfootball_nfl/events",
                params={"apiKey": settings.odds_api_key},
            )
            events_response.raise_for_status()
            events = events_response.json()

            offers: list[Offer] = []
            for event in events:
                event_id = event["id"]
                odds_response = await client.get(
                    f"{self.base_url}/sports/americanfootball_nfl/events/{event_id}/odds",
                    params={
                        "apiKey": settings.odds_api_key,
                        "regions": settings.odds_region,
                        "markets": ",".join(MARKET_MAP.keys()),
                        "oddsFormat": settings.odds_format,
                    },
                )
                if odds_response.status_code in (404, 422):
                    continue
                odds_response.raise_for_status()
                payload = odds_response.json()
                offers.extend(self._normalize_event(payload))
            return offers

    def _normalize_event(self, event: dict) -> list[Offer]:
        normalized: list[Offer] = []
        event_name = f"{event.get('away_team', '')} at {event.get('home_team', '')}".strip()
        commence_time = None
        if event.get("commence_time"):
            commence_time = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))

        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                mapped_market = MARKET_MAP.get(market.get("key"))
                if mapped_market is None:
                    continue
                for outcome in market.get("outcomes", []):
                    side = SIDE_MAP.get(str(outcome.get("name", "")).lower())
                    # Most player-prop payloads put player name in description.
                    player = outcome.get("description")
                    if side is None or not player:
                        continue
                    price = outcome.get("price")
                    if not isinstance(price, int):
                        continue
                    normalized.append(
                        Offer(
                            event_id=event["id"],
                            event_name=event_name,
                            commence_time=commence_time,
                            bookmaker=book.get("title", book.get("key", "Unknown")),
                            market=mapped_market,
                            player=player,
                            side=side,
                            line=outcome.get("point"),
                            american_odds=price,
                        )
                    )
        return normalized
