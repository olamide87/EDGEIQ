# Architecture Review Gate

Every future runtime proposal must complete this gate before implementation begins.
Use `PASS`, `FAIL`, or `NOT APPLICABLE`. Every result requires evidence; `FAIL`
blocks implementation, and `NOT APPLICABLE` requires written justification.

## Proposal identity

```text
Proposal:
Milestone:
Owner:
Review date:
Governing baseline version:
Related ADRs:
Decision: PENDING
```

## Gate checklist

### 1. Semantic ownership

Pass criteria:

- every new fact and decision has one owner;
- owned and forbidden responsibilities are explicit;
- facts, decisions, and effects remain separate; and
- downstream layers cannot mutate upstream meaning.

Evidence required: component boundary, inputs, outputs, responsibility table, and
negative ownership statements.

```text
Result:
Evidence:
Required changes:
```

### 2. Immutable history

Pass criteria:

- authoritative records are append-only;
- corrections and revocations are new records;
- current state is derived and rebuildable;
- ordering and versioning are explicit; and
- canonical hashes and evidence references are retained.

```text
Result:
Evidence:
Required changes:
```

### 3. Deterministic replay

Pass criteria:

- replay inputs and boundaries are explicit;
- schemas, policies, and component versions are retained;
- serialization and ordering are canonical;
- nondeterministic sources are prohibited; and
- missing evidence or divergence fails closed.

```text
Result:
Evidence:
Required changes:
```

### 4. Concurrency

Pass criteria:

- aggregate ownership and version checks are defined;
- idempotency scope and content conflicts are explicit;
- stale writes and equal-time races have deterministic handling;
- rollback uses compensation or supersession; and
- current pointers cannot reference uncommitted artifacts.

```text
Result:
Evidence:
Required changes:
```

### 5. Security boundaries

Pass criteria:

- trust zones and organization scope are identified;
- authentication, authorization, identity, trust, health, and readiness are distinct;
- authority cannot be created or extended downstream; and
- sensitive evidence and error disclosure are bounded.

```text
Result:
Evidence:
Required changes:
```

### 6. Dependency direction

Pass criteria:

- allowed and forbidden dependencies are listed;
- inputs come only from preceding authoritative artifacts;
- projections are not treated as authoritative; and
- downstream state cannot alter historical upstream decisions.

```text
Result:
Evidence:
Required changes:
```

### 7. Negative routes

Pass criteria:

- stable failures are defined;
- invalid, unauthorized, stale, and unavailable inputs fail closed;
- unsupported effectful routes do not exist; and
- persistence and internal failures cannot appear successful.

```text
Result:
Evidence:
Required changes:
```

### 8. Extension points

Pass criteria:

- extension contracts and order are explicit and versioned;
- configuration has canonical identity;
- failure and compatibility behavior are defined; and
- extensions preserve security, replay, and dependency boundaries.

```text
Result:
Evidence:
Required changes:
```

### 9. Documentation completeness

Pass criteria:

- purpose and non-goals are documented;
- component ownership and lifecycle position are clear;
- persistence, replay, concurrency, security, errors, and tests are addressed;
- deferred work is explicit; and
- an ADR records deviations or durable new decisions.

```text
Result:
Evidence:
Required changes:
```

## Final decision

```text
Overall result:
Blocking failures:
Approved deviations:
Implementation authorization: NOT GRANTED / GRANTED SEPARATELY
Reviewer:
Decision date:
```

Passing this gate does not itself authorize implementation unless the final decision
explicitly records separate implementation authority.
