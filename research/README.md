# EDGE IQ WR-receptions research

Research work is split into four promotion-gated milestones. v0.5A builds only the
reproducible source and player-game table. v0.5B adds leakage-audited features,
v0.5C establishes simple baselines, and v0.5D evaluates the first learned models.

## Reproduce v0.5A

```text
python -m app.cli data-download --seasons 2021 2022 2023 2024 2025 --datasets player_stats schedules rosters weekly_rosters snap_counts participation injuries depth_charts
python -m app.cli data-manifest
python -m app.cli build-wr-dataset --seasons 2021 2022 2023 2024 2025
```

Add `--datasets pbp` deliberately when play-by-play is required; it is excluded from
the default download because it is much larger than the v0.5A training-table inputs.
All downloaded and generated files live under ignored `data/` paths.

## Reproduce v0.5B

```text
python -m app.cli build-wr-features --seasons 2021 2022 2023 2024 2025
python -m app.cli feature-registry
python -m app.cli validate-wr-features --path data/processed/wr_receptions_features.parquet
python research/experiments/run_v05b_feature_audit.py
```

The audit reports null rates, descriptive statistics, first availability, season
coverage, player-history tiers, registry/source/output hashes, and leakage-validation
status. It does not fit or evaluate a model. Generated reports are ignored.

Tests inject synthetic CSV loaders and never call the internet. The committed fixture
backfill is intentionally too small to support football or profitability conclusions.

## Experiment rule

Later experiment reports must record the Git revision, configuration, source manifest
hash, chronological windows, feature list, model parameters, metrics, warnings, and a
KEEP, MODIFY, or DISCARD conclusion. Calibration error is the primary probability KPI.
No v0.5B feature has earned a KEEP decision yet.
