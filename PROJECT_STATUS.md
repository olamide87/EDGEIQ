# EDGEIQ Project Status

Document Status: Current

Applies To: `main @ e39ab7ad9d308a8c44f8a47d54653f46e9c70061`

Last Updated: 2026-08-17

Maintainers: EDGEIQ Maintainers

---

# Current Release

**v0.10B — Work Claim Foundation**

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
Architecture Review Gate passed. The separately authorized bounded v0.10A immutable
Dispatch Decision Foundation passed its Implementation Review Gate and CI and was
squash-merged through PR #26 at
`b8881b6e0b736c5736fb34e2908bce16a81b08e1`.

ADR 0012 — Work Claim Foundation was squash-merged into `main` through PR #27 at
`706f43525b208b6f0a327834b4b71336f7f41214`. ADR 0012 remains Proposed and its
Architecture Review Gate passed after the work-item lineage and fencing remediation.
The documentation-only Work Claim implementation authorization package passed its
Governance Review Gate and CI and was squash-merged through PR #28 at
`6d8e22a1e226198b7df8e3ac846ef2672ede29de`. The bounded authorization defined below
is now effective. ADR 0012 remains Proposed and was not modified by the authorization
package.

The authorized v0.10B Work Claim Foundation passed its Implementation Review Gate
with non-blocking documentation notes and passed CI before PR #30 was squash-merged
into `main` at `df6cc09edbd2adae871b75aabab407debdcd8f4b`. The implementation
authorization has been exercised, the bounded foundation is implemented on `main`,
and its implementation review is complete. No Execution Attempt, Queue Envelope,
execution, monitoring, completion, retry, scheduling, orchestration, provider/model,
API, migration, durable distributed persistence, or other downstream implementation
exists.

ADR 0013 — Execution Lease Foundation was squash-merged through PR #32 at
`e39ab7ad9d308a8c44f8a47d54653f46e9c70061`. ADR 0013 remains Proposed, and its
Architecture Review Gate passed with no blocking findings. The documentation-only
implementation-authorization package was squash-merged through PR #33, reviewed
at `33acfe5c55cafd16805aca2481c211c47108cddf`, into `main` at
`543a5d787c9fcd8bda4c1b67e96c69aab3f379c2`. Its Governance Review Gate and CI
passed, so the bounded authorization described below is now effective. The
`feature/execution-lease-foundation` branch now contains an implementation candidate
intended only for a Draft PR. It is not merged or part of `main`; a complete
Implementation Review Gate, CI, and merge review remain required.

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
- ✅ v0.10A Dispatch Decision Foundation authorization
- ✅ v0.10A Implementation Review Gate
- ✅ v0.10A squash merge through PR #26
- ✅ ADR 0012 Architecture Review Gate
- ✅ v0.10B Implementation Review Gate with non-blocking documentation notes
- ✅ v0.10B CI
- ✅ v0.10B squash merge through PR #30

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
| ADR 0012 — Work Claim Foundation | Proposed |
| ADR 0013 — Execution Lease Foundation | Proposed; Architecture Review Gate PASS |
| Runtime Architecture | Baseline Established |
| Architecture Review Gate | PASS |
| v0.9A Implementation Review Gate | PASS |
| v0.9B Implementation Review Gate | PASS |
| v0.10A Implementation Review Gate | PASS |
| v0.10B Implementation Review Gate | PASS WITH NON-BLOCKING NOTES |

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

## Dispatch Decision Foundation

- Immutable organization-scoped approval or denial evidence for one offer
- Retained Execution Plan, Worker Selection, transitive readiness, Execution Lease,
  causal authorization, policy, configuration, and time-evidence references
- Canonical serialization, SHA-256 digests, and deterministic decision identities
- Candidate-specific append-only process-local history
- Scoped idempotency and expected-version compare-and-swap
- Organization-isolated retrieval and fail-closed validation
- Deterministic reconstruction and replay-divergence detection
- No claim, exclusivity, queue message, lease mutation, execution, or external effect

This foundation passed its Implementation Review Gate and CI and was squash-merged
through PR #26.

## Implemented Work Claim Foundation

ADR 0012 is the sole architectural basis for this authorization and remains Proposed.
ADRs 0007–0011 remain controlling. ADR 0012's Architecture Review Gate passed, and
the separate implementation authorization package passed its Governance Review Gate
and CI before its squash merge through PR #28. ADR 0012 itself was not modified.

Because PR #28 merged into `main`, implementation authorization became effective and
remained limited to the following scope. PR #30 exercised that authorization and
successfully merged the bounded implementation:

- immutable Work Claim artifacts, including lineage events and records;
- canonical UTF-8 serialization, deterministic identities, and canonical digests;
- one authoritative lineage keyed only by `organization_id`,
  `workload_context_id`, `plan_id`, and `work_item_id`;
- lineage stream version ordering every lifecycle event;
- owner-assigned monotonic claim generation stored as immutable event content, with
  one unique next generation under expected-version CAS and a later generation only
  after valid expiry or release;
- an acceptance-only monotonic fence across the entire lineage, strictly separate
  from lineage version and generation;
- append-only acceptance, retained rejection, expiry, and release evidence;
- scoped idempotency, expected-version CAS, and rollback-safe owner-scoped atomic
  publication;
- deterministic reconstruction, fail-closed validation, and organization/workload
  isolation; and
- bounded implementation documentation and focused unit tests for this foundation.

Generation, claimant identity, candidate identity, and Dispatch identity are
canonical event inputs, not lineage identity. Competing claimants and
candidate-specific Dispatch approvals share the same exclusivity lineage. Every
lifecycle transition uses one lineage CAS boundary: only one successor may commit at
one expected version, while stale writers append nothing and reload. There is no
cross-stream atomicity, timestamp arbitration, last-write-wins, caller-selected or
timestamp-derived generation, or timestamp-derived fence. Only acceptance advances
the fence; rejection, expiry, release, and generation creation neither become nor
reuse fences. Every later accepted claim has a fence greater than every earlier
accepted claim.

One approved Dispatch Decision is the direct upstream semantic input. Work Claim may
resolve or reconstruct it only to verify identity, digest, scope, approval,
applicability, and causal integrity. Plan, selection, readiness, Authorization
Checkpoint, and Execution Lease semantics remain with their existing owners. Work
Claim must not re-evaluate Dispatch policy, re-authorize, recompute readiness, rerank
candidates, or grant, renew, revoke, extend, or reinterpret a lease. Newer Dispatch
evidence alone cannot supersede an active claim or create another generation.

Claimant support is limited to retained evidence sufficient to verify authenticated
claimant identity, selected-candidate equivalence, organization/workload scope,
evidence identity and digest, supported schema/version, and applicability to the
approved offer. Work Claim verifies this evidence only. The candidate cannot create
or change Worker Identity semantics, authentication infrastructure, trust, health,
readiness, authorization, or a general identity system.

With complete authoritative evidence, immutable domain outcomes may be accepted,
rejected where ADR 0012 retains rejection, expired, or released. Malformed input;
missing or inaccessible evidence; unsupported schema, policy, component, or
serialization versions; digest or scope mismatch; claimant/candidate mismatch caused
by invalid evidence; idempotency or expected-version conflict; illegal lineage
transition; duplicate or skipped generation; non-monotonic or reused fence;
persistence or reconstruction failure; replay divergence; and internal failure remain
explicit fail-closed failures and are never normalized into acceptance or rejection.

Reconstruction requires complete authoritative lineage history with contiguous
versions; exact approved Dispatch, claimant, claim-policy identity/version/digest,
semantic-time, expiry, release, schema, component, serialization, configuration,
generation, and fence evidence. It reproduces generation boundaries, accepted
claimant, outcomes, current derived claim, next permitted generation, every fence,
canonical input, identity, content, and digest. It rejects lineage gaps; skipped or
duplicate generations; multiple acceptances in one generation; generation before
prior termination; duplicate/non-monotonic fences; altered or missing upstream
evidence; policy divergence; and canonical-content divergence. Replay uses no current
time, live worker state, queues, authoritative projection, provider, execution
result, ambient mutable configuration, or external system.

One owner-scoped logical commit may publish only one immutable lineage event, the
lineage-history update, a repository-owned derived pointer/index, generation and
fence assignments when applicable, and the idempotency index entry. Preparation
precedes publication. Failure exposes no partial event, generation, fence, history
entry, ID index, idempotency entry, or current pointer, and previously accepted
state remains unchanged. Atomic creation or mutation of Dispatch Decision, Execution
Lease, Queue Envelope, Execution Attempt, Completion Evidence, or an external effect
is prohibited.

Reads and writes are organization-scoped; lineage is workload-scoped; idempotency is
organization-scoped; and Dispatch, claimant, and policy evidence use scope-aware
lookup. Absent and inaccessible foreign evidence have the same safe failure class,
code, message, and publication behavior and disclose no foreign artifact existence.
Same-scope integrity failures remain explicit. Claimant evidence is not substitutable
across organization or workload scope, and a scope-safe lookup failure publishes no
accepted state.

The implementation explicitly excludes Execution Attempt; execution; worker invocation;
monitoring; completion; retries; Dispatch, Worker Selection, Worker Readiness,
Execution Lease, Authorization Checkpoint, or Worker Identity semantic changes;
authentication-system expansion; Queue Envelope; queue publication or consumption;
provider or model invocation; orchestration; scheduling; public APIs; routes;
controllers; migrations; external effects; durable distributed persistence;
background workers; any end-to-end runtime path; and every later milestone.

Bounded tests may prove only this foundation: lineage identity; unique generation;
single acceptance per generation; monotonic fencing; expiry/release; idempotent and
conflicting retries; stale versions; competing claimant, claim/release, and
claim/expiry races; atomic failure/prior-state preservation;
reconstruction/divergence; isolation;
absent-versus-foreign non-disclosure; and downstream exclusions. Tests must not
require attempts, queues, execution, monitoring, completion, retry, orchestration,
or external integrations.

The merged implementation supplies only this process-local foundation:
frozen public inputs and lineage events; canonical UTF-8 content; deterministic
lineage/event identities and SHA-256 digests; retained Dispatch and claimant evidence
verification; one registered versioned claim policy; owner-derived generation and
acceptance fences; append-only generation, acceptance, retained rejection, expiry,
and release events; scoped idempotency; expected-version CAS; rollback-safe
copy-on-write publication; deterministic reconstruction; and scope-safe in-memory
evidence/history access. It adds no API, migration, durable adapter, queue, attempt,
execution behavior, or external effect.

## Effective Execution Lease Foundation Implementation Authorization

ADR 0013 is the sole architectural basis for this effective authorization and
remains Proposed. Its Architecture Review Gate is **PASS**. PR #32 was squash-merged
at `e39ab7ad9d308a8c44f8a47d54653f46e9c70061`; that architecture merge granted no
implementation authority.

PR #33 was reviewed at `33acfe5c55cafd16805aca2481c211c47108cddf` and
squash-merged into `main` at `543a5d787c9fcd8bda4c1b67e96c69aab3f379c2`.
Governance Review Gate: **PASS**. CI: **PASS**. The merge made the bounded Execution
Lease implementation authorization effective. ADR 0013 itself remains unchanged.

ADRs 0007–0012 remain controlling for their existing semantic owners. PR #33 does
not amend or supersede them, and ADR 0013 adds only the Execution Lease
implementation-authorization boundary. This package transfers, broadens, and narrows
no existing owner. Authorization Checkpoint, Worker Readiness, Worker Selection,
Dispatch Decision, and Work Claim retain their ownership. Execution Attempt remains
future and unauthorized; Retry, Monitoring, and Completion ownership remains
unchanged.

Before merge, branch creation, opening PR #33, CI passing, a Governance Review Gate
PASS, marking the PR Ready for Review, and governance comments did not authorize
implementation. PR #33's merge into `main` satisfied the sole effective condition;
authorization is no longer pending or ineffective. The bounded
`feature/execution-lease-foundation` implementation candidate is intended only for a
Draft PR and is not merged or part of `main`. It must pass a complete Implementation
Review Gate, CI, and merge review before the implementation becomes repository
baseline.

The effective authorization permits only the immutable Execution Lease Foundation
defined by ADR 0013:

- immutable lease domain evidence: lineage identity, lease-generation identity,
  lifecycle records or events, and append-only history;
- canonical UTF-8 serialization with deterministic ordering, canonical digests,
  deterministic namespaced identities, and strict supported schema, component,
  serialization, and configuration versions;
- one authoritative lineage keyed exactly by `organization_id`,
  `workload_context_id`, `plan_id`, `work_item_id`, and `permission_family`;
- owner-assigned monotonic generation: the first valid grant receives the initial
  generation, generation is immutable, and callers and timestamps cannot select it;
- a lineage version that advances exactly once per successful lifecycle append and
  remains distinct from generation, lease identity, and event identity;
- the closed, unique, canonical, versioned permission vocabulary
  `OFFER_WORK_ITEM` and `INITIATE_WORK_ITEM_EXECUTION`, bounded by retained upstream
  authority, with unknown permissions failing closed;
- a narrow retained-evidence port that resolves and verifies exact affirmative
  Authorization Checkpoint identity, digest, organization/workload and
  principal/authority-subject scope, plan/work-item scope, permission ceiling,
  policy identity/version/digest, semantic evaluation-time evidence, immutable
  history boundary, and exact schema/component/serialization/configuration versions;
- immutable grant evidence that narrows upstream scope and permission, assigns the
  owner-controlled generation, retains effective and expiry boundaries, and creates
  no downstream artifact or effect;
- immutable renewal evidence within the same generation using fresh affirmative
  Authorization Checkpoint evidence, the same organization/workload/work lineage,
  no permission broadening, expected-version CAS, and scoped idempotency;
- immutable revocation evidence only when exact retained causality satisfies ADR
  0013; a narrow port may represent already-authorized revocation evidence, but the
  implementation cannot invent a revocation-authority model;
- immutable supersession within one lineage while retaining every earlier generation
  and requiring downstream consumers to use exact generation and history boundaries;
- deterministic applicability using the half-open interval
  `effective_at <= evaluation_at < expires_at`, retained revocation boundaries, no
  replay dependence on current wall-clock time, and non-semantic `recorded_at`;
- owner-scoped idempotency over the exact canonical organization/workload,
  operation, lineage, Authorization Checkpoint evidence, work scope, permissions,
  generation boundary, effective/expiry boundary, revocation/supersession causality,
  policy/version/digest, semantic-time/evidence boundary,
  schema/component/serialization/configuration versions, and caller key;
- expected-version CAS for every lifecycle append, including grant, renewal,
  revocation, supersession, stale-writer, equivalent-retry, and conflicting-reuse
  races, with no timestamp arbitration, last-write-wins, or hidden cross-owner
  transaction;
- rollback-safe owner-scoped atomic publication prepared before commit and limited
  to one immutable lease event, lineage history, lease ID/index, owner-derived
  pointer/index, generation/version state, and scoped idempotency entry, with no
  partial visibility and preservation of prior accepted state on failure;
- deterministic fail-closed reconstruction through an explicit lineage version from
  exact Authorization Checkpoint evidence, lease policy/version/digest, scope,
  permissions, generation assignments, lifecycle and semantic-time evidence,
  versions, canonical inputs, identities, and digests;
- reconstruction checks for contiguous versions, monotonic owner-assigned
  generations, authorization causality, permission narrowing, legal transitions,
  revocation/supersession ordering, deterministic identity/content/digest, and
  derived applicability, without mutation;
- organization-scoped reads, writes, and idempotency; workload-scoped lineages;
  exact authorization-scope matching and permission narrowing; scope-aware evidence
  lookup; absent/foreign evidence non-disclosure; same-scope integrity visibility;
  immutable provenance and audit reconstruction; and no credentials or secrets in
  canonical lease evidence; and
- bounded implementation-local documentation and focused unit/foundation tests for
  this exact slice.

Possession of an Execution Lease performs no action and does not imply generic
execution authority. Permissions remain exact and bounded: `OFFER_WORK_ITEM` permits
only Dispatch evaluation, while `INITIATE_WORK_ITEM_EXECUTION` permits only the
separately owned downstream admission or effect boundary as governed later. Neither
permission by itself authorizes provider invocation, execution, completion, retry,
monitoring, or orchestration. No additional permission semantics are introduced.

An equivalent idempotent retry converges to the exact previously committed canonical
lease event. It appends no duplicate event and changes no lineage version,
generation, pointer/index, or idempotency state beyond the original committed entry.
Conflicting idempotency reuse fails explicitly, publishes nothing, appends no event,
and preserves prior state.

Expected-version CAS permits exactly one successor for one expected lineage version.
A stale writer appends nothing and must reload and recompute from newly committed
authoritative history. Last-write-wins, timestamp arbitration, and hidden cross-owner
transactions remain prohibited.

Expiry and applicability derive only from retained semantic-time evidence. No
background timer or scheduler may create authoritative expiry truth, replay never
consults wall-clock `now`, and `recorded_at` remains diagnostic only. Mutable current
lease pointers, projections, and caches are convenience views only; none may replace
immutable lineage history or an exact generation/history boundary as authority.

Reconstruction and replay use only retained immutable evidence and exact versions
and digests. They must not consult mutable current Authorization Checkpoint or
Execution Lease projections as authority, queues, live workers, providers,
Monitoring, Completion, external systems, current wall-clock time, or ambient mutable
configuration not retained in canonical evidence. Any divergence fails closed
without mutation.

Focused tests may prove canonical lineage identity; generation exclusion from stream
identity; owner-assigned first and monotonic generations; separation of lineage
version, generation, lease identity, and event identity; deterministic lease
identity; permission sorting, uniqueness, and unknown-permission rejection;
authorization scope narrowing and permission ceilings; valid and invalid grants;
valid renewal, fresh-authorization requirements, and illegal authority expansion;
immutable revocation and supersession; half-open effective/expiry behavior including
expiry equality; retained revocation boundaries; equivalent and conflicting
idempotency; stale versions; concurrent grants and renewals; renewal/revocation
races; rollback on empty and prior state; append-only history; immutable returned
evidence; deterministic reconstruction; lineage gaps; illegal generations;
authorization-evidence and digest divergence; organization/workload isolation;
absent-versus-foreign non-disclosure; and absence of downstream behavior. These tests
must not require downstream runtime owners.

This effective authorization explicitly excludes:

- Authorization Checkpoint changes beyond the narrow retained-evidence port;
- authentication or identity-subsystem changes;
- Execution Plan, Worker Readiness, Worker Selection, Dispatch Decision, or Work
  Claim semantic changes;
- Execution Attempt or Execution Effect/Runtime;
- provider or model selection or invocation;
- queue publication or consumption and Queue Envelope;
- execution, Monitoring, Completion, Retry, scheduling, or orchestration;
- public APIs, routes, controllers, migrations, or background workers;
- external effects, durable distributed persistence, end-to-end runtime execution,
  or any later milestone.

The implementation candidate supplies only process-local immutable lease lineage
events; canonical UTF-8 serialization; deterministic lineage, lease, event, and
idempotency identities and digests; owner-assigned generation; distinct lineage
version; bounded permissions; verification-only retained Authorization Checkpoint
evidence; grant, renewal, retained-directive revocation, and active-generation
supersession; retained-time applicability; scoped idempotency; expected-version CAS;
rollback-safe copy-on-write publication; deterministic reconstruction; and
organization/workload isolation. It creates no downstream artifact or effect.

The concrete revocation-directive and authorized-issuer contract, maximum duration
and renewal-window policy, precise post-revocation later-generation policy,
attempt-admission versus effect-initiation revocation race, and concrete
persistence/API/encoding choices remain non-blocking future governance items. A
candidate implementation must not invent their semantics. It may introduce an
abstraction only where ADR 0013 already fixes ownership. Any need for externally
meaningful authority, security, lifecycle, or concurrency semantics not established
by ADR 0013 must stop and return to governance.

This candidate is not yet merged and must pass a complete Implementation Review Gate,
CI, and merge review. ADR 0013 remains Proposed. Material deviation requires amended
or new architecture governance. No later runtime layer is authorized by this
candidate.

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
| Dispatch Decision tests | 51 passed |
| Work Claim tests | 34 passed |
| Runtime tests | 181 passed |
| Full test suite | 342 passed |
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
| Dispatch | Foundation complete |
| Scheduling | Deferred |
| Claims & Leases | Work Claim foundation complete; lease changes deferred |
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
- Work Claim behavior beyond the authorized immutable foundation
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
- Runtime milestones downstream of the authorized v0.10B foundation remain
  unauthorized.
- The completed v0.10A foundation records Dispatch approval or denial only. It
  provides no Work Claim, queue transport, execution path, external effect, or
  end-to-end prototype.
- The merged v0.10B implementation is limited to the authorized immutable Work Claim
  foundation. It
  grants no Execution Attempt, execution, monitoring, completion, retry, scheduling,
  orchestration, provider, API, migration, durable-persistence, or external-effect
  authority.

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
- The separately authorized v0.10A immutable Dispatch Decision foundation passed its
  Implementation Review Gate and CI and was squash-merged through PR #26.
- ADR 0012 is merged, remains Proposed, and its Architecture Review Gate passed.
- The v0.10B implementation authorization package passed its Governance Review Gate
  and CI and was squash-merged through PR #28 at
  `6d8e22a1e226198b7df8e3ac846ef2672ede29de`; authorization is now effective.
- The Work Claim Foundation passed its Implementation Review Gate with non-blocking
  documentation notes and CI, then was squash-merged through PR #30 at
  `df6cc09edbd2adae871b75aabab407debdcd8f4b`; v0.10B is implemented on `main`.
- Authorization is limited to the exact immutable Work Claim foundation slice above.
  PR #30 exercised that authorization without broadening it.
- ADR 0013 was squash-merged through PR #32 at
  `e39ab7ad9d308a8c44f8a47d54653f46e9c70061`, remains Proposed, and its
  Architecture Review Gate passed with no blocking findings.
- The Execution Lease implementation-authorization package was reviewed at
  `33acfe5c55cafd16805aca2481c211c47108cddf`, passed its Governance Review Gate and
  CI, and was squash-merged through PR #33 at
  `543a5d787c9fcd8bda4c1b67e96c69aab3f379c2`; its bounded authorization is now
  effective. The `feature/execution-lease-foundation` implementation candidate is
  intended only for a Draft PR, is not merged, and must pass a complete Implementation
  Review Gate, CI, and merge review.
- Material deviation requires an amended or new ADR, another Architecture Review
  Gate where applicable, and separate implementation authorization.
- Execution Attempt and every later runtime layer remain unauthorized.
- PR #28's merge into `main`, rather than its earlier pre-merge CI, review, Ready, or
  comment state, made the authorization effective.

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
