# EDGEIQ Project Status

Document Status: Current

Applies To: `main @ 0672c8c20b663ba9fce1587406bd69e509f391cb`

Last Updated: 2026-08-03

Maintainers: EDGEIQ Maintainers

---

# Current Release

**v0.10A — Dispatch Decision Foundation Implementation Candidate**

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

The v0.9B Immutable Execution Plan Foundation was squash-merged into `main` through
PR #23.

Merge Commit:

`ed204a86516de5154e9218b7df63cc94756104cb`

The v0.9B Implementation Review Gate and CI passed before merge. The implementation
contains only the authorized immutable Execution Plan foundation. Deterministic
derivation is owned by a registered, versioned planning rule, and retained accepted
Execution Request and Request Validation evidence are verified. Canonical planning
inputs, plan identity, digests, reconstruction, append-only history, scoped
idempotency, expected-version compare-and-swap, and atomic snapshot publication are
implemented.

ADR 0009 and ADR 0010 remain Proposed. Worker Selection changes and all downstream
runtime layers remain outside v0.9B and unauthorized; no downstream runtime authority
was introduced by the merge.

ADR 0011 — Dispatch Decision Foundation was squash-merged into `main` through PR #25
at `0672c8c20b663ba9fce1587406bd69e509f391cb`. ADR 0011 remains Proposed and its
Architecture Review Gate passed. A separate explicit authorization permits only the
bounded v0.10A immutable Dispatch Decision Foundation implementation candidate on its
feature branch. The candidate remains subject to an Implementation Review Gate, CI,
and merge review.

The first v0.10A Implementation Review Gate returned `FAIL` at reviewed head
`a13a973187e6b8af13404a7a0962c8da370d06d3`. Remediation replaces caller-authored
applicability results with authoritative retained Plan, Selection, transitive
Readiness, Lease, and registered-policy evidence; adds rollback-safe repository
publication and authoritative reconstruction; and remains pending a new full gate.
PR #26 remains Draft and unmerged.

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
- ✅ v0.9B Immutable Execution Plan Foundation authorization
- ✅ v0.9B Implementation Review Gate
- ✅ v0.9B squash merge through PR #23

These milestones are complete and considered part of the repository baseline.

---

# Architecture Status

| Artifact | Status |
|----------|--------|
| ADR 0007 — Runtime Architecture Baseline v1 | Effective |
| ADR 0008 — Worker Selection | Accepted |
| ADR 0009 — Execution Request and Deterministic Planning Foundation | Proposed |
| ADR 0010 — Runtime State Machine and Transition Ownership | Proposed |
| ADR 0011 — Dispatch Decision Foundation | Proposed |
| Runtime Architecture | Baseline Established |
| Architecture Review Gate | PASS |
| v0.9A Implementation Review Gate | PASS |
| v0.9B Implementation Review Gate | PASS |

---

# Implemented Capabilities

## Execution Request Foundation

- Immutable accepted Execution Request contracts
- Deterministic canonical serialization, identities, and SHA-256 digests
- Scoped idempotency with explicit equivalent and conflict behavior
- Atomic, concurrency-safe process-local admission
- Organization-isolated retrieval
- Fail-closed reconstruction and retained-content verification

## Execution Plan Foundation

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

This foundation passed its Implementation Review Gate and CI and was squash-merged
through PR #23.

## Worker Selection

- Immutable domain records
- Deterministic worker selection
- Exact fixed-point scoring
- Deterministic tie-breaking
- Canonical serialization
- Stable hashes and identifiers

## Dispatch Decision Foundation Candidate

- Immutable organization-scoped approval or denial evidence for one offer
- Retained Execution Plan, Worker Selection, transitive readiness, Execution Lease,
  causal authorization, policy, configuration, and time-evidence references
- Canonical serialization, SHA-256 digests, and deterministic decision identities
- Candidate-specific append-only process-local history
- Scoped idempotency and expected-version compare-and-swap
- Organization-isolated retrieval and fail-closed validation
- Deterministic reconstruction and replay-divergence detection
- No claim, exclusivity, queue message, lease mutation, execution, or external effect

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
| Execution Plan tests | 35 passed |
| Dispatch Decision tests | 31 passed |
| Runtime tests | 127 passed |
| Full test suite | 288 passed |
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
| Dispatch | Authorized foundation candidate; under review |
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
- The Execution Plan adapter is process-local; durable persistence remains deferred.
- No end-to-end task execution path exists.
- Prototype readiness depends on satisfying every acceptance criterion defined in
  `ROADMAP.md`; v0.9A and v0.9B together remain insufficient.
- v0.9B is complete on `main`, but it does not provide an end-to-end runtime path.
- Downstream runtime milestones remain unauthorized.
- The v0.10A candidate records Dispatch approval or denial only. It provides no Work
  Claim, queue transport, execution path, external effect, or end-to-end prototype.

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
- The separately authorized v0.9B immutable Execution Plan foundation passed its
  Implementation Review Gate and CI and was squash-merged through PR #23.
- The completed v0.9B implementation is limited to the immutable Execution Plan
  foundation.
- Worker Selection changes and downstream runtime layers remain outside v0.9B.
- ADR 0011 is merged, remains Proposed, and its Architecture Review Gate passed.
- v0.10A implementation authorization is limited to the immutable Dispatch Decision
  foundation candidate; its Implementation Review Gate and merge review remain
  pending.
- The first v0.10A Implementation Review Gate failed; focused remediation is pending
  re-evaluation on Draft PR #26.
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

# Completed v0.9B Scope

## v0.9B — Immutable Execution Plan Foundation

Merged scope:

1. Immutable Execution Plan contracts derived by a registered versioned rule from
   one retained accepted Execution Request, its retained valid Request Validation
   evidence, and immutable policy/configuration inputs.
2. Deterministic canonical input and plan serialization, identities, and digests.
3. Plan schema, planning-rule, policy, and configuration version retention.
4. Scoped idempotency, expected-version concurrency, and append-only reference
   history.
5. Atomic process-local publication and fail-closed reconstruction.

**Only this immutable Execution Plan foundation slice was authorized and merged.**

The merge introduces no Worker Readiness, Worker Selection changes, Authorization
Checkpoint, Dispatch Decision, Work Claim, Execution Lease, Queue Envelope,
Execution Attempt, Execution Monitoring, Completion, Retry Policy, providers,
models, scheduling, orchestration, APIs, external effects, or authority for later
runtime milestones. ADR 0009 and ADR 0010 remain Proposed.

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
