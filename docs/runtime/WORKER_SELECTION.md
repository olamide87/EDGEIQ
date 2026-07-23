# Worker Selection Foundation

Status: Proposed design
Governing baseline: [Runtime Architecture Baseline v1](RUNTIME_ARCHITECTURE_BASELINE_V1.md)
Review: [Worker Selection Architecture Review Gate](proposals/WORKER_SELECTION_ARCHITECTURE_REVIEW.md)

> **Conceptual-contract notice:** Interface and model names define semantic roles.
> They do not yet authorize Python classes, endpoints, persistence tables, or runtime
> services.

## Mission

Worker Selection ranks workers that are already contextually ready for one immutable
workload context and returns an explainable candidate ordering.

It answers only:

> Given this workload and this retained readiness evidence, which workers are the
> best candidates?

It never schedules, dispatches, reserves, claims, leases, consumes queues, executes,
invokes providers, retries, orchestrates, or changes worker lifecycle state.

## Semantic ownership

Worker Selection owns:

- one versioned selection evaluation;
- deterministic ordering of eligible candidates;
- score components and total score;
- ranks and deterministic tie-break evidence;
- selection outcome, explanations, and reason codes; and
- a mutable current-selection pointer derived from immutable history.

It must never own:

- request or plan semantics;
- authorization;
- worker identity, attestation, health, readiness, or capabilities;
- scheduling, dispatch, reservations, leases, claims, or queue state;
- execution, monitoring, output, completion, or retry policy; or
- trust proof or authority creation.

## Inputs

Required immutable inputs:

- organization and workload-context identity;
- `ExecutionPlan` reference;
- workload requirements;
- required capabilities;
- policy constraints;
- authoritative `WorkerReadiness` artifacts; and
- evaluator, scoring-policy, and schema versions.

Optional inputs are allowed only as retained, versioned evidence:

- locality preferences;
- affinity preferences;
- organization preferences;
- cost preferences;
- latency objectives; and
- workload-balancing metadata.

Forbidden inputs:

- dispatch decisions;
- work claims or leases;
- queue delivery or consumption state;
- future scheduling state;
- execution monitoring or output;
- completion;
- provider responses;
- retry state; and
- live worker state not captured by referenced readiness evidence.

## Conceptual interfaces

```text
WorkerSelectionEvaluator.evaluate(
    request: WorkerSelectionRequest
) -> WorkerSelectionEvaluation

WorkerSelectionHistory.append(
    selection: WorkerSelection,
    expectedVersion: int,
    idempotencyKey: str
) -> WorkerSelectionAppendResult

WorkerSelectionReplay.replay(
    boundary: WorkerSelectionReplayBoundary
) -> WorkerSelectionReplayResult
```

The evaluator is pure and effect-free. Persistence and replay are separate conceptual
boundaries. Implementation design must retain that separation.

## Conceptual data model

### WorkerSelectionRequest

```text
organizationId
workloadContextId
executionPlanReference
workloadRequirementsReference
capabilityRequirements
policyConstraintsReference
readinessReferences[]
preferenceEvidenceReferences[]
scoringPolicyVersion
evaluatorVersion
schemaVersion
evaluationBoundary
```

### WorkerSelection

Immutable historical evaluation:

```text
selectionId
organizationId
workloadContextId
version
outcome
candidates[]
inputEvidenceReferences[]
scoringPolicyVersion
evaluatorVersion
schemaVersion
replayMetadata
canonicalHash
evaluatedAt
recordedAt
```

### WorkerSelectionCurrent

Derived aggregate view:

```text
organizationId
workloadContextId
currentSelectionId
currentSelectionVersion
projectionVersion
updatedAt
```

Only the current pointer is mutable. It may reference only a committed immutable
selection and can be rebuilt from history.

### WorkerSelectionCandidate

```text
workerId
readinessReference
score
rank
scoreComponents[]
explanation
reasonCodes[]
evidenceReferences[]
readinessEvaluatedAt
canonicalHash
evaluationTimestamp
```

### ScoreComponent

```text
componentCode
rawValue
normalizedValue
weight
weightedScore
reasonCode
evidenceReferences[]
```

Weights and normalization rules belong to a versioned scoring policy. No machine
learning or opaque score is permitted.

## Outcomes

Stable outcomes:

- `CandidateFound`
- `NoEligibleWorkers`
- `PolicyFiltered`
- `EvidenceUnavailable`
- `Indeterminate`

`CandidateFound` requires at least one candidate. Empty candidate lists must use an
explicit non-success outcome and deterministic reason codes.

## Eligibility and ordering

Selection must first exclude any worker whose referenced readiness artifact:

- belongs to another organization or workload context;
- fails canonical hash or schema validation;
- is expired at the retained evaluation boundary;
- does not assert contextual readiness;
- lacks required capabilities; or
- violates an explicit policy constraint.

Eligible candidates are ordered by:

1. highest final score;
2. oldest readiness evaluation time;
3. lexicographically lowest canonical worker UUID.

Timestamps are retained evidence for this defined tie-break only; they never resolve
concurrent writes. Worker UUID comparison uses canonical lowercase hyphenated text.
No random or persistence-return order is permitted.

Rank is one-based and unique after all tie-breakers. Candidate arrays must be stored
in rank order.

## Explainable scoring contract

The first scoring policy may use explicit bounded components such as capability
match, policy preference, latency, cost, affinity, and load balance. This design does
not approve weights. A later implementation proposal must pre-register:

- every component;
- its input evidence;
- normalization and missing-evidence behavior;
- minimum and maximum values;
- weight;
- rounding rule; and
- reason codes.

The final score is the deterministic sum of weighted components using a specified
fixed decimal representation. Binary eligibility constraints must not be hidden
inside soft score components.

## Determinism and serialization

Identical canonical workload, readiness, policy, preferences, evaluator version, and
evaluation boundary must produce identical outcomes, candidates, scores, ranks,
explanations, reason codes, and hashes.

Canonical serialization requires UTF-8, stable field names, sorted map keys, defined
array ordering, canonical UUID and timestamp forms, explicit null semantics, fixed
decimal precision, and no NaN or infinity.

`evaluatedAt` and `recordedAt` are retained evidence. They must not enter semantic
identity unless supplied as part of the immutable evaluation boundary. Volatile
persistence time must not change `selectionId` or `canonicalHash`.

## Deterministic identifiers

```text
selectionId = namespacedHash(
    schemaVersion,
    organizationId,
    workloadContextId,
    executionPlanReference,
    ordered readinessReferences,
    ordered preferenceEvidenceReferences,
    policyConstraintsReference,
    scoringPolicyVersion,
    evaluatorVersion,
    evaluationBoundary
)
```

Candidate identity and hash include selection identity, worker identity, readiness
reference, score components, rank, reason codes, and ordered evidence references.

## Replay metadata

Every selection retains:

```text
historyBoundary
inputArtifactHashes[]
scoringPolicyHash
evaluatorVersion
canonicalConfigurationHash
candidateOrderingRuleVersion
serializationVersion
replayInputHash
replayOutputHash
```

Replay uses retained inputs only and performs no live health, readiness, provider,
queue, dispatch, or execution lookup. Missing evidence, unsupported versions, or hash
divergence produces a replay failure without changing history.

## Concurrency

- A workload-context selection stream is the aggregate ownership boundary.
- Appends use expected-version compare-and-swap.
- Idempotency is scoped by organization, workload context, operation, and canonical
  input identity.
- Reusing an idempotency key with different content is a conflict.
- A stale writer appends nothing and must recompute from newly committed history.
- Equal-time writes are never resolved by timestamp.
- Accepted selections are never rolled back or mutated; replacement is a new version.
- The current pointer advances only to a committed selection.
- Projection failure cannot orphan or invalidate immutable selection history.

## Security

Selection validates organization scope, artifact integrity, supported versions,
freshness at the retained boundary, and applicability. This validation does not
transfer ownership.

Selection cannot authenticate principals, authorize workloads, prove trust, validate
leases, consume queues, alter readiness, or access another organization's evidence.
Explanations and errors must reference safe reason codes without exposing sensitive
policy or worker evidence.

## Errors

Stable domain errors:

- `SelectionRequestInvalid`
- `SelectionArtifactNotFound`
- `SelectionArtifactInvalid`
- `SelectionArtifactVersionUnsupported`
- `SelectionEvidenceUnavailable`
- `SelectionEvidenceExpired`
- `SelectionOrganizationMismatch`
- `SelectionPolicyFiltered`
- `SelectionIndeterminate`
- `SelectionIdempotencyConflict`
- `SelectionVersionConflict`
- `SelectionReplayFailed`
- `SelectionReplayDiverged`
- `SelectionPersistenceUnavailable`
- `SelectionInternalFailure`

Errors fail closed and never produce a partial successful selection.

## Future API boundary

Potential read/evaluate routes:

```text
POST /worker-selection/evaluate
GET  /worker-selection/{selectionId}
GET  /worker-selection/{selectionId}/history
GET  /worker-selection?workloadId={workloadContextId}
```

This design does not authorize API implementation. The following routes must not
exist on a selection-only service and must return `404` if requested:

```text
/dispatch
/claim
/execute
/start
/retry
/invoke
/schedule
```

## Test plan for a future implementation

Determinism:

- identical reordered inputs produce identical selection and hash;
- map, set, and persistence order cannot affect candidates;
- all score and tie-break stages are deterministic;
- replay reproduces exact output; and
- volatile timestamps do not change semantic identity.

Ownership and negative routes:

- only readiness-positive workers are eligible;
- selection never mutates input artifacts;
- selection cannot dispatch, claim, execute, retry, or invoke;
- prohibited routes return `404`; and
- no queue, provider, execution, or completion dependency is present.

Concurrency:

- identical idempotent writes return the accepted selection;
- content mismatch returns idempotency conflict;
- one equal-version writer wins;
- stale writes append nothing;
- current pointers never reference uncommitted artifacts; and
- projection rebuild reproduces current state.

Security and failure:

- organization mismatch fails closed;
- invalid, missing, expired, or unsupported evidence has stable outcomes;
- error output is redacted; and
- replay and persistence failures cannot appear successful.

## Likely implementation areas after authorization

Repository-specific placement must be confirmed during implementation planning. A
future proposal may require domain models, a pure evaluator, history and projection
ports, API composition, tests, and documentation. This design deliberately names no
implementation files before that inspection and authorization.

## Acceptance criteria for design approval

- The Architecture Review Gate has no unresolved failures.
- Every input is an upstream immutable artifact or explicitly versioned preference.
- Ordering and all tie-breakers are complete and deterministic.
- Score evidence and reason codes are explainable.
- Immutable history, replay, concurrency, security, and errors satisfy the baseline.
- Forbidden dependencies and routes are explicit.
- Worker Selection performs no scheduling or execution effect.
- Implementation authority remains separately controlled.

## Deferred work

- scoring weights and normalization constants;
- persistence and API implementation;
- Worker Readiness implementation;
- dispatch, scheduling, leases, claims, and queues;
- execution, providers, monitoring, completion, and retries;
- orchestration, worker lifecycle, and scaling;
- automatic model or worker promotion; and
- production deployment.
