# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [0.5.0-alpha.1] - Unreleased

### Added

- Typed nflreadpy/nflverse adapter for nine historical dataset families
- Ignored season-partitioned Parquet cache and hash-verified source manifests
- Deterministic, normalized one-row-per-WR-game training-table generator
- Offline synthetic fixtures and a two-run reproducibility validator
- Feature/model registry scaffolding and architecture decision records

### Scope

- No feature computation, model fitting, public training API, or wagering execution
- Polars and nflreadpy only; model dependencies are deferred to v0.5D

## [0.4.0] - 2026-07-15

### Added

- Authorized provider registry and configurable APScheduler ingestion loop
- One-shot ingestion API and CLI with retries, correlation IDs, and structured logs
- Ingestion jobs, provider health, snapshot batches, and unchanged-payload suppression
- Data-quality flags and cross-provider player alias normalization
- Historical odds, movement detection, and multi-book market consensus APIs
- SQLite-safe v0.3-to-v0.4 migration and ingestion test coverage

## [0.3.0] - 2026-07-15

### Added

- Fair-market normalization and vig removal for complete two-way markets
- Weighted confidence, freshness policy, and explicit recommendation reasons
- Paper bets, closing snapshots, settlement, CLV, and performance analytics
- Exposure controls and baseline Poisson WR-receptions projections
- CI, architecture documentation, and release roadmap

## [0.2.0] - 2026-07-15

### Added

- FastAPI, SQLAlchemy persistence, SQLite, and Alembic
- Projection and recommendation APIs
- Expected-value and bankroll services

## [0.1.0] - 2026-07-15

### Added

- CLI line shopper, odds math, provider abstraction, and snapshots
