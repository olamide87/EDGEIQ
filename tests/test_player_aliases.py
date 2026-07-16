from sqlalchemy.orm import Session

from app.db_models import Player
from app.services.player_aliases import normalize_player_name, resolve_player


def test_player_name_normalization_handles_punctuation_suffixes_and_initials():
    assert normalize_player_name("A.J. Brown Jr.") == normalize_player_name("AJ Brown")
    assert normalize_player_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert normalize_player_name("Odell Beckham, Jr.") == normalize_player_name("Odell Beckham")


def test_player_name_normalization_handles_common_abbreviation():
    assert normalize_player_name("Gabe Davis") == normalize_player_name("Gabriel Davis")


def test_aliases_across_providers_resolve_to_canonical_player(db_session: Session):
    first = resolve_player(db_session, provider="provider-a", raw_name="A.J. Brown Jr.")
    second = resolve_player(db_session, provider="provider-b", raw_name="AJ Brown")
    db_session.commit()
    assert first.id == second.id
    assert db_session.query(Player).count() == 1
