# Runtime Architecture Baseline v1

Status: Governing upon merge
Milestone: v0.7A
Classification: Architecture-only
Decision: [ADR 0007](../decisions/0007-runtime-architecture-baseline-v1.md)

## 1. Authority and purpose

This document is the normative architecture for future EDGEIQ runtime features. A
future proposal must satisfy the [Architecture Review Gate](ARCHITECTURE_REVIEW_GATE.md)
before implementation is authorized. An approved ADR is required for deviations.

The baseline establishes deterministic, auditable, secure runtime boundaries while
remaining independent of programming language, persistence technology, queue,
scheduler, or orchestration framework.

> **Conceptual-contract notice:** Names such as `ExecutionPlan`, `WorkerSelection`,
> and `RuntimeHistoryStore` identify architectural roles and semantic boundaries.
> They do not require a Python class, API schema, service, database table, or other
> specific implementation structure.

## 2. Normative language

`MUST`, `MUST NOT`, `REQUIRED`, and `PROHIBITED` are binding. `SHOULD` records a
strong default whose exception requires evidence in the review gate. `MAY` describes
an allowed choice.

## 3. Constitutional invariants

1. Every authoritative fact and decision MUST have exactly one semantic owner.
2. Facts, decisions, and external effects MUST remain separate.
3. Components MUST consume only preceding authoritative artifacts.
4. Authoritative history MUST be immutable and append-only.
5. Identical canonical inputs, retained history, policies, and component versions
   MUST produce identical derived output.
6. Missing, invalid, stale, expired, unauthorized, or unverifiable evidence MUST
   fail closed.
7. Current-state projections MUST be disposable and MUST NOT replace history.
8. Concurrent writes MUST use explicit version checks; timestamps MUST NOT decide
   races.
9. A component MUST NOT create, extend, or reinterpret authority it does not own.
10. External effects MUST NOT occur before the authorizing transition is durably
    accepted.

## 4. Semantic ownership

The authoritative component boundaries are defined in the
[Runtime Component Map](RUNTIME_COMPONENT_MAP.md).

A component MAY validate the structure, integrity, freshness, and applicability of
an input artifact. It MUST NOT rewrite the artifact, manufacture missing authority,
or assume ownership of its semantics.

Historical facts remain true even when later artifacts cancel, revoke, supersede,
or compensate for them. Corrections MUST be new immutable records.

## 5. Lifecycle and dependency direction

The normative dependency direction is:

```text
Execution Request
  -> Request Validation
  -> Execution Plan
  -> Authorization Checkpoint
  -> Execution Lease                 [future]
  -> Queue Envelope                  [future]
  -> Worker Evidence and Readiness   [future]
  -> Worker Selection                [future]
  -> Dispatch Decision               [future]
  -> Work Claim                      [future]
  -> Work Execution                  [future]
  -> Monitoring                      [future]
  -> Completion                      [future]
```

The detailed lifecycle is defined in [Runtime Lifecycle](RUNTIME_LIFECYCLE.md), and
allowed dependencies are defined in [Runtime Dependency Rules](RUNTIME_DEPENDENCY_RULES.md).

No downstream artifact, future state, or execution output may influence a historical
upstream decision. Later evidence MAY trigger a new versioned evaluation.

## 6. Immutable history

Authoritative history MUST:

- be append-only;
- use a stable stream identity and monotonically increasing stream version;
- retain artifact type, schema version, organization, workload context, producer,
  producer version, causation, correlation, idempotency, evidence references, and a
  canonical payload hash;
- reject duplicate or missing stream versions;
- preserve superseded and failed decisions; and
- order records by stream version rather than timestamp.

Canonical identifiers MUST derive from an explicit namespace and canonical semantic
inputs. They MUST NOT depend on randomness, process identity, local paths, memory
addresses, host identity, wall-clock timing, or unordered enumeration.

The complete contract is defined in [Immutable History and Replay](IMMUTABLE_HISTORY_AND_REPLAY.md).

## 7. Deterministic replay

Replay MUST use only immutable history, immutable referenced artifacts, exact schema
and policy versions, exact deterministic component versions, canonical configuration,
and a declared stream-version boundary.

Replay MUST NOT:

- call live providers;
- consume current queues, health, configuration, or projections;
- use current time or unseeded randomness;
- depend on database order without an explicit ordering clause;
- repeat external effects;
- repair history; or
- replace missing evidence.

Replay MUST fail on missing evidence, unsupported versions, invalid hashes, version
gaps, invalid causal references, or output divergence. Failure MUST NOT mutate
authoritative history.

## 8. Concurrency

Every mutable current pointer MUST belong to one aggregate stream. An authoritative
append MUST supply the expected stream version and succeed atomically only when that
version matches.

The architecture requires:

- scoped idempotency keys;
- content-conflict detection for reused keys;
- explicit stale-write failures;
- re-evaluation after conflicts rather than replay of a stale decision;
- no timestamp arbitration for equal-time races;
- compensating or superseding records instead of historical rollback; and
- current pointers that reference only committed immutable artifacts.

Detailed rules are defined in [Runtime Concurrency](RUNTIME_CONCURRENCY.md).

## 9. Security and trust

Authentication, authorization, identity, attestation, health, readiness, selection,
claims, and execution are distinct responsibilities. No artifact in one category may
silently substitute for another.

Every protected artifact MUST carry organization scope. Cross-organization references
are PROHIBITED without a future explicit federation contract.

Only the Authorization Checkpoint owns authorization decisions. Downstream components
may validate applicability but MUST NOT expand the decision. Worker health, readiness,
selection, a lease, a claim, or prior success MUST NOT prove authorization or trust.

The trust zones and prohibited access paths are defined in
[Runtime Security Boundaries](RUNTIME_SECURITY_BOUNDARIES.md).

## 10. Failure semantics and negative routes

Runtime proposals MUST define stable domain failures covering, where applicable:

- invalid requests;
- validation failure;
- authentication failure;
- authorization denial;
- missing, invalid, expired, or unsupported artifacts;
- evidence unavailability;
- idempotency conflict;
- version conflict;
- replay failure or divergence;
- persistence failure; and
- internal runtime failure.

Failures MUST be fail-closed, redact sensitive data, preserve correlation evidence,
and MUST NOT be translated into successful domain outcomes.

A component-specific API MUST NOT expose routes for responsibilities it does not own.
Prohibited effectful routes MUST be absent and return `404` if requested.

## 11. Extension governance

Every extension point MUST declare:

- extension identity and semantic owner;
- supported input and output schema versions;
- deterministic configuration identity;
- failure behavior;
- security and organization requirements;
- replay support;
- deterministic execution order; and
- forbidden dependencies.

Extensions MUST NOT bypass ownership, introduce hidden external calls, read downstream
state, rely on ambient configuration, mutate history, or weaken fail-closed behavior.

## 12. Worker Selection boundary

Worker Selection is deferred. Its future architectural mission is limited to
deterministic, explainable ordering of contextually ready workers for an immutable
workload context.

It may consume an execution plan, workload and capability requirements, policy
constraints, authoritative readiness artifacts, organization context, and explicitly
versioned preferences.

It MUST NOT consume dispatch, claims, queue-consumption state, execution monitoring,
completion, outputs, provider responses, retry state, or other future execution state.

It MUST NOT schedule, dispatch, reserve, claim, lease, execute, retry, orchestrate,
change readiness, prove trust, or create authority. v0.7A defines no selection
algorithm, score, or API.

## 13. Review and change control

Every runtime feature proposal MUST provide evidence for each applicable gate:

- semantic ownership;
- immutable history;
- deterministic replay;
- concurrency;
- security boundaries;
- dependency direction;
- negative routes;
- extension points; and
- documentation completeness.

A `FAIL` blocks implementation. `NOT APPLICABLE` requires written justification.
Architectural deviations require an accepted ADR before implementation.

## 14. Scope exclusions

This baseline does not implement or select technologies for Worker Selection,
scheduling, queues, leases, claims, execution, monitoring, retries, orchestration,
worker lifecycle, scaling, production persistence, or production runtime services.
