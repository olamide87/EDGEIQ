# WR receptions Poisson regression

Status: research candidate, not production-grade
Model version: `0.1.0`
Research governance: `1.0`

## Why Poisson regression comes first

Receptions are non-negative counts, so a log-link Poisson regression is a small,
interpretable first learned model. It provides a useful bridge from the v0.5C
analytical baselines to learned-model evaluation without introducing tuning,
feature selection, or an additional numerical dependency. This choice does not
establish that receptions are exactly Poisson distributed or that the candidate
outperforms any baseline.

## Feature and time contract

The ordered inputs are `receptions_roll3`, `targets_roll3`, `home_indicator`, and
`games_played_before`. At model version 0.1.0, every configured input is enabled in the versioned WR feature registry.
Each input is materialized by the point-in-time feature pipeline before kickoff.
The model configuration rejects disabled, postgame-only, high-leakage, unknown, or
duplicate features.

Training and evaluation use explicit, non-overlapping chronological periods. Rows
are ordered by kickoff, game ID, and stable source player ID. The evaluation layer
fits on the training period and scores only the held-out period; it never shuffles
player-games.

## Determinism and evaluation

The implementation uses a deterministic penalized Newton solver with explicit
hyperparameters. It records the ordered features, hyperparameters, standardized
feature statistics, fitted coefficients, training cohort boundaries and count,
canonical training-data hash, source identities, and a canonical model fingerprint.
The fingerprint includes deterministic training-period boundaries but excludes
wall-clock timestamps, paths, memory addresses, and other volatile values.

The learned candidate is evaluated on the same shared cohort as all governed WR
baselines. Its scorecard reports MAE, expected calibration error, mean Poisson
deviance, diagnostics, and the existing seeded paired-bootstrap MAE comparison
against the governed strongest baseline. v0.6A always returns a `RESEARCH` decision:
it does not implement the remaining subgroup and promotion gates and therefore
cannot promote the candidate.

## Known limitations

- The tiny committed fixture validates mechanics, not predictive usefulness.
- The Poisson variance-equals-mean assumption may not describe reception counts.
- Only four pregame candidate features are used; there is no tuning or selection.
- The solver is intentionally small and is not optimized for large datasets.
- No production artifact, live inference API, betting logic, or profitability claim
  is included.
