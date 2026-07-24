# Worker Selection Architecture Review Gate

Proposal: Worker Selection Foundation
Milestone: Next runtime design milestone after v0.7A
Governing baseline: Runtime Architecture Baseline v1
Related design: [Worker Selection Foundation](../WORKER_SELECTION.md)
Overall result: Pass
Implementation authorization: Not granted

This gate evaluates the architecture only. `PASS` means the documented boundary
satisfies the baseline and recommends a separate implementation-authorization
decision. It does not itself authorize implementation.

## 1. Semantic ownership

Result: **PASS**

Evidence:

- Selection owns only deterministic candidate ordering, scores, ranks,
  explanations, outcomes, and its derived current pointer.
- Readiness, identity, trust, health, authorization, dispatch, claims, execution,
  retries, and lifecycle are explicitly excluded.
- The evaluator is separated from persistence and external effects.

Required design changes: None identified.

## 2. Immutable history

Result: **PASS**

Evidence:

- `WorkerSelection` is an immutable historical evaluation.
- Replacement creates a new stream version.
- Only `WorkerSelectionCurrent` is mutable and derived.
- The current pointer may reference only committed history and is rebuildable.
- Candidate hashes retain ordered evidence and ranking details.

Required design changes: None identified.

## 3. Deterministic replay

Result: **PASS**

Evidence:

- Replay inputs include artifact hashes, policy and evaluator versions,
  configuration, serialization, ordering rule, and history boundary.
- Replay excludes current health, queues, providers, dispatch, and execution state.
- Exact output hashes and divergence failures are required.
- Volatile persistence timestamps do not enter semantic identity.

Required design changes: None identified.

## 4. Concurrency

Result: **PASS**

Evidence:

- Organization plus workload context defines aggregate ownership.
- Appends require expected-version compare-and-swap.
- Idempotency and content-conflict scopes are explicit.
- Stale decisions are recomputed after reload.
- Timestamps do not arbitrate races.
- Rollback uses new history; pointers cannot orphan selections.

Required design changes: None identified.

## 5. Security boundaries

Result: **PASS**

Evidence:

- Organization scope and input integrity are validated fail-closed.
- Validation does not transfer ownership.
- Selection cannot authenticate, authorize, prove trust, validate leases, consume
  queues, or change readiness.
- Explanations and errors require redacted stable reason codes.

Required design changes: None identified.

## 6. Dependency direction

Result: **PASS**

Evidence:

- Required dependencies are Execution Plan, workload and capability requirements,
  policies, and Worker Readiness.
- Optional preferences must be retained and versioned.
- Dispatch, claims, queues, monitoring, completion, output, providers, and retry state
  are forbidden inputs.

Required design changes: None identified.

## 7. Negative routes

Result: **PASS**

Evidence:

- Stable validation, evidence, policy, concurrency, replay, persistence, and internal
  errors are defined.
- Empty successful selections are prohibited.
- `/dispatch`, `/claim`, `/execute`, `/start`, `/retry`, `/invoke`, and `/schedule`
  are explicitly absent and must return `404`.

Required design changes: None identified.

## 8. Extension points

Result: **PASS**

Evidence:

- ScoringPolicyV1 registers six components in immutable order with fixed weights
  `40/20/15/10/10/5`.
- Required capabilities and hard policy constraints are eligibility gates.
- Six-place exact decimals and round-half-even rules are specified.
- Missing optional evidence scores zero with component-specific reason codes.
- Registration uses an immutable tuple keyed by exact policy version; dynamic or
  unordered discovery is prohibited.
- No opaque or machine-learned score is allowed.

Required design changes: None identified.

## 9. Documentation completeness

Result: **PASS**

Evidence:

- Purpose, non-goals, ownership, lifecycle position, conceptual interfaces, models,
  ordering, replay, concurrency, security, errors, tests, acceptance, and deferred
  work are documented.
- Conceptual vocabulary is explicitly distinguished from implementation commitments.

Required design changes: None identified.

## Final decision

```text
Overall result: PASS
Blocking architecture failures: none identified
Unresolved design deficiencies: none
Recommendation: GRANT IMPLEMENTATION AUTHORIZATION THROUGH A SEPARATE DECISION
Implementation authorization: NOT GRANTED
Reviewer: Architecture Review Gate self-review against ADR 0007
Decision date: 2026-07-22
```

The gate has a binary `PASS` outcome. No conditional approval remains. No Worker
Selection code should be written until a separate implementation-authorization
decision is formally granted.
