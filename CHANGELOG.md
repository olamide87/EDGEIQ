# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [0.6.0-alpha.2] - Unreleased

### Added

- Deterministic expanding-window evaluation for the learned WR-receptions model
- Per-window learned-versus-baseline MAE, RMSE, Poisson deviance, and bias differences
- Seeded paired-bootstrap confidence intervals for pooled out-of-sample differences
- Residual, prediction-bias, and cross-window coefficient-stability summaries
- Canonical rolling scorecards and deterministic Markdown research reports

### Scope

- Research-only diagnostics with no production promotion or sportsbook execution
- No automatic model selection, tuning, calibration curves, prediction intervals,
  dashboards, or additional model families
- Existing v0.6A public APIs and scorecard semantics remain unchanged

## [0.6.0-alpha.1] - Unreleased

### Added

- Deterministic penalized Poisson regression for WR-receptions research
- Immutable fitted state, canonical model fingerprints, and JSON round trips
- Explicit chronological train/evaluation splitting and governed learned scorecards
- Paired-bootstrap comparison with the strongest governed WR baseline

### Scope

- Research-only candidate with no promotion, production inference, or betting logic
- No tuning, ensembles, feature selection, neural networks, or new dependencies

## [0.5.0-alpha.2] - Unreleased

### Added

- Typed v1 WR feature registry with availability, missingness, and leakage contracts
- Deterministic point-in-time player, usage, team, opponent, and game features
- Versioned feature table, canonical content hash, atomic Parquet output, and manifest
- Feature registry/build/validation CLI commands and an offline feature-audit script
- Leakage, ordering, season-boundary, trade, rookie, missingness, and hash tests

### Scope

- Candidate features only; no fitting, baseline evaluation, calibration, or backtesting
- No scikit-learn, statsmodels, or other model-training dependencies

## [0.5.0-alpha.1]

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
