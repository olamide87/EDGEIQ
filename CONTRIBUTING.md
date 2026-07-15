# Contributing to EDGE IQ

## Development workflow

1. Create a focused branch from `main`.
2. Install dependencies from `requirements.txt` in a virtual environment.
3. Add tests with each behavior change.
4. Run `pytest -q`, `alembic upgrade head`, and `alembic check`.
5. Keep secrets in `.env`; never commit credentials or local databases.
6. Open a pull request describing the behavior, migration impact, and validation.

Changes must preserve paper-only operation. Do not add sportsbook scraping, login
automation, wager execution, or unlicensed data ingestion.

Database changes require a new forward migration. API changes should remain backward
compatible during pre-1.0 development unless the release notes explicitly document
the break.
