from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import math

from pydantic import ValidationError

from app.models import Market, Offer
from app.services.player_aliases import normalize_player_name


@dataclass(frozen=True)
class QualityFlag:
    category: str
    message: str
    record_index: int | None = None


@dataclass(frozen=True)
class ValidatedPayload:
    offers: list[Offer]
    flags: list[QualityFlag]


def validate_provider_payload(
    payload: Any, *, stale_event_hours: int = 6,
) -> ValidatedPayload:
    if not isinstance(payload, list):
        return ValidatedPayload([], [QualityFlag("MALFORMED_PAYLOAD", "Provider payload is not a list.")])
    offers: list[Offer] = []
    flags: list[QualityFlag] = []
    seen: set[tuple[object, ...]] = set()
    stale_before = datetime.now(timezone.utc) - timedelta(hours=stale_event_hours)
    normalized_names: dict[str, str] = {}

    for index, raw in enumerate(payload):
        try:
            offer = raw if isinstance(raw, Offer) else Offer.model_validate(raw)
        except ValidationError as exc:
            category = "UNSUPPORTED_MARKET" if "market" in str(exc) else "MALFORMED_PAYLOAD"
            flags.append(QualityFlag(category, "Provider record failed schema validation.", index))
            continue
        if not offer.player.strip():
            flags.append(QualityFlag("MISSING_PLAYER_NAME", "Player name is missing.", index))
            continue
        if offer.american_odds == 0 or abs(offer.american_odds) < 100:
            flags.append(QualityFlag("INVALID_ODDS", "American odds are outside valid bounds.", index))
            continue
        if offer.line is not None and (
            not math.isfinite(offer.line) or offer.line < 0 or offer.line > 10_000
        ):
            flags.append(QualityFlag("IMPOSSIBLE_LINE", "Prop line is outside plausible bounds.", index))
            continue
        if offer.market == Market.ANYTIME_TD and offer.line is not None:
            flags.append(QualityFlag("IMPOSSIBLE_LINE", "Binary anytime-TD offers cannot have a line.", index))
            continue
        if offer.commence_time is not None:
            event_time = (
                offer.commence_time.replace(tzinfo=timezone.utc)
                if offer.commence_time.tzinfo is None else offer.commence_time.astimezone(timezone.utc)
            )
            if event_time < stale_before:
                flags.append(QualityFlag("STALE_EVENT", "Event timestamp is stale.", index))

        normalized = normalize_player_name(offer.player)
        previous = normalized_names.get(normalized)
        if previous is not None and previous != offer.player:
            flags.append(QualityFlag(
                "PLAYER_ALIAS_VARIATION",
                f"Multiple raw aliases normalize to '{normalized}'.",
                index,
            ))
        normalized_names[normalized] = offer.player
        contract = (
            offer.event_id, offer.bookmaker.casefold(), offer.market.value, normalized,
            offer.side.value, offer.line,
        )
        if contract in seen:
            flags.append(QualityFlag("DUPLICATE_CONTRACT", "Duplicate contract suppressed.", index))
            continue
        seen.add(contract)
        offers.append(offer)
    return ValidatedPayload(offers, flags)
