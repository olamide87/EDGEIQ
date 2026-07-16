import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import Player, PlayerAlias

COMMON_FIRST_NAMES = {
    "gabe": "gabriel",
    "mike": "michael",
    "will": "william",
}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


class AliasConflictError(ValueError):
    pass


def normalize_player_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", ascii_name.casefold())
    if tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    while len(tokens) >= 3 and len(tokens[0]) == 1 and len(tokens[1]) == 1:
        tokens[0:2] = [tokens[0] + tokens[1]]
    if tokens:
        tokens[0] = COMMON_FIRST_NAMES.get(tokens[0], tokens[0])
    return " ".join(tokens)


def resolve_player(session: Session, *, provider: str, raw_name: str) -> Player:
    normalized = normalize_player_name(raw_name)
    if not normalized:
        raise ValueError("Player name cannot be empty after normalization.")
    alias = session.scalar(
        select(PlayerAlias).where(
            PlayerAlias.provider == provider,
            PlayerAlias.normalized_alias == normalized,
        )
    )
    if alias is not None:
        return alias.player

    global_aliases = session.scalars(
        select(PlayerAlias).where(PlayerAlias.normalized_alias == normalized)
    ).all()
    player_ids = {item.player_id for item in global_aliases}
    if len(player_ids) > 1:
        raise AliasConflictError(f"Conflicting aliases for normalized player name '{normalized}'.")
    if global_aliases:
        player = global_aliases[0].player
    else:
        players = session.scalars(select(Player)).all()
        player = next(
            (candidate for candidate in players if normalize_player_name(candidate.name) == normalized),
            None,
        )
        if player is None:
            player = Player(name=raw_name.strip())
            session.add(player)
            session.flush()

    session.add(PlayerAlias(
        player_id=player.id,
        provider=provider,
        raw_alias=raw_name,
        normalized_alias=normalized,
    ))
    session.flush()
    return player
