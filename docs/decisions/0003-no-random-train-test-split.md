# ADR 0003: Prohibit random player-game train/test splits

- Status: Accepted
- Date: 2026-07-16

## Context

Randomly splitting player-game rows allows later games and related observations to
inform training for earlier predictions.

## Decision

Do not use random train/test splits for model selection or reported WR-receptions
performance. Split strictly by event time and audit every feature as-of kickoff.

## Consequences

Some familiar machine-learning helpers cannot be used directly. Leakage tests are a
release requirement, not optional research cleanup.
