# ADR 0008: Worker Selection Foundation

Status: Accepted

## Context

Runtime Architecture Baseline v1 is effective. The next runtime capability must be
designed entirely under its ownership, history, replay, concurrency, security,
dependency, and review-gate rules.

Worker Selection needs to answer which contextually ready workers are the best
candidates for an immutable workload context without taking responsibility for any
downstream operational effect.

## Proposed decision

Adopt [Worker Selection Foundation](../runtime/WORKER_SELECTION.md) as a deterministic,
explainable candidate-ordering boundary.

Worker Selection would own selection outcomes, scores, ranks, explanations, reason
codes, immutable selection history, and a derived current pointer. It would not own
readiness, identity, trust, health, authorization, scheduling, dispatch, queues,
leases, claims, execution, retries, completion, or worker lifecycle.

The
[Architecture Review Gate](../runtime/proposals/WORKER_SELECTION_ARCHITECTURE_REVIEW.md)
subsequently passed, and a separate implementation-authorization decision granted
authority for the bounded foundation described by this ADR.

## Deterministic scoring policy v1

The first scoring policy has a fixed 100-point total:

| Component | Maximum | Evidence |
| --- | ---: | --- |
| Capability fit | 40 | Preferred-capability matches after all required capabilities pass eligibility |
| Organization policy preference | 20 | Versioned soft policy preferences after all hard constraints pass eligibility |
| Latency objective | 15 | Retained readiness or preference evidence at the evaluation boundary |
| Cost preference | 10 | Retained versioned cost evidence |
| Affinity preference | 10 | Retained versioned workload-worker affinity evidence |
| Load balance | 5 | Retained versioned load metadata referenced by readiness evidence |

Required capabilities and hard policy constraints are binary eligibility gates and
cannot be recovered through score. An eligible worker receives a component score in
the closed range from zero through that component's maximum.

All component inputs and weights use fixed-point integers with six decimal places.
Implementations must parse canonical decimal strings, calculate with exact decimal
arithmetic, round each normalized component once using round-half-even at six decimal
places, multiply by its integer weight, round the weighted component once with the
same rule, and sum the six rounded components. Binary floating point is prohibited.

Candidates are ordered by highest final score, oldest readiness evaluation time, and
then lexicographically lowest canonical worker UUID.

## Missing-evidence policy

- Missing or invalid readiness, required capability, organization, plan, or hard
  policy evidence excludes that worker.
- If no worker can be evaluated because required evidence is unavailable, the outcome
  is `EvidenceUnavailable`.
- If every otherwise evaluable worker violates a hard policy constraint, the outcome
  is `PolicyFiltered`.
- Missing optional scoring evidence contributes zero to that component and records a
  component-specific `*_EVIDENCE_MISSING` reason code.
- A result may be `CandidateFound` when at least one worker remains eligible. Every
  excluded worker must be retained in deterministic worker-ID order with exclusion
  reason codes and evidence references.
- Contradictory evidence that cannot be resolved from versioned policy produces
  `Indeterminate`; selection must not guess or use current state.

## Repository placement and registration

Subject to separate implementation authorization, Worker Selection will live under:

```text
app/runtime/worker_selection/
|-- domain.py          Immutable conceptual contract representations
|-- evaluator.py       Pure deterministic eligibility, scoring, and ordering
|-- policy.py          ScoringPolicyV1 and immutable ordered component registry
|-- serialization.py   Canonical serialization and hashing
|-- ports.py           History and projection protocols only
`-- service.py         Idempotent evaluation and append coordination

tests/runtime/
|-- test_worker_selection_domain.py
|-- test_worker_selection_evaluator.py
|-- test_worker_selection_replay.py
|-- test_worker_selection_concurrency.py
`-- test_worker_selection_api.py
```

Any future HTTP composition belongs in the existing application API boundary and may
depend on the service, never the evaluator in reverse. Persistence adapters depend on
`ports.py`; domain, policy, evaluator, and serialization must not depend on FastAPI,
SQLAlchemy, queues, providers, execution, or persistence implementations.

Policy registration is an immutable ordered tuple declared in `policy.py`. Discovery
through entry points, filesystem scanning, import side effects, sets, or unordered
maps is prohibited. Policy lookup is by exact policy version. Unknown or duplicate
versions fail closed.

## Rationale

Separating candidate ordering from dispatch preserves the baseline's distinction
between decision and effect. Explicit scores and stable tie-breakers support replay
and audit without an opaque ranking model.

## Consequences

- all inputs must be retained upstream artifacts or versioned preference evidence;
- identical canonical inputs must reproduce identical ordering;
- selection history is immutable and current ranking is a rebuildable projection;
- future implementation must pre-register scoring weights and decimal rules; and
- dispatch and every downstream effect require separate components and reviews.

## Governance result

The Architecture Review Gate records `PASS`. No conditional approval remains. A
separate decision subsequently authorized implementation strictly within this ADR;
the ADR and gate alone did not grant that authority.
