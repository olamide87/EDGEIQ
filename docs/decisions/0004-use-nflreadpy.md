# ADR 0004: Use nflreadpy as the nflverse adapter

- Status: Accepted
- Date: 2026-07-16

## Context

EDGE IQ needs an authorized, reproducible route to nflverse schedules, rosters,
player statistics, participation, snaps, injuries, and play-by-play data.

## Decision

Use `nflreadpy` behind an EDGE IQ adapter. Preserve source repository, capture time,
schema, seasons, hashes, and dataset-specific license/attribution in manifests. Tests
use committed synthetic fixtures and never require network access.

## Consequences

The adapter shields the project from upstream schema changes, which must fail clearly
rather than silently alter training data. nflverse dataset licenses must be reviewed
per source; the participation data has different attribution terms from most feeds.
