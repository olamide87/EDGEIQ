# EDGE IQ roadmap

This roadmap communicates product direction, not fixed delivery dates. A release is
complete only when its behavior, migrations, tests, and documentation are shipped.

| Release | Theme | Status |
| --- | --- | --- |
| v0.1 | Line Shopping | ✅ Complete |
| v0.2 | API and Database | ✅ Complete |
| v0.3 | Projection Quality and Paper Trading | ✅ Complete |
| v0.4 | Automated Data Engine | ✅ Complete |
| v0.5 | Historical Data and WR Model Validation | Planned |
| v0.6 | Machine Learning | Planned |
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

## v0.4 — Automated Data Engine ✅

- Scheduled, idempotent odds ingestion jobs
- Snapshot deduplication and provider health monitoring
- Historical odds, movement, and market-consensus endpoints
- Retry, timeout, data-quality, alias, and observability controls
- Optional in-process scheduler and one-shot execution

## v0.5 — Historical Data and WR Model Validation

- Evaluate and license historical NFL usage sources
- Build canonical player, team, game, route, target, and reception datasets
- Validate coverage, survivorship bias, corrections, and point-in-time availability
- Establish the simple Poisson and market-implied probability baselines
- Train/validation/test splits that respect season and time boundaries
- Feature definitions for route participation, target share, TPRR, catch rate,
  first-read share, quarterback context, opponent coverage, and game environment
- Out-of-sample calibration, scoring, and economic-value evaluation before model expansion

## v0.6 — Machine Learning

- Reproducible feature pipelines and experiment tracking
- Calibrated WR-receptions probability models
- Champion/challenger comparison against simple and market baselines
- Drift monitoring, model registry, and guarded deployment

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
