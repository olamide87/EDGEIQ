# ADR 0006: Point-in-time feature semantics

- Status: Accepted
- Date: 2026-07-18

## Context

WR outcomes and usage become known after kickoff. Using a current or future outcome
in a pregame feature would make offline results impossible to reproduce live.
Trades, simultaneous game rows, season boundaries, and missing supporting datasets
make the availability boundary easy to violate accidentally.

## Decision

The v0.5B builder orders rows by kickoff, game ID, and stable source player ID. It
materializes all rows in a game before updating any history. Player outcome and
usage features use only completed games and follow the source player ID across
teams. Player rolling windows carry across seasons; season-to-date features reset.
Team and opponent histories key on season and team, so they reset each season.

Pregame schedule fields may be copied directly. Rest days come from prior recorded
player appearances. Missing source values remain null unless the registry declares
a visible indicator or another explicit policy. Final scores, current-game usage,
postgame injury data, and future rows are prohibited.

Canonical output ordering, content hashing, source-manifest references, and atomic
Parquet/manifest replacement are part of the feature-table contract.

## Consequences

Early-career and first-game-of-season rows can have substantial null coverage.
Offseason player rolling history may be informative or harmful; v0.5C/D must test
that rather than changing it implicitly. Team and opponent context deliberately
discard prior-season history. Route participation and snap share remain null unless
a trustworthy source-ID keyed pre-aggregated input is supplied.
