# Runtime Dependency Rules

> Subsystem names are conceptual roles. The table governs semantic dependencies,
> independent of future package layout.

| Subsystem | Allowed dependencies | Forbidden dependencies |
| --- | --- | --- |
| Request Intake | Transport contracts, canonical serialization, principal reference | Plans, workers, selection, execution |
| Validation | Request, versioned validation policy | Authorization outcome, workers, queues, execution |
| Planning | Validated request, versioned planning policy | Worker availability, readiness, selection, execution output |
| Authorization | Principal reference, request, plan, versioned policy | Selection, claims, queues, execution |
| Lease (future) | Authorization decision, lease policy | Ranking, execution result, completion |
| Queue Envelope (future) | Immutable upstream references, transport contract | Domain reconstruction, authorization truth, selection |
| Worker Identity (future) | Identity registry contract | Attestation, health, readiness, selection |
| Attestation (future) | Identity reference, trust policy and evidence | Health, selection, execution output |
| Health (future) | Identity reference, health observations | Authorization, readiness ownership, selection |
| Readiness (future) | Identity, attestation, health, capabilities, policy evidence | Selection, dispatch, claims, execution |
| Selection (future) | Plan, requirements, readiness, policy, versioned preferences | Dispatch, claims, queue consumption, execution, completion |
| Dispatch (future) | Selection, authority reference, dispatch policy | Recomputed ranking or readiness, execution |
| Claim (future) | Dispatch reference, claim policy, concurrency boundary | Selection logic, execution result |
| Execution (future) | Valid claim, bounded authority, workload reference, provider boundary | Selection, readiness mutation, retry policy |
| Monitoring (future) | Attempt reference, observations | Attempt ownership, retry or completion decision |
| Completion (future) | Execution evidence, completion policy | Selection, dispatch, provider invocation |
| Retry Policy (future) | Failed attempt, completion evidence, retry policy | History mutation, selection, execution ownership |
| Projection | Immutable history, projection version | Live authority, external effects |
| Replay | Immutable history, versioned contracts and configuration | Live providers, current health, queues, mutable projections |

## Globally forbidden dependencies

No component may depend semantically on downstream current state, a mutable
projection as authority, an unversioned policy, an unverified artifact, ambient
configuration, undocumented persistence, delivery order, current time during replay,
implicit global state, another organization's state, or execution output when making
an upstream decision.
