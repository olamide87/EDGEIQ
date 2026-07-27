# EDGEIQ Project Status

Document Status: Current

Applies To: `main @ 7e210cc`

Last Updated: 2026-07-27

Maintainers: EDGEIQ Maintainers

---

# Current Release

**v0.9A — Execution Request Foundation**

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
Deterministic execution planning remains unauthorized. Worker Selection changes and
all downstream runtime layers remain outside v0.9A.

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
| Runtime Architecture | Baseline Established |
| Architecture Review Gate | PASS |
| v0.9A Implementation Review Gate | PASS |

---

# Implemented Capabilities

## Execution Request Foundation

- Immutable accepted Execution Request contracts
- Deterministic canonical serialization, identities, and SHA-256 digests
- Scoped idempotency with explicit equivalent and conflict behavior
- Atomic, concurrency-safe process-local admission
- Organization-isolated retrieval
- Fail-closed reconstruction and retained-content verification

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
- No end-to-end task execution path exists.
- Prototype readiness depends on satisfying every acceptance criterion defined in
  `ROADMAP.md`; v0.9A alone is insufficient.
- Deterministic planning and downstream runtime milestones remain unauthorized.

---

# Current Governance State

- Roadmap reconciliation is complete.
- Objective Prototype Acceptance Criteria are defined in `ROADMAP.md`.
- ADR 0009 is merged, remains Proposed, and its Architecture Review Gate passed.
- v0.9A Execution Request Foundation was explicitly authorized, passed its
  Implementation Review Gate, passed CI, and was squash-merged through PR #20.
- The completed v0.9A implementation is limited to the immutable Execution Request
  foundation.
- Deterministic execution planning remains unauthorized.
- Worker Selection changes and downstream runtime layers remain outside v0.9A.
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
authorized by this merge. No v0.9B implementation is authorized.

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
