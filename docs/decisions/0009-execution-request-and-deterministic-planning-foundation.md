# ADR 0009: Execution Request and Deterministic Planning Foundation

Status: Proposed

## Context

Runtime Architecture Baseline v1 is effective, and Worker Selection Foundation is
implemented. Worker Selection already accepts an immutable `ExecutionPlan` reference
and workload requirements, but EDGEIQ does not yet define an authoritative Execution
Request or a deterministic owner for producing that plan.

Planning is upstream of Worker Selection. It supplies stable workload meaning and
requirements that later readiness and selection decisions may consume. It does not
fill the separate downstream gap between a selected eligible worker and any future
dispatch, claim, lease, execution, monitoring, or completion behavior. Those remain
distinct, deferred responsibilities.

Without an explicit boundary, future code could confuse request admission with
authorization, derive plans from live worker state, mutate plans to record progress,
or allow planning to perform execution effects. This ADR proposes a narrow,
non-executing, side-effect-free request and planning boundary under
[Runtime Architecture Baseline v1](../runtime/RUNTIME_ARCHITECTURE_BASELINE_V1.md).

This ADR is architecture documentation only. It does not authorize implementation.

## Decision

Define two conceptual artifacts with distinct semantic owners.

### Execution Request

An `ExecutionRequest` is the canonical accepted description of desired work and the
immutable inputs required for validation and planning.

It describes:

- requested work identity and type;
- immutable payload content or an immutable payload reference;
- request-level constraints;
- organization and workload context;
- request provenance;
- schema and contract versions; and
- scoped idempotency identity and canonical digest.

An Execution Request does not:

- select or rank a worker;
- decide dispatch eligibility;
- claim responsibility;
- create or validate a lease;
- begin or monitor execution;
- invoke a provider or model;
- publish to or consume a queue;
- create retry or completion state; or
- perform any external side effect.

Request Intake continues to own receipt, transport identity, idempotency capture, and
canonical provenance. Request Validation continues to own structural and semantic
validation findings. The accepted Execution Request owns the immutable requested-work
semantics; it owns neither caller authorization nor execution authority.

### Deterministic Execution Plan

An `ExecutionPlan` is an immutable, deterministic, reconstructable interpretation of
one valid Execution Request under explicitly versioned planning rules and accepted
policy inputs.

It describes:

- ordered or explicitly structured planned work;
- required capabilities and resources;
- declared work-unit dependencies;
- immutable input and policy references;
- request and plan schema versions;
- planning-rule identity and version; and
- derivation evidence sufficient for reconstruction.

Planning records intended execution structure without performing execution. A plan
does not authorize its own execution, reserve capacity, establish readiness, select a
worker, dispatch work, create a claim or lease, invoke a provider or model, or decide
completion.

Runtime Architecture Baseline v1 places Planning before Worker Selection and forbids
Planning from depending on selection. Therefore, the canonical Execution Plan MUST
NOT consume a Worker Selection result or contain a selected-worker reference. A
future downstream composite view MAY reference both an immutable plan and an
immutable selection, but that view is not an Execution Plan, is non-authoritative for
planning, and cannot mutate either artifact.

This resolves the phrase “worker-selection output where applicable” as not applicable
to the canonical plan under the current governing baseline. Changing that dependency
would require an explicit amendment to the governing architecture, not an
implementation convenience.

## Semantic ownership

### Execution Request owns only

- requested work identity;
- immutable planning inputs;
- request-level constraints;
- request provenance;
- organization and workload context;
- request schema identity and version; and
- canonical request content and digest.

### Execution Plan owns only

- deterministic interpretation of one valid request;
- ordered or explicitly structured planned work;
- required capabilities, resources, and work-unit dependencies;
- immutable references used by planning;
- plan schema and planning-rule versions;
- derivation evidence; and
- deterministic reconstruction inputs and plan digest.

### Ownership explicitly preserved

- Request Intake owns receipt, transport identity, idempotency capture, and canonical
  provenance.
- Request Validation owns validation findings.
- Authorization Checkpoint owns workload authorization decisions.
- Worker Identity owns stable worker identity and organization association.
- Worker Readiness owns contextual eligibility and supporting evidence.
- Worker Selection owns candidate ordering, scores, outcomes, and selection history.
- Dispatch Decision owns whether work is offered to a selected candidate.
- Work Claim owns claimant, fence, version, expiry, and release.
- Execution Lease owns bounded permission, scope, expiry, and revocation reference.
- Work Execution owns attempt identity, attempt-local lifecycle, effects, and result
  evidence.
- Execution Monitoring owns progress and liveness observations.
- Completion owns terminal adjudication and reason.
- Retry Policy owns whether another attempt may be proposed within a retry budget.

Neither the request nor planning layer may create, extend, reinterpret, or mutate
authority owned by any of these layers.

## Dependency direction

The permitted direction is:

```text
Request Intake
  -> Execution Request
  -> Request Validation
  -> Deterministic Execution Plan
  -> Authorization Checkpoint
  -> Worker evidence and readiness
  -> Worker Selection
  -> future downstream runtime layers
```

Planning may consume only:

- one canonical, valid Execution Request;
- immutable payload content or a verified immutable payload reference;
- retained validation findings;
- stable upstream facts;
- accepted, versioned planning policy;
- explicit canonical configuration; and
- exact schema and planning-rule versions.

Planning must not depend on:

- worker availability, identity observations, health, or readiness;
- Worker Selection output;
- queue state or delivery order;
- dispatch decisions;
- active or historical claims and leases;
- attempts, output, monitoring, or completion;
- retries or orchestration state; or
- other downstream current or future state.

Downstream layers may reference immutable request and plan identities. They must
append their own evidence and must not mutate a request or plan to represent runtime
progress.

## Determinism

Equivalent canonical inputs under the same schema, policy, configuration, and
planning-rule versions must produce the same plan identity, content, ordering, and
digest.

Canonical planning inputs include:

- organization and workload context;
- every semantic Execution Request field;
- normalized request constraints;
- immutable payload content or verified payload digest;
- retained validation evidence;
- accepted policy content and version or digest;
- planning configuration and digest;
- explicit step and dependency ordering rules;
- request and plan schema versions; and
- planning-rule identity and version.

Canonical serialization must define UTF-8 encoding, stable field names, sorted map
keys, explicit null behavior, normalized identifiers and timestamps, defined array
ordering, finite numeric representations, and rejection of unsupported values.

The planner must not depend on:

- wall-clock time unless it is an explicit immutable semantic input;
- random values unless an explicit retained seed is part of the planning contract;
- process-local, filesystem, set, or persistence-return order;
- unordered map iteration;
- live network or provider calls;
- ambient mutable configuration;
- process, host, path, memory, or deployment identity; or
- current worker or runtime state.

A derivation timestamp is evidence only. It cannot change request identity, plan
identity, ordering, or digest.

## Immutable evidence

Accepted planning evidence must retain at least:

```text
request_id
request_schema_version
canonical_request_digest
organization_id
workload_context_id
validation_evidence_references
planning_rule_version
planning_configuration_digest
policy_version_or_digest
canonical_input_digest
plan_id
plan_schema_version
canonical_plan_digest
derivation_evidence_reference
history_boundary
correlation_id
causation_id
derivation_timestamp
reconstruction_metadata
```

Worker Selection identity or digest is deliberately absent because selection is
downstream of planning. A future downstream artifact may retain both plan and
selection references without becoming planning evidence.

Request, validation, plan, and derivation records are immutable and append-only.
Corrections, cancellation, or supersession create new records and references; they
never rewrite accepted evidence. Stream version, not timestamp, orders records.

## Authoritative and derived state

The accepted Execution Request, accepted validation evidence, versioned planning
inputs, and canonical Execution Plan record are authoritative artifacts for their
respective semantics.

The canonical plan is retained as immutable decision evidence and must also be
reconstructable from its retained inputs. Retention and reconstruction are
cross-checks, not competing sources of truth: the retained digest must match the
reconstructed digest.

The following are derived and non-authoritative:

- current-plan pointers;
- request or plan indexes;
- list and search projections;
- summaries and display models;
- dependency visualizations;
- combined plan-and-selection views; and
- runtime progress views.

Derived state must be rebuildable from immutable history and cannot supply facts
missing from authoritative artifacts.

## Reconstruction

Reconstruction uses exactly:

- the canonical request;
- the declared history boundary;
- retained validation findings;
- every referenced immutable input;
- exact schema, policy, configuration, and planning-rule versions; and
- the canonical serialization version.

Given the same canonical inputs and versions, reconstruction must reproduce the same
plan identity, ordered or structured steps, references, and digest. It must perform
no external effect and no live lookup.

Reconstruction fails explicitly and closed when:

- the planning rule or required policy version is unavailable;
- a schema or serialization version is unsupported;
- a request, policy, payload, configuration, or plan digest does not match;
- referenced evidence is missing or belongs to another organization or context;
- the retained history has a version gap or invalid causal reference; or
- reconstructed output diverges from the retained plan.

Failure records diagnostics without changing request, plan, or history.

## Atomicity

The atomic ownership boundary is one organization-scoped request-planning stream.
Successful planning admission atomically records:

- the accepted canonical Execution Request;
- its successful validation evidence;
- the canonical Execution Plan;
- plan derivation evidence and digests; and
- the committed current-plan pointer, if such a pointer is maintained.

The operation is not successful and exposes no committed plan when any required
artifact cannot be recorded. The design prohibits:

- an accepted request without its required accepted evidence;
- a plan without a valid request and validation reference;
- a digest without the canonical content it verifies;
- a current pointer referencing uncommitted history; and
- a success response before the authoritative append commits.

Validation rejection may be retained as an immutable failed admission with no plan,
but it cannot be represented as an accepted request or successful plan.

This boundary does not include authorization, selection, dispatch, queue, claim,
lease, execution, retry, monitoring, or completion transactions. Future external
effects require their own persisted intent and atomicity decisions.

## Idempotency and concurrency

Request admission and plan creation use organization-scoped idempotency and explicit
expected-version compare-and-swap.

- An idempotency key is scoped by organization, workload context, operation, and
  canonical request identity.
- Repeating the same key with identical canonical content returns the previously
  accepted result without appending duplicate history.
- Reusing a key with different canonical content returns an idempotency conflict and
  appends no successful plan.
- A canonical request identity is unique within its organization and workload
  context.
- A canonical plan identity is unique for one canonical input digest and exact
  planning-rule version.
- Concurrent equivalent planners must converge on one canonical plan.
- Only one equal-version writer may commit; stale writers append nothing and must
  reload committed history.
- Timestamps never arbitrate races.
- Repeated reconstruction is effect-free and produces no authoritative append unless
  a separately defined diagnostic record is requested.
- A changed request, policy, configuration, schema, or planning-rule version is a new
  canonical planning input and cannot silently replace an accepted plan.

Stable outcomes include created, existing equivalent result, idempotency conflict,
version conflict, unsupported version, invalid evidence, reconstruction failure,
reconstruction divergence, persistence failure, and internal failure.

## Overlap-stop rule

Planning must stop and return an explicit non-success outcome when the requested
behavior would require another semantic owner. It must not invent defaults or absorb
the responsibility.

Planning stops rather than:

- deciding whether a worker is ready;
- selecting, ranking, or changing a selected worker;
- deciding dispatch eligibility;
- publishing or consuming queue data;
- claiming work or releasing a claim;
- creating, extending, validating, or revoking a lease;
- beginning, monitoring, or completing an attempt;
- choosing or performing a retry;
- orchestrating runtime progress;
- invoking a provider or model; or
- creating completion state.

If planning requirements cannot be expressed without one of those decisions, the
architecture must return to ADR review before implementation proceeds.

## Layer evolution

Future layers may consume stable request and plan identities and append their own
immutable facts, decisions, intents, and observed evidence.

Worker Readiness may evaluate retained capability requirements without changing
them. Worker Selection may order ready candidates for the immutable plan context.
Future authorization, dispatch, claim, lease, execution, monitoring, retry, and
completion components must retain causal plan references and own their separate
history.

Runtime progress, later evidence, cancellation, failure, or completion never mutates
the plan. A materially changed interpretation is a new plan derived from explicit new
inputs or versions. Future layers cannot retroactively make an earlier plan mean
something different.

## Explicit non-goals

This ADR does not define or authorize:

- queue publication or consumption;
- execution attempts;
- Execution Coordination;
- scheduling, dispatch, or dispatch authorization;
- claim creation, release, or ownership;
- lease creation, validation, renewal, or revocation;
- orchestration;
- monitoring;
- retries or recovery policy;
- provider invocation;
- model invocation;
- completion semantics;
- external side effects;
- Worker Identity, Health, or Readiness implementation;
- Worker Selection changes;
- persistence technology or schema;
- API implementation;
- runtime services, migrations, adapters, or tests; or
- implementation authorization.

## Proposed conceptual contracts

These fields define architecture vocabulary, not code, API schemas, database tables,
or a commitment to a programming language.

### ExecutionRequest

```text
request_id
request_schema_version
organization_id
workload_context_id
requested_work_type
immutable_payload_or_reference
request_constraints
provenance
idempotency_identity
canonical_digest
```

### ExecutionPlan

```text
plan_id
plan_schema_version
request_id
planning_rule_version
ordered_or_structured_plan_steps
immutable_references
required_capabilities
resource_requirements
work_unit_dependencies
policy_version_or_digest
canonical_input_digest
canonical_digest
derivation_evidence_reference
```

`selected_worker_reference` is prohibited in the canonical Execution Plan under
Runtime Architecture Baseline v1. Where a future consumer needs a selected-worker
reference, it must use a separate downstream artifact that references both
`plan_id` and the immutable Worker Selection identity.

### PlanDerivationResult

```text
outcome:
  Created
  ExistingEquivalentResult
  IdempotencyConflict
  VersionConflict
  UnsupportedVersion
  InvalidEvidence
  ReconstructionFailure
  ReconstructionDivergence
  PersistenceFailure
  InternalFailure

request_id
plan_id_or_null
canonical_request_digest
canonical_plan_digest_or_null
reason_codes
evidence_references
```

Failure outcomes contain safe reason codes and must not expose another
organization's artifact existence or sensitive request content.

## Invariants

1. The same canonical inputs and planning-rule version produce the same plan identity,
   content, ordering, and digest.
2. Planning performs no external side effects.
3. Planning never selects workers or creates dispatch decisions, queue state, claims,
   leases, attempts, retries, monitoring, or completion state.
4. A plan cannot exist without a valid request and accepted validation reference.
5. An accepted request or plan cannot silently change.
6. Replayed admission with the same scoped idempotency key and payload returns the
   same accepted result.
7. Reuse of an idempotency key with different canonical content fails.
8. Concurrent equivalent planners converge on one canonical plan.
9. A stale writer appends no accepted plan.
10. Repeated reconstruction reproduces the retained plan and performs no effect.
11. Runtime progress never mutates the request or plan.
12. Missing, invalid, cross-organization, or unsupported reconstruction evidence
    fails closed.
13. Derived projections are disposable and cannot become planning authority.
14. Worker Selection, Readiness, Dispatch, Claims, Leases, Execution, Monitoring,
    Retry, Completion, and Authorization ownership remain unchanged.

## Consequences

Positive:

- Worker Selection can consume a real immutable plan reference rather than an
  undefined conceptual placeholder.
- Requested-work meaning becomes stable before authorization and worker decisions.
- Planning decisions become reproducible, auditable, and safe to reference.
- Downstream runtime progress cannot rewrite planning history.

Costs:

- historical planning rules, schemas, policies, and configuration must remain
  available for reconstruction;
- request admission and planning require an explicit atomic stream boundary;
- changed interpretations require new immutable plans; and
- downstream layers still require their own ADRs, gates, and authorization.

## Architecture review questions

1. **Semantic ownership:** Are Request Intake, Validation, Execution Request, and
   Execution Plan ownership distinct and complete?
2. **Dependency direction:** Does planning consume only upstream retained artifacts
   and remain independent of Worker Selection and all downstream state?
3. **Deterministic inputs:** Are every semantic input, ordering rule, schema, policy,
   configuration, and planning-rule version identified?
4. **Evidence sufficiency:** Can retained evidence prove exactly how the plan was
   derived without a live lookup?
5. **Authoritative versus derived state:** Is the canonical plan the only retained
   planning decision while indexes, summaries, pointers, and combined views remain
   rebuildable?
6. **Reconstruction:** Are unsupported versions, missing evidence, digest mismatch,
   and divergence explicit fail-closed outcomes?
7. **Atomicity:** Can request acceptance, validation evidence, plan content, digests,
   and any current pointer commit without partial success?
8. **Idempotency:** Are key scope, equivalent retries, and content conflicts
   unambiguous?
9. **Concurrency:** Do equivalent planners converge, and do stale writers append
   nothing?
10. **Boundary overlap:** Does the proposal avoid Worker Selection, Readiness,
    Dispatch, Claims, Leases, Execution, Monitoring, Retry, and Completion ownership?
11. **Narrowness:** Can the proposal remain useful without choosing persistence,
    transport, API, queue, worker, or orchestration technology?
12. **Baseline conflict:** Is prohibiting selected-worker input in the canonical plan
    the correct resolution of the governing dependency rule?

## Implementation gate

- This ADR remains **Proposed**.
- This draft does not authorize implementation.
- The proposal must complete the Architecture Review Gate.
- The gate must return a binary `PASS` before implementation may be considered.
- A separate explicit Implementation Authorization decision is required after a
  `PASS`.
- A `FAIL` blocks implementation, and unresolved ownership or dependency conflict
  requires ADR revision and another review.

No runtime work may begin by implication from this ADR or its review.
