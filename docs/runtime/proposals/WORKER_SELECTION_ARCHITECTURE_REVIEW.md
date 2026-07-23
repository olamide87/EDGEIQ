# Worker Selection Architecture Review Gate

Proposal: Worker Selection Foundation
Milestone: Next runtime design milestone after v0.7A
Governing baseline: Runtime Architecture Baseline v1
Related design: [Worker Selection Foundation](../WORKER_SELECTION.md)
Overall result: Pending formal review
Implementation authorization: Not granted

This gate evaluates the proposed architecture only. A proposed `PASS` means the
documented boundary satisfies the baseline; it does not authorize implementation.

## 1. Semantic ownership

Result: **PASS — proposed**

Evidence:

- Selection owns only deterministic candidate ordering, scores, ranks,
  explanations, outcomes, and its derived current pointer.
- Readiness, identity, trust, health, authorization, dispatch, claims, execution,
  retries, and lifecycle are explicitly excluded.
- The evaluator is separated from persistence and external effects.

Required design changes: None identified.

## 2. Immutable history

Result: **PASS — proposed**

Evidence:

- `WorkerSelection` is an immutable historical evaluation.
- Replacement creates a new stream version.
- Only `WorkerSelectionCurrent` is mutable and derived.
- The current pointer may reference only committed history and is rebuildable.
- Candidate hashes retain ordered evidence and ranking details.

Required design changes: None identified.

## 3. Deterministic replay

Result: **PASS — proposed**

Evidence:

- Replay inputs include artifact hashes, policy and evaluator versions,
  configuration, serialization, ordering rule, and history boundary.
- Replay excludes current health, queues, providers, dispatch, and execution state.
- Exact output hashes and divergence failures are required.
- Volatile persistence timestamps do not enter semantic identity.

Required design changes: None identified.

## 4. Concurrency

Result: **PASS — proposed**

Evidence:

- Organization plus workload context defines aggregate ownership.
- Appends require expected-version compare-and-swap.
- Idempotency and content-conflict scopes are explicit.
- Stale decisions are recomputed after reload.
- Timestamps do not arbitrate races.
- Rollback uses new history; pointers cannot orphan selections.

Required design changes: None identified.

## 5. Security boundaries

Result: **PASS — proposed**

Evidence:

- Organization scope and input integrity are validated fail-closed.
- Validation does not transfer ownership.
- Selection cannot authenticate, authorize, prove trust, validate leases, consume
  queues, or change readiness.
- Explanations and errors require redacted stable reason codes.

Required design changes: None identified.

## 6. Dependency direction

Result: **PASS — proposed**

Evidence:

- Required dependencies are Execution Plan, workload and capability requirements,
  policies, and Worker Readiness.
- Optional preferences must be retained and versioned.
- Dispatch, claims, queues, monitoring, completion, output, providers, and retry state
  are forbidden inputs.

Required design changes: None identified.

## 7. Negative routes

Result: **PASS — proposed**

Evidence:

- Stable validation, evidence, policy, concurrency, replay, persistence, and internal
  errors are defined.
- Empty successful selections are prohibited.
- `/dispatch`, `/claim`, `/execute`, `/start`, `/retry`, `/invoke`, and `/schedule`
  are explicitly absent and must return `404`.

Required design changes: None identified.

## 8. Extension points

Result: **PASS WITH OPEN IMPLEMENTATION DETAIL — proposed**

Evidence:

- Scoring policy is versioned and must declare components, evidence, normalization,
  bounds, weights, rounding, missing-evidence behavior, and reason codes.
- No opaque or machine-learned score is allowed.

Required design changes before implementation authorization:

- pre-register the initial scoring weights and fixed-decimal precision;
- define component-specific missing-evidence behavior; and
- identify the repository-specific extension registration mechanism.

These details do not block architectural design review but do block implementation
authorization.

## 9. Documentation completeness

Result: **PASS — proposed**

Evidence:

- Purpose, non-goals, ownership, lifecycle position, conceptual interfaces, models,
  ordering, replay, concurrency, security, errors, tests, acceptance, and deferred
  work are documented.
- Conceptual vocabulary is explicitly distinguished from implementation commitments.

Required design changes: None identified.

## Final decision

```text
Overall result: PENDING FORMAL REVIEW
Blocking architecture failures: none identified
Implementation blockers: scoring policy constants and repository-specific placement
Implementation authorization: NOT GRANTED
Reviewer: pending
Decision date: pending
```

The next decision may approve the architecture boundary while retaining the listed
implementation blockers. No Worker Selection code should be written until this gate
is formally reviewed and separate implementation authorization is granted.
