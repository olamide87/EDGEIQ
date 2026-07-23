# Runtime Concurrency

## Aggregate ownership

Each mutable current pointer belongs to one aggregate stream. The immutable artifact
behind the pointer remains historical evidence.

## Compare-and-swap

An authoritative append supplies an expected stream version:

```text
append(streamId, expectedVersion, events)
```

At most one competing append for the same expected version succeeds. A loser receives
an explicit conflict and must reload history and recompute its decision.

```mermaid
sequenceDiagram
    participant A as Writer A
    participant B as Writer B
    participant H as History Store
    A->>H: append expected v7
    B->>H: append expected v7
    H-->>A: accepted as v8
    H-->>B: version conflict
    B->>H: reload through v8
    Note over B: recompute; never reuse stale decision
```

## Idempotency

Idempotency keys are scoped by organization, operation, and workload or aggregate.
Repeating identical canonical content returns the accepted result. Reusing a key with
different content is an idempotency conflict.

## Required race behavior

- Timestamps do not determine winners.
- Stale writes append nothing and advance no pointer.
- Shared mutable in-process domain objects are prohibited.
- Caches are disposable and cannot alter semantic results.
- Multiple events in one owning stream append atomically.
- Cross-stream atomicity is not assumed.
- Accepted history is corrected through new events, never rollback by deletion.
- A current pointer references only a committed artifact.

Future external effects require persisted intent or an equivalent atomic outbox
boundary, but v0.7A selects no implementation.
