# ADR 0010: Runtime State Machine and Transition Ownership

Status: Proposed

## Context

Runtime Architecture Baseline v1 is effective, ADR 0008 is accepted, and the
Worker Selection Foundation is implemented. ADR 0009 remains Proposed, while its
separately authorized v0.9A slice has delivered only the immutable Execution
Request foundation. Deterministic planning and every downstream runtime effect
remain unauthorized.

The governing runtime documents define semantic owners and downstream dependency
rules, but future proposals still need one consolidated account of how independent
runtime artifacts contribute evidence to a lifecycle without becoming one mutable
workflow record. A forced total order would be incorrect: the baseline establishes
causal dependencies, not a global transaction or timestamp order.

This ADR documents the effective ownership and transition rules already established
by Runtime Architecture Baseline v1 and accepted ADRs. It does not amend,
supersede, or reinterpret them. Where a component remains future or a contract
remains Proposed, this ADR records that status rather than making the component
effective.

This ADR is architecture documentation only. It authorizes no implementation.

## Decision

Represent the runtime lifecycle as a dependency graph of independent,
organization-scoped artifacts. Each artifact has one semantic owner, retains its own
immutable evidence, and may be referenced downstream. No downstream artifact may
mutate an upstream artifact or transfer ownership through shared identifiers,
storage, or transactions.

Lifecycle state is reconstructed from authoritative artifacts and append-only
evidence at explicit version boundaries. A mutable status field, current pointer,
index, projection, cache, or combined view is not authoritative lifecycle truth
unless a future accepted ADR assigns it that ownership.

## Governing dependency graph

The effective dependency direction is:

```text
Execution Request
  -> Request Validation
  -> Execution Plan
  -> Authorization Checkpoint
  -> Execution Lease
  -> Queue Envelope
  -> Worker Identity
  -> Worker Attestation
  -> Worker Runtime Health
  -> Worker Readiness Evidence
  -> Worker Selection Result
  -> Dispatch Decision
  -> Work Claim
  -> Execution Attempt
  -> Execution Monitoring
  -> Completion Evidence
```

Execution Lease, Queue Envelope, Worker Identity, Worker Attestation, Worker
Runtime Health, Worker Readiness, Dispatch Decision, Work Claim, Execution Attempt,
Execution Monitoring, and Completion remain future architectural components except
where a separate accepted ADR and explicit implementation authorization state
otherwise.

The graph is a semantic partial order:

- explicit artifact references establish cross-stream causality;
- stream version orders records only within one owning stream;
- timestamps are evidence and never establish causal or concurrency order;
- no global total order is assumed;
- Retry Policy may consume failed-attempt and completion evidence and may propose a
  new attempt, but it does not mutate the prior attempt or completion evidence; and
- projections may join artifacts for queries but cannot create a dependency absent
  from authoritative history.

Worker Selection consumes authoritative Worker Readiness Evidence. Worker Selection
never produces, changes, or substitutes for readiness. Execution Planning never
depends on Worker Selection or any later runtime state.

## Semantic and transition ownership

### Execution Request

Owns:

- the immutable accepted requested-work semantics;
- organization and workload context;
- immutable payload content or reference;
- request-level constraints, provenance, schema identity, canonical digest; and
- stable idempotency identity associated with the accepted request.

Consumes:

- canonical intake provenance and submitted immutable request content under Request
  Intake ownership.

Produces:

- one immutable accepted request artifact suitable for downstream validation and
  planning.

Owns the `request accepted` transition at the request boundary. Request Validation
then consumes the accepted request and owns its separate validation findings.
Acceptance records immutable request evidence; it does not authorize, plan, select,
dispatch, claim, lease, or execute.

Explicitly does not own:

- validation findings, authorization, planning, worker state, selection, execution,
  retry, monitoring, or completion.

### Execution Plan

Owns:

- deterministic interpretation of one valid Execution Request;
- planned work structure, requirements, dependencies, and plan-level constraints;
- exact planning-rule, policy, configuration, and schema versions; and
- derivation evidence, canonical identity, and digest.

Consumes:

- a valid immutable Execution Request, retained validation findings, immutable
  referenced inputs, and exact versioned planning rules and policies.

Produces:

- one immutable, reconstructable Execution Plan.

Owns the `plan derived` transition. The transition is valid only when retained
inputs reproduce the same canonical plan.

Explicitly does not own:

- authorization, readiness, selected-worker identity, dispatch eligibility, claims,
  leases, attempts, retries, monitoring, progress, or completion.

ADR 0009 remains Proposed. This ownership description is conceptual and does not
authorize deterministic planning.

### Authorization Checkpoint

Owns:

- whether an authenticated principal may request a specific planned action under a
  referenced policy and evaluation boundary.

Consumes:

- principal, request, plan, and exact versioned authorization-policy evidence.

Produces:

- immutable authorization approval or denial evidence.

Owns the `authorization evaluated` transition. Approval is bounded evidence; denial
fails closed. Neither outcome dispatches or executes work.

Explicitly does not own:

- identity issuance, readiness, selection, lease execution, claims, attempts, or
  completion.

### Execution Lease

Owns:

- bounded execution permission, scope, expiry, and revocation reference.

Consumes:

- a valid Authorization Checkpoint decision and explicit lease policy.

Produces:

- immutable lease-grant, rejection, expiry, or revocation evidence.

Owns the `lease granted` transition. Granting a lease creates bounded authority but
does not select a worker, claim work, prove readiness, or execute.

Explicitly does not own:

- authorization policy, worker ranking, queue delivery, claims, execution results,
  retries, or completion.

### Queue Envelope

Owns:

- transport representation, immutable upstream references, and delivery metadata.

Consumes:

- immutable upstream references and an explicit transport contract.

Produces:

- transport evidence without becoming the source of workload, authorization,
  selection, claim, or execution truth.

Owns only transport-envelope recording transitions defined by a future ADR.

Explicitly does not own:

- domain reconstruction, authorization truth, readiness, selection, claims,
  execution, retry, or completion.

### Worker Readiness

Owns:

- contextual eligibility at a retained evaluation boundary;
- reasoned readiness outcome; and
- references to identity, attestation, health, capability, and policy evidence.

Consumes:

- authoritative Worker Identity, Worker Attestation, Worker Runtime Health,
  capability, policy, workload, and evaluation-boundary evidence.

Produces:

- immutable point-in-time Worker Readiness Evidence.

Owns the `readiness evaluated` transition. A later observation requires a new
evaluation; it never rewrites earlier readiness evidence.

Explicitly does not own:

- underlying identity, trust, or health facts; candidate ordering; dispatch; claims;
  leases; attempts; retries; or completion.

### Worker Selection

Owns:

- deterministic eligible-candidate ordering, scores, ranks, explanations, reason
  codes, outcomes, and immutable selection history.

Consumes:

- an immutable Execution Plan reference, workload and capability requirements,
  policy constraints, authoritative Worker Readiness Evidence, organization context,
  and explicitly versioned preferences.

Produces:

- an immutable Worker Selection Result and rebuildable current-selection pointer.

Owns the `worker selected` transition as candidate-ordering evidence. It does not
offer work or reserve a worker.

Explicitly does not own:

- readiness, identity, trust, health, authorization, scheduling, dispatch, queues,
  leases, claims, attempts, retries, monitoring, or completion.

### Dispatch Decision

Owns:

- whether work is offered to a selected candidate under retained authority and
  dispatch-policy evidence.

Consumes:

- a Worker Selection Result, applicable authority reference, and versioned dispatch
  policy.

Produces:

- immutable dispatch approval or denial evidence.

Owns the `dispatch approved or denied` transition. It may validate referenced
selection and readiness applicability but must not recompute either.

Explicitly does not own:

- ranking, readiness, claims, leases, execution, retry, or completion.

### Work Claim

Owns:

- claimant, fence, version, expiry, release, and exclusive bounded acceptance.

Consumes:

- an applicable Dispatch Decision, claim policy, authenticated claimant evidence,
  and the owning stream's expected version.

Produces:

- immutable claim-accepted, rejected, expired, or released evidence.

Owns the `claim accepted` transition. Claim acceptance does not create
authorization, prove readiness or trust, or establish execution results.

Explicitly does not own:

- authorization, selection logic, dispatch policy, lease authority, attempt effects,
  retry policy, or completion.

### Execution Attempt

Owns:

- one attempt identity, attempt-local lifecycle, effects, and result evidence.

Consumes:

- a valid current Work Claim, bounded applicable authority, immutable workload
  reference, and explicit provider boundary.

Produces:

- immutable attempt-started, attempt-local lifecycle, effect, and attempt-result
  evidence.

Owns the `attempt started` and `attempt completed` transitions for one attempt.

Explicitly does not own:

- readiness, selection, claim policy, authorization policy, retry eligibility,
  monitoring adjudication, or completion truth.

### Completion

Owns:

- terminal adjudication and its reason under explicit completion policy.

Consumes:

- immutable Execution Attempt evidence and exact completion-policy inputs.

Produces:

- immutable Completion Evidence.

Owns the `completion recorded` transition. Completion is idempotent for equivalent
canonical evidence and fails closed on conflicting reports.

Explicitly does not own:

- output generation, provider invocation, selection, dispatch, claims, lease
  authority, retry policy, or worker lifecycle.

## Transition validity

Every authoritative transition requires:

- all required upstream artifacts at an explicit history boundary;
- matching organization and workload context;
- valid canonical identities and digests;
- supported schema, policy, serialization, and component versions;
- legal dependency direction and transition type;
- an authenticated actor and authority where the owning transition requires them;
- immutable evidence references;
- scoped idempotency identity;
- the owning stream's expected version; and
- an atomic append of the transition and any pointer owned by that same stream.

Missing, invalid, stale, expired, cross-organization, unsupported, conflicting, or
unverifiable evidence fails closed and appends no successful transition.

## Authoritative artifacts, evidence, and derived state

### Authoritative artifacts

An accepted artifact is authoritative only for the semantics assigned to its owner.
The request, plan, authorization decision, lease, queue envelope, readiness result,
selection result, dispatch decision, claim, attempt, and completion evidence remain
independent artifacts even when they share identifiers or storage.

### Append-only evidence

Transition records retain stable stream identity and version, organization and
workload context, schema and producer versions, causation and correlation,
idempotency identity, evidence references, canonical payload hash, and recorded and
effective timestamps.

Correction, revocation, cancellation, supersession, compensation, expiry, and retry
create new immutable evidence. They never edit an accepted record.

### Derived lifecycle state

Lifecycle labels, combined timelines, current pointers, indexes, projections,
summaries, dashboards, and cached operational views are derived. They must be
rebuildable from authoritative history and cannot supply missing authority or facts.

No general authoritative `runtime status` or single mutable state-machine record is
established by this ADR.

## Reconstruction

Reconstruction consumes:

- immutable history through explicit per-stream version boundaries;
- every immutable referenced artifact;
- exact schemas, policies, deterministic component versions, and canonical
  configuration; and
- explicit cross-stream causal references.

Reconstruction validates:

- artifact and stream identities;
- canonical payload digests;
- monotonically increasing in-stream versions;
- causal reference integrity;
- supported version compatibility;
- dependency direction; and
- transition legality under the owning component's rules.

Reconstruction rejects broken chains, missing required artifacts, conflicting
evidence, invalid hashes, unsupported versions, version gaps, cross-organization
references, illegal transitions, and replay divergence.

Replay uses no live providers, queues, health, projections, current time, ambient
configuration, or unseeded randomness. It performs no external effect, repairs no
history, and fails without mutation.

## Atomic persistence boundaries

Atomicity belongs to one semantic owner's aggregate stream unless a future accepted
ADR explicitly defines a larger boundary.

Within one stream, a successful transition atomically appends all evidence owned by
that transition and advances any current pointer owned by the same aggregate.
Success is not exposed before commit. A pointer must never reference uncommitted
history.

Cross-stream atomicity is not assumed. Cross-stream causality uses committed
immutable references. Transaction co-location, shared tables, shared identifiers,
or one database transaction does not combine semantic ownership or transfer
authority.

Future external effects require persisted intent or an equivalent explicitly
reviewed atomic boundary before the effect occurs. This ADR selects no persistence
technology.

## Idempotency

Each transition defines an idempotency scope containing organization, operation,
workload or aggregate identity, canonical transition input, and applicable versions.

- An equivalent retry returns the existing canonical result and appends no duplicate
  successful evidence.
- Reuse of an idempotency identity with different canonical content fails explicitly
  as an idempotency conflict.
- Idempotency in one owning stream cannot deduplicate or authorize a transition in
  another stream.
- Idempotency never converts invalid or stale evidence into success.

## Concurrency

Authoritative appends use expected-version compare-and-swap.

- At most one writer for the same expected stream version succeeds.
- A stale writer appends nothing, reloads committed history, and recomputes.
- Timestamps, persistence-return order, process scheduling, and last-write-wins do
  not arbitrate races.
- Compatible equivalent writes converge through scoped idempotency.
- Incompatible immutable evidence is rejected rather than merged.

Specific races are resolved by their semantic owner:

- competing selections append only under the Worker Selection stream's version and
  idempotency rules;
- competing claims are serialized by the Work Claim fence and expected version;
- lease races are resolved by the Execution Lease stream without expanding the
  Authorization Checkpoint decision;
- duplicate equivalent completion reports return the existing canonical Completion
  Evidence; and
- conflicting completion reports fail closed and preserve the accepted evidence.

## Retry boundary

Retry Policy owns whether another attempt may be proposed and whether retry budget
remains. A retry, if authorized by a future accepted design, creates a new attempt
identity and new causal evidence referencing retained failure and completion
evidence.

Retry never mutates, reopens, or replaces an existing Execution Attempt or
Completion Evidence. Neither an attempt failure nor completion automatically
authorizes retry.

This ADR does not define or authorize retry implementation.

## Failure model

Stable non-success outcomes must distinguish at least:

- missing upstream artifact;
- invalid canonical identity or digest;
- unsupported schema, policy, serialization, or component version;
- expired, revoked, or inapplicable authority;
- organization or workload-context mismatch;
- illegal dependency or transition;
- idempotency conflict;
- stale writer or version conflict;
- conflicting immutable evidence;
- invalid reconstruction or replay divergence;
- persistence failure; and
- internal failure.

Failures are fail-closed, expose no partial success, redact sensitive evidence, and
must not disclose another organization's artifact existence.

## Security and authority

Authentication, authorization, identity, attestation, health, readiness, selection,
leases, claims, attempts, and completion remain separate responsibilities.

Every protected artifact and idempotency scope carries organization identity.
Downstream validation may verify integrity, version, scope, freshness, and
applicability; it may not create, extend, reinterpret, or transfer authority.

A lease or claim does not prove identity, trust, readiness, selection correctness,
or completion. Selection does not authorize or reserve. Completion does not rewrite
authorization, selection, dispatch, claim, lease, or attempt history.

## Explicit non-goals

This ADR does not define or authorize:

- Execution Plan implementation or deterministic planning;
- Worker Identity, Attestation, Runtime Health, or Readiness implementation;
- Worker Selection implementation or changes;
- Authorization Checkpoint, Execution Lease, or Queue Envelope implementation;
- dispatch, scheduling, claims, attempts, execution, completion, or retries;
- queues, providers, monitoring, orchestration, or external side effects;
- APIs, persistence technology, database schemas, migrations, or background workers;
- a global transaction, total event order, or mutable authoritative runtime status;
- real-money wagering, sportsbook execution, or any relaxation of ADR 0005;
- v0.9B or any other implementation milestone; or
- implementation planning beyond the architectural definitions in this ADR.

## Consequences

Positive:

- future proposals can identify exactly which owner may record each transition;
- lifecycle views can be reconstructed without a mutable cross-component record;
- readiness-to-selection direction and other governing dependencies remain explicit;
- races and retries preserve immutable evidence; and
- storage choices cannot silently collapse semantic boundaries.

Costs:

- cross-stream lifecycle queries require causal joins and rebuildable projections;
- historical schemas, policies, component versions, and evidence must remain
  available for replay;
- future components still require their own detailed contracts, gates, and separate
  implementation authorization; and
- unresolved cross-stream coordination cannot be hidden inside a shared
  transaction.

## Unresolved architectural gaps

This ADR intentionally leaves these decisions to future proposals:

1. exact transition schemas, APIs, and persistence adapters;
2. durable distributed history and cross-stream consistency mechanisms;
3. the detailed Authorization Checkpoint, lease, queue, readiness, dispatch, claim,
   attempt, monitoring, completion, and retry contracts;
4. persisted-intent or outbox boundaries for external effects;
5. cancellation, supersession, compensation, and expiry policies by owner;
6. how a new readiness evaluation triggers a new selection without mutating either
   artifact;
7. how completion and retry policy interact when evidence is incomplete or
   contradictory; and
8. projection lag, rebuild, and operational observability requirements.

None of these gaps may be filled through implementation convenience.

## Architecture review questions

1. **Ownership:** Does every artifact and transition have exactly one semantic
   owner without transferring ownership through storage or references?
2. **Dependency direction:** Does the graph preserve the baseline, including
   Worker Readiness Evidence before Worker Selection Result?
3. **Transition legality:** Are prerequisites and illegal-transition failures
   explicit without inventing a global state owner?
4. **Evidence:** Is every transition supported by immutable, organization-scoped,
   versioned evidence?
5. **State classification:** Are authoritative artifacts, append-only evidence,
   projections, indexes, caches, and pointers clearly distinguished?
6. **Reconstruction:** Can lifecycle state be rebuilt deterministically and fail
   closed on broken or unsupported history?
7. **Concurrency:** Do CAS, stale-writer, competing-selection, claim, lease, and
   completion rules preserve accepted evidence?
8. **Idempotency:** Are equivalent retry and conflicting-key outcomes explicit and
   scoped to the owning transition?
9. **Atomicity:** Are single-stream atomic boundaries clear without implying
   cross-stream transactions or merged ownership?
10. **ADR 0009 overlap:** Does this ADR preserve ADR 0009's Proposed status and avoid
    authorizing deterministic planning?
11. **Accepted-architecture consistency:** Does this ADR consolidate rather than
    amend ADR 0007, ADR 0008, or Runtime Architecture Baseline v1?
12. **Implementation boundary:** Are every runtime implementation and v0.9B still
    explicitly unauthorized?

## Implementation gate

- ADR Status: **Proposed**.
- Architecture Review Gate: **Required**.
- A binary Architecture Review Gate `PASS` is required before implementation
  authorization may be considered.
- Separate explicit Implementation Authorization is required after a `PASS`.
- ADR 0010 authorizes no implementation.
- A `FAIL` or unresolved ownership, dependency, or authority conflict blocks
  implementation and requires ADR revision and another review.

No runtime work may begin by implication from this ADR, its publication, or its
review.
