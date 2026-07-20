# EDGE IQ Research Governance

- Governance version: 1.0
- Status: Active
- Effective milestone: v0.5C
- Scope: Model-agnostic research evaluation and promotion

Research Governance v1.0 defines how EDGE IQ judges evidence. Datasets, features,
baselines, and models may change, but every research result must satisfy the same
reproducibility, validation, reporting, and decision standards.

This document is a versioned contract. Its rules must not change during an active
experiment. Clarifications that cannot change an evaluation or promotion outcome
require a minor version. Any change that can affect results or decisions requires
a major version.

## Governing questions

Every research milestone must answer:

1. **Can it be reproduced?** Version the data, feature registry, manifests,
   configuration, code revision, and deterministic outputs.
2. **Is it statistically better?** Use chronological held-out validation,
   pre-registered metrics, paired comparisons, confidence intervals, and effect
   sizes.
3. **Does it generalize?** Report predefined player, volume, and season segments
   instead of relying only on aggregate results.
4. **Should it be trusted?** Resolve leakage and data-quality issues, state
   limitations, and record a formal research decision.

## Evaluation Protocol v1.0

An experiment must register its protocol before evaluation begins. Changing a
registered rule invalidates comparison under that experiment identifier and
requires a new protocol version or experiment.

```yaml
evaluation_protocol:
  version: "1.0"
  validation_method: chronological_held_out
  primary_metric: mean_absolute_error
  calibration_metric: expected_calibration_error
  distribution_metric: mean_poisson_deviance
  significance_test: paired_bootstrap
  confidence_level: 0.95
  bootstrap_iterations: 10000
  random_seed: required
```

Player-game rows must never be randomly split. Training observations must occur
before validation observations, and every input must be available at its declared
prediction timestamp. Hyperparameter or model selection decisions must not use the
final held-out evaluation period.

Comparisons use the same eligible player-game cohort. A candidate may not appear
better by silently dropping difficult rows. Coverage differences must be reported
and justified.

### Promotion-critical metrics

These metrics determine whether a model may advance:

| Metric | Definition | Required direction |
| --- | --- | --- |
| Mean Absolute Error (MAE) | Mean absolute difference between projected and actual receptions | Lower, with statistically meaningful improvement |
| Expected Calibration Error (ECE) | Weighted absolute difference between predicted and observed event rates across pre-registered probability bins | Equal or lower |
| Mean Poisson Deviance | Mean Poisson deviance for non-negative reception counts | Lower |

The experiment configuration must define probability events and calibration bins
before evaluation. Empty bins are reported, not silently removed or merged after
results are observed.

### Diagnostic metrics

Diagnostic metrics explain performance but cannot independently justify promotion:

- root mean squared error;
- signed bias;
- prediction and interval coverage;
- sample and missing-prediction counts;
- interval coverage;
- prediction variance.

Win rate, paper ROI, and profitability are not model-promotion metrics.

## Baseline hierarchy

v0.5C establishes the benchmark hierarchy for WR receptions:

| Level | Baseline | Purpose |
| --- | --- | --- |
| L0 | League mean | Sanity check |
| L1 | Previous game | Minimal historical reference |
| L2 | Rolling three-game mean | Short-term form |
| L3 | Rolling five-game mean | Primary historical benchmark |
| L4 | Season-to-date mean | Stable in-season benchmark |
| L5 | Poisson baseline | Analytical count-distribution benchmark |

A career-average baseline may be reported as a diagnostic when sufficient
point-in-time history exists, but it is not part of Governance v1.0's required
hierarchy.

The strongest eligible baseline is selected under the registered v0.5C protocol
and frozen before a learned candidate is evaluated. It must have valid predictions
for the comparison cohort and no unresolved leakage or reproducibility issue.

## Statistical comparisons

Every candidate-to-baseline comparison must report:

- the metric value for each system;
- the paired metric difference in the registered direction;
- a 95% paired-bootstrap confidence interval;
- an effect size;
- the number of evaluated player-games;
- whether the improvement is statistically significant.

Bootstrap sampling and all stochastic operations use the registered seed. Raw
paired metric differences remain the primary interpretation; any standardized
effect-size definition must be declared in the experiment configuration.

For promotion, MAE improvement must be statistically meaningful under the
registered protocol. ECE must be equal or better, and mean Poisson deviance must
improve. All three promotion-critical metrics and their uncertainty must still be
reported when a gate fails.

## Reproducible Baseline Scorecard

Every evaluation produces a versioned scorecard containing:

- dataset manifest hash;
- feature registry hash;
- canonical feature-table hash;
- Git commit SHA;
- configuration hash;
- training period;
- validation period;
- random seed, including an explicit `none` when no randomness exists;
- evaluation timestamp;
- baseline implementation version;
- Governance and Evaluation Protocol versions.

The scorecard includes one row per baseline with MAE, ECE, mean Poisson deviance,
diagnostic metrics, coverage, eligibility, and status. It identifies the strongest
eligible baseline without overwriting prior scorecards.

Canonical scorecard identity excludes volatile evaluation timestamps and physical
file metadata. Those values remain recorded for provenance. Equivalent inputs,
configuration, code, and environment must reproduce the same canonical metrics
and scorecard identity.

Generated datasets, reports, and binary artifacts remain outside Git. Versioned
registries, configuration, schemas, and compact scorecard metadata belong in the
repository.

## Standard failure report

Every evaluation report uses the same structure.

### Overall performance

- MAE;
- RMSE;
- ECE and calibration table;
- mean Poisson deviance;
- bias;
- coverage;
- sample count;
- interval coverage;
- prediction variance.

### Segment performance

- rookies;
- veterans;
- low-volume wide receivers;
- high-volume wide receivers;
- early season;
- late season;
- home;
- away;
- games after bye weeks.

Segment definitions and minimum sample sizes must be pre-registered. Insufficient
samples are labeled explicitly and cannot be interpreted as passing a subgroup
check.

### Error analysis

- largest over-predictions;
- largest under-predictions;
- systematic bias by player;
- systematic bias by team;
- systematic bias by opponent;
- error distribution.

### Data quality

- missing feature frequencies;
- missing prediction frequencies;
- disabled features;
- feature registry version and hash;
- dataset manifest hash;
- canonical feature-table hash;
- unresolved warnings or validation failures.

## Research decisions

Every evaluated candidate receives exactly one decision:

| Decision | Meaning |
| --- | --- |
| `PROMOTE` | Meets every promotion criterion and is eligible for the next governed stage |
| `RESEARCH` | Interesting result with insufficient evidence for promotion |
| `REVISE` | Implementation, data, or feature changes are required before reevaluation |
| `REJECT` | Performs worse than the strongest eligible baseline or fails a decisive gate |

A non-promotion is not automatically a rejection. The report must state which
criteria produced the decision.

## Promotion Gate v1.0

A learned model may advance beyond research only if it:

1. outperforms the strongest eligible baseline on held-out chronological
   validation;
2. demonstrates statistically meaningful MAE improvement using Evaluation
   Protocol v1.0;
3. maintains equal or better calibration and improves mean Poisson deviance;
4. passes predefined rookie, veteran, volume, location, bye-week, and seasonal
   subgroup analyses;
5. has no unresolved leakage, reproducibility, or data-quality issue;
6. is fully reproducible from versioned datasets, feature registries, manifests,
   configuration, code, and implementation metadata; and
7. receives a final `PROMOTE` research decision.

Complexity, favorable in-sample results, isolated profitability, or narrative
plausibility cannot override a failed gate.

## Registry and artifact requirements

Each model registry entry must record:

- model and implementation version;
- feature names and feature registry hash;
- dataset and canonical feature-table identities;
- training and validation windows;
- evaluation configuration and protocol version;
- metrics, calibration results, and subgroup status;
- promotion decision;
- artifact location;
- last training date and Git revision.

Artifacts must be immutable or content-addressed. Re-running an experiment creates
a new result; it does not rewrite historical evidence.

## Governance versioning

- **v1.0:** Initial governance contract.
- **v1.1:** Backward-compatible clarification or additional diagnostic that cannot
  alter an evaluation or promotion outcome.
- **v2.0:** Any change that can affect evaluation results or promotion decisions,
  including primary metrics, statistical tests, validation methodology, or gates.

Governance changes require deliberate review and must not be introduced during an
active research milestone. Historical scorecards always retain the governance
version under which they were produced.

## Safety and claims

Research remains paper-only. EDGE IQ does not place wagers, automate sportsbook
logins, or claim profitability. Model promotion establishes research evidence
under this contract; it does not establish financial performance or production
suitability.
