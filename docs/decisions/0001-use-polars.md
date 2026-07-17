# ADR 0001: Use Polars for historical NFL data

- Status: Accepted
- Date: 2026-07-16

## Context

The research pipeline needs typed columnar transforms over multiple NFL seasons
without making pandas the shared data contract.

## Decision

Use Polars data frames and Parquet at data-pipeline boundaries. Convert to NumPy
only at a model library boundary when required and documented.

## Consequences

Transforms remain explicit and efficient, but contributors must understand Polars
expressions and verify library compatibility when upgrading.
