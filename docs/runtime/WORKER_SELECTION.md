# Worker Selection Foundation

Status: Accepted and implemented foundation
Governing baseline: [Runtime Architecture Baseline v1](RUNTIME_ARCHITECTURE_BASELINE_V1.md)
Review: [Worker Selection Architecture Review Gate](proposals/WORKER_SELECTION_ARCHITECTURE_REVIEW.md)

The implemented Python records and interfaces realize these semantic roles without
expanding them. The included in-memory history adapter provides deterministic
foundation and test semantics only; durable distributed persistence remains deferred.

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
excludedWorkers[]
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

### WorkerSelectionExclusion

```text
workerId
readinessReference
reasonCodes[]
evidenceReferences[]
canonicalHash
```

Excluded workers are ordered by canonical worker UUID. This history makes eligibility
decisions explainable without placing excluded workers in the candidate ranking.

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

ScoringPolicyV1 uses these components in this exact order:

| Component code | Maximum score |
| --- | ---: |
| `CAPABILITY_FIT` | 40 |
| `ORGANIZATION_POLICY_PREFERENCE` | 20 |
| `LATENCY_OBJECTIVE` | 15 |
| `COST_PREFERENCE` | 10 |
| `AFFINITY_PREFERENCE` | 10 |
| `LOAD_BALANCE` | 5 |

Required capabilities and hard policy constraints are eligibility gates. They cannot
be offset by a high score. `CAPABILITY_FIT` scores only versioned preferred
capabilities after all required capabilities match. Policy preference scores only
soft preferences after every hard constraint passes.

Each normalized component is a canonical decimal in `[0, 1]`. Values are represented
as fixed-point integers with six decimal places. Parse canonical decimal strings,
round the normalized value once using round-half-even at six decimal places, multiply
by the component's integer maximum, round the weighted result once with the same
rule, then sum the six rounded component scores. Binary floating point, intermediate
display rounding, and unspecified precision are prohibited.

Missing optional evidence yields a zero component and a component-specific
`*_EVIDENCE_MISSING` reason. No machine-learning or opaque score is permitted.

The immutable component registry is an ordered tuple keyed by exact scoring-policy
version. Filesystem discovery, entry points, import side effects, sets, and unordered
maps are prohibited. Unknown or duplicate policy versions fail closed.

## Missing-evidence behavior

- Invalid or missing readiness, plan, organization, required-capability, or hard-policy
  evidence excludes the affected worker.
- If required evidence prevents evaluation of every worker, return
  `EvidenceUnavailable`.
- If hard policy filters every otherwise evaluable worker, return `PolicyFiltered`.
- If retained evidence is contradictory and policy cannot resolve it, return
  `Indeterminate`.
- If at least one eligible worker remains, return `CandidateFound`, rank eligible
  candidates, and retain excluded workers with deterministic reason codes.
- `NoEligibleWorkers` is reserved for a valid, complete evidence set containing no
  readiness-positive worker for the workload context.

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

## API boundary

Implemented read/evaluate routes:

```text
POST /worker-selection/evaluate
GET  /worker-selection/{selectionId}
GET  /worker-selection/{selectionId}/history
GET  /worker-selection?workloadId={workloadContextId}
```

The following routes do not exist on the selection-only service and return `404`:

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

## Approved implementation placement after authorization

No files are created by this design milestone. If implementation is separately
authorized, the approved module boundary is:

```text
app/runtime/worker_selection/
|-- domain.py
|-- evaluator.py
|-- policy.py
|-- serialization.py
|-- ports.py
`-- service.py
```

Domain, policy, evaluator, and serialization remain pure and cannot depend on
FastAPI, SQLAlchemy, providers, queues, execution, or concrete persistence. Adapters
depend inward on protocols in `ports.py`. Future HTTP composition remains in the
existing application API boundary.

Focused tests belong under `tests/runtime/` and separate domain, evaluator, replay,
concurrency, and negative-route coverage.

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

- persistence and API implementation;
- Worker Readiness implementation;
- dispatch, scheduling, leases, claims, and queues;
- execution, providers, monitoring, completion, and retries;
- orchestration, worker lifecycle, and scaling;
- automatic model or worker promotion; and
- production deployment.
