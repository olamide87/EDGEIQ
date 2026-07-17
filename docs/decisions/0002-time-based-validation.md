# ADR 0002: Use time-based model validation

- Status: Accepted
- Date: 2026-07-16

## Context

Predictions are made forward in time, while NFL roles, teams, and environments drift.

## Decision

Use expanding-season validation and retain the latest complete season as the final
holdout. Weekly rolling-origin evaluation may supplement, but not replace, it.

## Consequences

Reported performance better represents deployment and will usually be less flattering
than random validation. Final holdout results remain untouched during tuning.
