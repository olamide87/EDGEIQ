# EDGE IQ roadmap

This roadmap communicates product direction, not fixed delivery dates. A release is
complete only when its behavior, migrations, tests, and documentation are shipped.

| Release | Theme | Status |
| --- | --- | --- |
| v0.1 | Line Shopping | ✅ Complete |
| v0.2 | API and Database | ✅ Complete |
| v0.3 | Projection Quality and Paper Trading | ✅ Complete |
| v0.4 | Automated Data Engine | 🚧 Next |
| v0.5 | Machine Learning | Planned |
| v0.6 | AI War Room | Planned |
| v0.7 | Dashboard | Planned |
| v1.0 | Public Beta | Planned |

## v0.1 — Line Shopping ✅

- Normalized player-prop offers
- Threshold-first line comparison
- American-odds math
- Mock data and The Odds API provider
- CLI and JSONL snapshots

## v0.2 — API and Database ✅

- FastAPI and OpenAPI documentation
- SQLAlchemy 2.x persistence
- SQLite development database and Alembic migrations
- Players, events, sportsbooks, prop lines, projections, and recommendations
- Expected-value service and paper bankroll rules

## v0.3 — Projection Quality and Paper Trading ✅

- Proportional vig removal for complete two-way markets
- Weighted confidence and freshness policy
- Best-line selection before expected-value calculation
- Paper-bet, closing-line, settlement, CLV, and performance analytics
- Duplicate and correlated exposure controls
- Baseline Poisson WR-receptions model

## v0.4 — Automated Data Engine 🚧

- Scheduled, idempotent ingestion jobs
- Snapshot deduplication and provider health monitoring
- Historical odds and closing-line datasets
- Retry, backoff, rate-limit, and data-quality controls
- Background-worker observability and operational runbooks
- PostgreSQL CI and deployment-ready configuration

## v0.5 — Machine Learning

- Licensed historical feature pipeline
- Train/validation/test splits that respect season and time boundaries
- Calibrated position-specific probability models
- Baseline comparisons, experiment tracking, and model registry
- Drift, calibration, and out-of-sample evaluation reports

## v0.6 — AI War Room

- Evidence-linked research summaries
- Injury, role, matchup, and market-movement review workspace
- Human approval checkpoints for model and recommendation changes
- Auditable prompts, sources, and generated analysis

## v0.7 — Dashboard

- Responsive line-shopping and recommendation views
- Projection and confidence explainability
- Paper bankroll, exposure, CLV, and performance dashboards
- Operational status and data-freshness monitoring

## v1.0 — Public Beta

- Stable, versioned public API contracts
- Security, privacy, licensing, and responsible-use review
- Production PostgreSQL, backups, monitoring, and incident response
- User documentation and onboarding
- Explicit beta limitations and feedback process

## Release discipline

EDGE IQ uses semantic versioning while pre-1.0 releases are allowed to evolve quickly.
Every release should include:

- A versioned Alembic migration when persistence changes
- Passing tests and schema-drift checks in CI
- Updated API and architecture documentation
- A changelog entry and migration notes
- No committed secrets, local databases, or generated odds snapshots
