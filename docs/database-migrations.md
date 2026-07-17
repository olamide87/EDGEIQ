# Local database migration note

The legacy development database at `data/edgeiq.db` was historically created through
SQLAlchemy `create_all()` and is not reliably associated with an Alembic revision.
The current local file contains an empty `alembic_version` table, which still means it
is unstamped. Running `alembic upgrade head` against it attempts the initial migration
and conflicts with tables that already exist.

This is not a v0.5A release blocker because v0.5A makes no database-schema changes.
Migration upgrade and drift validation are run against a fresh, ignored SQLite file.

Do not stamp, delete, rebuild, or otherwise mutate `data/edgeiq.db` casually. A later
decision must inventory its schema and data, define backup and recovery steps, and
choose explicitly between reconciliation, export/import, or replacement. That work
should receive its own ADR, tests, and migration plan.
