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
against the governed strongest baseline. The v0.6A single-window API and scorecard
semantics remain unchanged.

## v0.6B rolling evaluation

v0.6B adds predeclared expanding-window evaluation. Training begins at one fixed
timestamp and expands only through rows strictly before each non-overlapping
evaluation window. A new model is fitted in every window, and its canonical state
and fingerprint are retained. The learned model and the strongest eligible
deterministic baseline are evaluated on identical held-out player-game rows.

Every window reports MAE, RMSE, mean Poisson deviance, mean signed prediction bias,
and learned-minus-baseline differences. Aggregate metrics are calculated from the
pooled, non-overlapping out-of-sample rows rather than by averaging window metrics.
A paired percentile bootstrap recomputes all four aggregate metric differences with
an explicit seed, configurable iteration count, and recorded confidence level.

Diagnostics include deterministic residual quantiles, signed and absolute
prediction bias, per-window standardized and raw-scale coefficients, coefficient
ranges, and sign changes. The scorecard has a canonical hash, and the Markdown
renderer uses fixed section, row, feature, metric, and numeric formatting. Wall-clock
evaluation time is excluded from the canonical scorecard identity and report.

Both v0.6A and v0.6B always return a `RESEARCH` decision. Rolling evidence cannot
promote the candidate or activate a production or wagering path.

## Known limitations

- The tiny committed fixture validates mechanics, not predictive usefulness.
- The Poisson variance-equals-mean assumption may not describe reception counts.
- Only four pregame candidate features are used; there is no tuning or selection.
- The solver is intentionally small and is not optimized for large datasets.
- No production artifact, live inference API, betting logic, or profitability claim
  is included.
- Rolling windows are predeclared; v0.6B performs no automatic window, model, or
  hyperparameter selection.
- Calibration curves, prediction intervals, and alternative count-model families
  remain deferred.
