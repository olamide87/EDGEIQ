from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def test_populated_v03_database_upgrades_to_v04(tmp_path):
    database = tmp_path / "populated-v03.db"
    url = f"sqlite:///{database.as_posix()}"
    original_url = settings.database_url
    settings.database_url = url
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260715_0002")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO players (id,name,created_at) "
                "VALUES (1,'Legacy Player',CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO sportsbooks (id,name,key,created_at) "
                "VALUES (1,'Legacy Book','legacy',CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO events (id,external_id,name,sport,created_at) "
                "VALUES (1,'legacy-event','Legacy Event','americanfootball_nfl',CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO prop_lines "
                "(id,event_id,player_id,sportsbook_id,market,side,line,american_odds,captured_at) "
                "VALUES (1,1,1,1,'player_receptions','over',5.5,-110,CURRENT_TIMESTAMP)"
            ))

        command.upgrade(config, "head")
        with engine.connect() as connection:
            legacy = connection.execute(text(
                "SELECT id,provider_key,raw_player_name,snapshot_batch_id "
                "FROM prop_lines WHERE id=1"
            )).one()
        assert legacy == (1, None, None, None)
        assert {
            "ingestion_jobs", "provider_health", "odds_snapshot_batches", "player_aliases"
        } <= set(inspect(engine).get_table_names())
        command.check(config)
    finally:
        settings.database_url = original_url
