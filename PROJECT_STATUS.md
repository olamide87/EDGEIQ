# EDGEIQ Project Status

Document Status: Current

Applies To: `main @ 386fa49`

Last Updated: 2026-07-26

Maintainers: EDGEIQ Maintainers

---

# Current Release

**v0.8 — Worker Selection Foundation**

---

# Current State

The Worker Selection Foundation has been merged into `main`.

Merge Commit:

`ae9e80a`

The Runtime Architecture Baseline is now effective, and the Worker Selection Foundation is part of the primary runtime.

ADR 0009 is present on `main` with status Proposed and its Architecture Review Gate
has passed. A separate authorization permits implementation of the request-only
v0.9A Execution Request Foundation slice. That implementation is not yet merged.
Deterministic planning and every downstream runtime behavior remain unauthorized.

---

# Completed Milestones

- ✅ Runtime Architecture Baseline v1
- ✅ Architecture Review Gate
- ✅ Worker Selection ADR
- ✅ Implementation Authorization
- ✅ Worker Selection Foundation
- ✅ Review
- ✅ Merge into `main`

These milestones are complete and considered part of the repository baseline.

---

# Architecture Status

| Artifact | Status |
|----------|--------|
| ADR 0007 — Runtime Architecture Baseline v1 | Effective |
| ADR 0008 — Worker Selection | Accepted |
| Runtime Architecture | Baseline Established |
| Architecture Review Gate | PASS |

---

# Implemented Capabilities

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
| Full test suite | 192 passed |
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
- No end-to-end task execution path exists.
- Prototype readiness cannot be declared until roadmap reconciliation is complete.
- Future runtime milestones have not yet been authorized.

---

# Current Blockers

- Repository roadmap has not yet been reconciled with `main`.
- Prototype acceptance criteria have not been formally defined.
- The next runtime milestone has not yet been selected through governance.

---

# Authorized Current Activity

## v0.9A — Execution Request Foundation

Authorized scope:

1. Immutable accepted Execution Request contracts.
2. Deterministic canonicalization, identities, and digest verification.
3. Idempotent, concurrency-safe request admission.
4. Fail-closed reconstruction from retained canonical content.
5. Persistence abstractions and reference adapters required by this slice.

**Only this request foundation slice is authorized for implementation.**

Execution Plans, deterministic planning, Worker Selection changes, dispatch, claims,
leases, execution, retries, monitoring, completion, and orchestration are not
authorized by this status document or by the v0.9A authorization.

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
