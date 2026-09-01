# ADR 0014: Execution Attempt Admission Foundation

Status: Proposed

## Context

ADRs 0007 through 0013 establish immutable runtime evidence, single semantic
ownership, deterministic replay, Work Claim exclusivity, and bounded Execution
Lease authority. ADR 0013 deliberately leaves a future Execution Attempt owner a
bounded input contract but does not decide what an Attempt means.

ADR 0010 used broader conceptual language in which Work Execution owned an Attempt
that could be started and completed and could contain effects and result evidence.
That vocabulary is too broad for the next safe foundation. Combining admission,
effect initiation, running state, results, and completion in one owner would cross
the fact/decision/effect boundary and overlap future Monitoring, Completion, Retry,
and provider/runtime owners.

This decision therefore defines only whether one exact work item is admitted into
one initial bounded Execution Attempt under exact retained Work Claim and Execution
Lease evidence. It defines immutable proof of that admission and nothing effectful.

This ADR is architecture documentation only. Its review or merge does not authorize
implementation.

## Decision

Execution Attempt is the semantic owner of one decision:

> Whether one exact work item is admitted into one initial bounded attempt under
> exact retained Work Claim and Execution Lease evidence at an explicit semantic
> admission time.

The sole authoritative lifecycle event in this foundation is
`ATTEMPT_ADMITTED`. It is immutable evidence that admission succeeded. An admitted
Attempt may exist even when no external effect ever begins.

Execution Attempt owns:

- the admission decision and its reasoned, canonical evidence;
- an owner-scoped deterministic Attempt identity;
- its own append-only admission history and stream version;
- owner-scoped idempotency and expected-version concurrency; and
- deterministic reconstruction of admission.

Execution Attempt does not own execution, generic execution authority, effect
initiation, provider or model invocation, external effects, mutable process state,
progress, liveness, terminal truth, Retry, or later-Attempt eligibility.

## Refinement of ADR 0010

This ADR explicitly refines and partially supersedes ADR 0010's conceptual
Execution Attempt section for this foundation. It does not silently edit ADR 0010.

- `attempt started` is refined to `attempt admitted`;
- admission is not effect initiation;
- effect and result evidence are excluded from Execution Attempt admission;
- Attempt completion and terminal Attempt states are excluded;
- future Completion remains the sole owner of terminal adjudication; and
- future Retry remains the sole owner of later-Attempt eligibility.

ADRs 0007 through 0013 otherwise remain controlling. In particular, ADR 0013's
future-Attempt input contract is preserved and made concrete here without expanding
Execution Lease authority.

## Upstream evidence join

Neither possession of a claim nor possession of a lease is sufficient. Admission
is a fail-closed join of exact retained evidence from both owners, plus the causal
evidence needed to verify their consistency.

### Work Claim evidence

Admission requires:

- an accepted and applicable claim;
- exact claim identity and canonical digest;
- exact claim generation;
- the current acceptance fence at the retained admission boundary;
- exact claim event identity, history boundary, and lineage version;
- claimant identity;
- organization, workload, plan, and work-item scope; and
- retained selected-candidate and worker linkage proving that the claimant is the
  selected candidate or worker.

An expired claim or a claim released before the semantic admission boundary cannot
support a new admission. Attempt validates the retained claim's integrity, scope,
applicability, and linkage but does not mutate or consume it. Work Claim remains the
sole owner of claimant exclusivity, generation, acceptance fencing, expiry, and
release.

### Execution Lease evidence

Admission requires:

- exact lease lineage, identity, and canonical digest;
- exact lease generation, lineage version, event identity, and history boundary;
- an applicable, non-superseded generation at the retained admission time;
- the exact `INITIATE_WORK_ITEM_EXECUTION` permission;
- exact organization, workload, plan, and work-item scope;
- retained Authorization Checkpoint identity, digest, version, scope, and causality;
- exact lease policy identity, version, and digest; and
- exact configuration, schema, component, and serialization versions.

An expired lease, a superseded generation whose supersession precedes the admission
boundary, or a lease without the exact permission fails closed. Lease possession
does not create an Attempt. Execution Lease remains the sole owner of its lineage,
generation, permission, temporal applicability, renewal, revocation references,
and supersession.

### Dispatch and Authorization causality

Admission retains the exact Dispatch Decision identity and digest and the selected
candidate linkage needed to prove claimant/worker consistency. It does not
reinterpret Dispatch approval or rerank candidates.

Authorization remains mediated through Execution Lease. Attempt may validate the
retained Authorization Checkpoint causality required by the lease but must not
originate, broaden, replace, or independently reinterpret Authorization authority.

`INITIATE_WORK_ITEM_EXECUTION` permits evaluation of Attempt admission only. It is
not generic execution authority, provider or model invocation authority, queue
publication authority, or external-effect authority. Admission does not authorize
a future Effect owner to act.

## Attempt lineage, identity, and version

The owner-scoped Attempt lineage key is:

```text
(organization_id, workload_context_id, plan_id, work_item_id)
```

This is the one authoritative initial-admission stream for that work item. It is
organization/workload scoped, plan/work-item scoped, deterministic, and owned by
Execution Attempt. Claim generation, claim fence, claimant identity, lease identity,
lease generation, and an Attempt number are not stream identity.

Attempt identity is deterministic from the explicit Attempt namespace, artifact and
schema type, the lineage key, and the complete canonical admission inputs. Those
inputs include the exact retained claim, lease, Dispatch, Authorization-causality,
semantic-time, policy, configuration, schema, component, serialization, and
idempotency evidence defined by this ADR.

The initial-only foundation has no Attempt generation or Attempt number. Inventing
one would imply general later-Attempt semantics before Retry governance exists.
Callers therefore cannot submit either field. A future Retry decision may govern a
new lineage or numbering model, but it must not reinterpret this ADR as authority
for Attempt 2.

The following concepts remain distinct:

| Concept | Owner and meaning |
| --- | --- |
| Attempt identity | Attempt-owned digest-derived identity of the admitted artifact |
| Attempt lineage | Attempt-owned organization/workload/plan/work-item stream key |
| Attempt version | Monotonic stream version; `ATTEMPT_ADMITTED` is version 1 |
| Claim generation | Work Claim-owned accepted-claim generation |
| Claim fence | Work Claim-owned acceptance-only exclusivity fence |
| Lease generation | Execution Lease-owned permission generation |
| Lease lineage version | Execution Lease-owned event-stream position |

No caller may author the Attempt identity, Attempt version, outcome, canonical
digest, or an Attempt generation/number.

## Lifecycle and semantic time

`ATTEMPT_ADMITTED` is the only lifecycle event. This ADR defines no `STARTED`,
`TERMINATED`, `ABANDONED`, `SUPERSEDED`, `RESULT`, or `COMPLETED` event. Execution
Attempt is immutable admission evidence, not a mutable running process.

Admission receives and retains an explicit canonical semantic admission time. All
claim and lease applicability is evaluated against exact retained evidence at that
boundary. Current wall-clock time is never an authoritative input and replay never
consults it.

## Revocation and release boundaries

At admission, an applicable lease may support admission; an expired lease fails
closed. A generation superseded before the retained admission boundary fails closed.
Opaque, self-consistent revocation evidence grants no revocation authority. If a
future governed revocation contract proves that revocation occurred before
admission, that generation is inapplicable. This ADR does not invent the absent
concrete revocation-authority contract.

Revocation after admission but before future effect initiation remains unresolved:

- admission records historical admission truth;
- admission does not freeze authority for a future effect;
- an admitted Attempt does not authorize effect initiation;
- future Effect/Runtime governance must decide whether and how authority is
  revalidated immediately before an external effect; and
- this ADR does not resolve the admission/revocation/effect race.

Similarly, releasing a claim after valid admission does not rewrite historical
`ATTEMPT_ADMITTED` evidence. Whether that release prevents future effect initiation
belongs to future Effect-boundary governance. Both races are implementation-stop
conditions for future effectful work until governance resolves them.

## Canonical evidence and digest

Canonical admission evidence retains strict artifact/schema, component,
serialization, policy, and configuration versions. Its UTF-8 representation uses
stable field names, sorted map keys, defined list ordering, normalized timestamps
and enums, deterministic decimals, and no NaN or infinity. The canonical digest and
Attempt identity are deterministic over the complete canonical admission inputs.

At minimum, canonical idempotency content includes:

- organization and workload context;
- plan and work item;
- exact claim identity, digest, generation, fence, event/history boundary, lineage
  version, and claimant/worker linkage;
- exact lease identity, digest, generation, event/history boundary, lineage version,
  permission, scope, and Authorization causality;
- exact Dispatch identity, digest, and selected-candidate linkage;
- semantic admission time;
- policy, configuration, schema, component, and serialization versions; and
- submitted idempotency identity.

Missing, extra, foreign, malformed, unsupported, divergent, or authority-incomplete
evidence fails closed.

## Idempotency and concurrency

Idempotency is scoped by organization, workload, Attempt operation, and Attempt
lineage. An equivalent retry with identical canonical admission content returns the
original canonical admission. Reusing the identity with different content is an
explicit idempotency conflict and publishes nothing. Idempotency never authorizes a
second Attempt.

Every Attempt append supplies the expected Attempt stream version. For the initial
admission the expected version is zero. At most one contender can publish version 1.
A stale writer publishes nothing, advances no pointer, reloads committed history,
and recomputes. Timestamps never arbitrate. Claim fence and lease generation or
version are retained upstream evidence, not Attempt CAS tokens.

## Atomic publication

The smallest atomic boundary is one Attempt-owned publication containing:

- the immutable `ATTEMPT_ADMITTED` event;
- the deterministic Attempt identity index;
- the Attempt lineage/version update;
- the scoped idempotency record; and
- optionally, a disposable non-authoritative current projection.

Publication is all-or-nothing. It does not atomically create or mutate Work Claim,
Execution Lease, Dispatch, Authorization, Queue Envelope, Effect/Runtime,
Monitoring, Completion, Retry, or any external system. Cross-owner and cross-stream
atomicity are not assumed.

## Reconstruction and replay

Deterministic reconstruction consumes only:

- Attempt admission history through an explicit stream-version boundary;
- exact accepted Work Claim evidence through the retained boundary;
- exact Execution Lease evidence through the retained boundary;
- exact Dispatch and required Authorization causal evidence;
- exact policy, configuration, schema, component, and serialization versions; and
- the explicit retained semantic admission time.

It reproduces the same admission decision, event, Attempt identity, canonical bytes,
digest, reason evidence, and processed boundary. It never consults current time,
current claim or lease pointers, current Authorization, worker health, queues,
providers, execution state, mutable projections as authority, or unretained
administrative authority.

Missing, divergent, foreign, unsupported, version-gapped, integrity-invalid, or
authority-incomplete evidence fails closed. Replay performs no mutation, queue
action, provider invocation, history repair, or external effect. Integrity of opaque
revocation evidence never becomes proof of revocation authority during replay.

## Security and isolation

- Organization and workload scope are part of Attempt identity, lineage, and
  idempotency boundaries.
- Foreign claim or lease evidence is masked like absent.
- Cross-organization, cross-workload, cross-plan, and cross-work-item substitution
  fails closed.
- Claimant/worker mismatch and selected-candidate substitution fail closed.
- Tenant/workload replay substitution fails closed.
- Canonical Attempt evidence contains no secrets, credentials, tokens, or reusable
  authentication material.
- Same-scope integrity failures may be explicit when doing so does not disclose a
  foreign artifact.

## Ownership matrix

| Owner | Owned decision or evidence | Consumed evidence | Explicit non-ownership |
| --- | --- | --- | --- |
| Execution Request | Canonical requested intent and provenance | Caller/input provenance | Planning, authority, admission, execution |
| Execution Plan | Deterministic work decomposition | Valid request and planning policy | Workers, authority, admission, effects |
| Worker Selection | Candidate ordering and explanation | Plan, readiness, selection policy | Dispatch, claims, leases, admission, effects |
| Dispatch Decision | Approval or denial of one offer | Selection and applicable authority reference | Ranking, claimant exclusivity, admission, effects |
| Work Claim | Claimant exclusivity, generation, fence, expiry, release | Dispatch and claim policy | Authorization, admission, execution results |
| Authorization Checkpoint | Whether a principal may request a planned action | Principal, request, plan, policy | Leases, admission, execution |
| Execution Lease | Bounded retained permission, scope, applicability, generation, lifecycle | Authorization evidence and lease policy | Dispatch outcome, claims, admission, effects |
| Execution Attempt | Initial admission decision and immutable `ATTEMPT_ADMITTED` evidence | Exact claim/lease join and retained causal evidence | Effect initiation, running state, results, Completion, Retry |
| Future Effect/Runtime | Whether and how an admitted Attempt may initiate an effect, and effect-boundary evidence | Attempt plus future governed authority inputs | Admission truth, Monitoring, Completion, Retry |
| Future Monitoring | Progress and liveness observations | Attempt/effect references and observations | Attempt admission, terminal adjudication, Retry |
| Future Completion | Terminal adjudication and reason | Future execution/result evidence and completion policy | Effect generation, Retry policy, historical mutation |
| Future Retry | Later-Attempt eligibility and budget | Prior Attempt/Completion evidence and retry policy | Prior Attempt mutation, selection, execution |
| Future Queue Envelope | Transport and delivery metadata for immutable references | Governed immutable references and transport contract | Admission, claim, authorization, or execution truth |

## Adversarial and boundary cases

| Case | Required disposition |
| --- | --- |
| Foreign organization or workload replay | Mask foreign evidence like absent and fail closed |
| Cross-plan or cross-work-item substitution | Fail closed |
| Non-selected worker or claimant/worker mismatch | Fail closed |
| Expired claim or released claim seeking new admission | Fail closed |
| Expired lease or missing `INITIATE_WORK_ITEM_EXECUTION` | Fail closed |
| Lease generation superseded before admission | Fail closed |
| Opaque revocation evidence | Grants no authority; fail closed when required authority is incomplete |
| Replay inferring revocation authority | Prohibited and fail closed |
| Caller-selected Attempt identity, generation, or number | Reject |
| Concurrent admissions | Expected-version CAS permits at most one publication |
| Replay depending on current time or mutable current lease | Prohibited and fail closed |
| Admitted Attempt attempting an external effect | Prohibited; admission grants no effect authority |
| Attempt 1 treated as Retry authority | Prohibited |
| Admission treated as Completion | Prohibited |
| Revocation after admission before effect | Explicitly deferred to future Effect governance |
| Claim release after admission before effect | Historical admission stands; effect consequence deferred |
| Later Attempt without Retry authority | Prohibited |

## Retry, Effect, Monitoring, Completion, and Queue boundaries

Attempt 1 can exist without Retry. This ADR authorizes no Attempt 2. Attempt identity
or version cannot authorize another Attempt. Prior Attempt evidence is immutable;
future Retry may consume it and Completion evidence but may not mutate it.

Future Execution Effect/Runtime owns whether an admitted Attempt may initiate an
actual effect, how it is initiated, and effect-boundary execution evidence. This ADR
defines no provider/model/subprocess/remote execution, tool call, external write,
queue operation, effect result, or success/failure.

Future Monitoring owns progress and liveness observations. Future Completion owns
terminal adjudication and reason. Execution Attempt owns neither and therefore has
no terminal states.

Execution Attempt requires no queue. A future Queue Envelope may transport immutable
references but owns no admission, claim, authorization, or execution truth. This
decision introduces no broker, scheduler, worker process, or transport semantics.

## Deferred governance

The following remain unresolved and explicitly deferred:

- provider and effect boundary and execution mechanism;
- admission versus effect-initiation revocation race;
- claim release after admission versus effect initiation;
- effect-side authority revalidation;
- successful effect and result evidence;
- Monitoring contract;
- Completion contract;
- Retry eligibility, budget, and later-Attempt creation;
- post-revocation later-generation policy;
- durable persistence, APIs, migrations, queues, and concrete encoding choices.

These gaps do not block an admission-only ADR because they are outside this
decision. If implementation would require resolving any of them, implementation
must stop and return to governance.

## Explicit non-goals

This ADR does not define or authorize:

- actual execution or effect initiation;
- provider/model selection or invocation;
- external effects, writes, tool calls, subprocesses, or remote execution;
- queue transport, scheduling, orchestration, brokers, or worker processes;
- Monitoring, Completion, Retry policy, or later-Attempt authorization;
- the admission/revocation/effect race resolution;
- public APIs, routes, controllers, migrations, or deployment infrastructure;
- concrete durable or distributed persistence; or
- any runtime implementation or later milestone.

## Consequences

Admission becomes independently reviewable and replayable without conflating it
with effects. The cost is retention of exact cross-owner evidence boundaries and a
deliberate governance stop before effectful execution. Omitting Attempt generation
keeps the initial foundation honest and prevents an accidental Retry policy.

## Invariants

1. Execution Attempt owns admission only.
2. `ATTEMPT_ADMITTED` is the sole lifecycle event.
3. An admitted Attempt creates no external effect authority.
4. Exact applicable Work Claim and Execution Lease evidence are both required.
5. Authorization remains mediated through the exact Execution Lease causality.
6. `INITIATE_WORK_ITEM_EXECUTION` permits admission evaluation only.
7. Attempt lineage and identity are owner-scoped and deterministic.
8. This initial foundation has no Attempt generation or number.
9. Attempt version is distinct from all claim and lease generations, fences, and
   versions.
10. Semantic admission time is explicit and retained; replay uses no current time.
11. Revocation and release applicability at admission fail closed.
12. Post-admission effect races remain deferred.
13. Idempotency and CAS cannot produce or authorize a second Attempt.
14. Atomic publication is limited to one Attempt-owned commit.
15. Reconstruction is deterministic, effect-free, and fail-closed.
16. Foreign organization or workload evidence is masked like absent.
17. Monitoring, Completion, Retry, Queue, and Effect owners remain separate.
18. Accepted admission history is immutable.

## Architecture review questions

1. Is admission the only owned decision?
2. Is the claim/lease join exact and sufficient without transferring ownership?
3. Is the lineage key stable and free of upstream generation or downstream state?
4. Is omitting Attempt generation correct for an initial-only foundation?
5. Does the sole-event lifecycle avoid Effect, Monitoring, Completion, and Retry
   overlap?
6. Are semantic time, revocation, release, replay, concurrency, atomicity, and
   isolation fail-closed?
7. Does the ADR refine ADR 0010 explicitly while preserving ADR 0013?
8. Are all effectful and later-Attempt questions still governed stops?

## Implementation gate

**ADR 0014 remaining Proposed or being merged does not authorize implementation.**

Implementation requires a separate explicit governance authorization after this ADR
passes Architecture Review and is merged. Execution Attempt implementation remains unauthorized.
Execution Effect/Runtime and all downstream capabilities remain unauthorized.

A failed Architecture Review Gate or unresolved ownership, lineage, authority,
semantic-time, concurrency, reconstruction, security, or effect-boundary conflict
blocks implementation.
