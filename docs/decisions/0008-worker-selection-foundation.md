# ADR 0008: Worker Selection Foundation

Status: Proposed

## Context

Runtime Architecture Baseline v1 is effective. The next runtime capability must be
designed entirely under its ownership, history, replay, concurrency, security,
dependency, and review-gate rules.

Worker Selection needs to answer which contextually ready workers are the best
candidates for an immutable workload context without taking responsibility for any
downstream operational effect.

## Proposed decision

Adopt [Worker Selection Foundation](../runtime/WORKER_SELECTION.md) as a deterministic,
explainable candidate-ordering boundary.

Worker Selection would own selection outcomes, scores, ranks, explanations, reason
codes, immutable selection history, and a derived current pointer. It would not own
readiness, identity, trust, health, authorization, scheduling, dispatch, queues,
leases, claims, execution, retries, completion, or worker lifecycle.

Implementation remains unauthorized while the
[Architecture Review Gate](../runtime/proposals/WORKER_SELECTION_ARCHITECTURE_REVIEW.md)
is pending and the initial scoring policy constants remain unspecified.

## Rationale

Separating candidate ordering from dispatch preserves the baseline's distinction
between decision and effect. Explicit scores and stable tie-breakers support replay
and audit without an opaque ranking model.

## Consequences

- all inputs must be retained upstream artifacts or versioned preference evidence;
- identical canonical inputs must reproduce identical ordering;
- selection history is immutable and current ranking is a rebuildable projection;
- future implementation must pre-register scoring weights and decimal rules; and
- dispatch and every downstream effect require separate components and reviews.

## Status transition

This ADR may move to `Accepted` only after formal gate review. Acceptance does not by
itself grant implementation authorization.
