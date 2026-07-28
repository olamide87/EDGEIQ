# EDGEIQ Project Status

Document Status: Current

Applies To: `main @ b683221` plus the unmerged v0.9B implementation candidate

Last Updated: 2026-07-28

Maintainers: EDGEIQ Maintainers

---

# Current Release

**v0.9B — Immutable Execution Plan Foundation (Implementation Under Review)**

---

# Current State

The v0.9A Execution Request Foundation has been squash-merged into `main` through
PR #20.

Merge Commit:

`7e210cc976b1c79644b2d5bd2fdf3ece7a5c39cf`

The implementation adds only the immutable Execution Request foundation:
deterministic canonicalization and digests, immutable accepted requests, idempotent
and concurrency-safe admission, organization-isolated retrieval, and fail-closed
reconstruction.

ADR 0009 is present on `main` with status Proposed and its Architecture Review Gate
has passed. The v0.9A Implementation Review Gate and CI passed before merge.
ADR 0010 is also present on `main` with status Proposed and its Architecture Review
Gate passed.

A separately authorized v0.9B implementation candidate adds only the immutable
Execution Plan foundation. It remains unmerged and subject to Implementation Review
Gate and CI. Worker Selection changes and all downstream runtime layers remain
outside v0.9B and unauthorized.

---

# Completed Milestones

- ✅ Runtime Architecture Baseline v1
- ✅ Architecture Review Gate
- ✅ Worker Selection ADR
- ✅ Implementation Authorization
- ✅ Worker Selection Foundation
- ✅ Review
- ✅ Merge into `main`
- ✅ v0.9A Execution Request Foundation authorization
- ✅ v0.9A Implementation Review Gate
- ✅ v0.9A squash merge through PR #20

These milestones are complete and considered part of the repository baseline.

---

# Architecture Status

| Artifact | Status |
|----------|--------|
| ADR 0007 — Runtime Architecture Baseline v1 | Effective |
| ADR 0008 — Worker Selection | Accepted |
| ADR 0009 — Execution Request and Deterministic Planning Foundation | Proposed |
| ADR 0010 — Runtime State Machine and Transition Ownership | Proposed |
| Runtime Architecture | Baseline Established |
| Architecture Review Gate | PASS |
| v0.9A Implementation Review Gate | PASS |
| v0.9B Implementation Review Gate | Pending |

---

# Implemented Capabilities

## Execution Request Foundation

- Immutable accepted Execution Request contracts
- Deterministic canonical serialization, identities, and SHA-256 digests
- Scoped idempotency with explicit equivalent and conflict behavior
- Atomic, concurrency-safe process-local admission
- Organization-isolated retrieval
- Fail-closed reconstruction and retained-content verification

## Candidate Execution Plan Foundation (Not Merged)

- Immutable, organization-scoped Execution Plan contracts
- Deterministic construction by a registered versioned rule from retained accepted
  Execution Requests, retained Request Validation evidence, and immutable
  policy/configuration inputs
- Canonical input and plan serialization, identities, and SHA-256 digests
- Plan schema, planning-rule, policy, and configuration version retention
- Append-only process-local reference history and current projection
- Scoped idempotency and expected-version compare-and-swap
- Atomic immutable snapshot publication
- Fail-closed reconstruction and replay-divergence detection

This candidate remains subject to implementation review and does not represent a
completed or merged capability.

## Worker Selection

- Immutable domain records
- Deterministic worker selection
- Exact fixed-point scoring
- Deterministic tie-breaking
- Canonical serialization
- Stable hashes and identifiers

## Replay & Audit

- Replay metadata
- Append-only reference history
- Deterministic replay
- Divergence detection

## Concurrency

- Compare-and-swap concurrency control
- Scoped idempotency

## APIs

- Evaluate API
- Read API
- History API
- Current Selection API

## Isolation

- Cross-organization read isolation
- Explicit `404` behavior for forbidden operational routes

---

# Validation Baseline

| Validation | Status |
|------------|--------|
| Worker Selection tests | 31 passed |
| Execution Request tests | 34 passed |
| Full test suite | 226 passed |
| Python compilation | PASS |
| CI | PASS |
| `git diff --check` | PASS |
| Dependency audit | PASS |
| Ordering audit | PASS |
| Mutation audit | PASS |
| Route audit | PASS |

---

# Prototype Readiness

| Capability | Status |
|------------|--------|
| Runtime Architecture Baseline | Complete |
| Worker Identity | Existing / Verify |
| Worker Readiness | Existing / Verify |
| Worker Selection | Complete |
| Durable Persistence | Deferred |
| Task Submission | Not Started |
| Dispatch | Deferred |
| Scheduling | Deferred |
| Claims & Leases | Deferred |
| Worker Execution | Not Started |
| Retry Handling | Deferred |
| Orchestration | Deferred |
| Observability | Not Started |
| End-to-End Prototype | Not Yet Available |

---

# Deferred Scope

The following capabilities are intentionally excluded from the Worker Selection Foundation.

- Durable distributed persistence
- Dispatch
- Scheduling
- Claims
- Leases
- Queues
- Worker execution
- Retry orchestration
- Runtime orchestration
- Worker readiness ownership changes

Deferred capabilities require future planning and, where applicable, architectural governance before implementation.

---

# Current Risks

- Selection history adapter remains process-local.
- The Execution Request adapter is process-local; durable persistence remains
  deferred.
- The candidate Execution Plan adapter is process-local; durable persistence remains
  deferred.
- No end-to-end task execution path exists.
- Prototype readiness depends on satisfying every acceptance criterion defined in
  `ROADMAP.md`; v0.9A alone is insufficient.
- The v0.9B implementation candidate remains unmerged and under review.
- Downstream runtime milestones remain unauthorized.

---

# Current Governance State

- Roadmap reconciliation is complete.
- Objective Prototype Acceptance Criteria are defined in `ROADMAP.md`.
- ADR 0009 is merged, remains Proposed, and its Architecture Review Gate passed.
- v0.9A Execution Request Foundation was explicitly authorized, passed its
  Implementation Review Gate, passed CI, and was squash-merged through PR #20.
- The completed v0.9A implementation is limited to the immutable Execution Request
  foundation.
- ADR 0010 is merged, remains Proposed, and its Architecture Review Gate passed.
- A separate authorization permits only the v0.9B immutable Execution Plan
  foundation implementation candidate.
- Worker Selection changes and downstream runtime layers remain outside v0.9B.
- Further implementation requires separate explicit authorization.

---

# Completed v0.9A Scope

## v0.9A — Execution Request Foundation

Merged scope:

1. Immutable accepted Execution Request contracts.
2. Deterministic canonicalization, identities, and digest verification.
3. Idempotent, concurrency-safe request admission.
4. Fail-closed reconstruction from retained canonical content.
5. Persistence abstractions and reference adapters required by this slice.

**Only this request foundation slice was authorized and merged.**

Execution Plans, deterministic planning, Worker Selection changes, dispatch, claims,
leases, execution, retries, monitoring, completion, and orchestration are not
authorized by the v0.9A merge.

---

# Candidate v0.9B Scope

## v0.9B — Immutable Execution Plan Foundation

Authorized implementation-review scope:

1. Immutable Execution Plan contracts derived by a registered versioned rule from
   one retained accepted Execution Request, its retained valid Request Validation
   evidence, and immutable policy/configuration inputs.
2. Deterministic canonical input and plan serialization, identities, and digests.
3. Plan schema, planning-rule, policy, and configuration version retention.
4. Scoped idempotency, expected-version concurrency, and append-only reference
   history.
5. Atomic process-local publication and fail-closed reconstruction.

**This candidate is not complete or merged.**

It introduces no Worker Readiness, Worker Selection changes, Authorization
Checkpoint, lease, queue, dispatch, claim, attempt, execution, monitoring,
completion, retry, scheduling, orchestration, provider calls, model calls, or
external side effects. ADR 0009 and ADR 0010 remain Proposed.

---

# Repository Rules

- Architecture changes require an accepted ADR.
- Material deviation from an accepted ADR requires a new or amended ADR.
- Deferred runtime capabilities shall not be introduced through implementation convenience.
- Every implementation milestone shall update both:
  - `PROJECT_STATUS.md`
  - `ROADMAP.md`
- Repository status shall accurately reflect the current state of `main`.

---

# Governance Statement

This document is a repository status report.

It records the current implementation baseline and governance state.

It does **not**:

- authorize implementation;
- approve architectural changes;
- modify or supersede accepted ADRs;
- establish future milestones; or
- replace the project's governance process.

Authorization for new implementation work must be granted through the established EDGEIQ governance workflow.
