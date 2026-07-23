# ADR 0007: Runtime Architecture Baseline v1

Status: Accepted

## Context

EDGEIQ has deterministic research and paper-trading components, but it does not yet
have a governing architecture for future distributed runtime capabilities. Adding
worker selection, dispatch, claims, or execution without a prior constitutional
boundary would risk ambiguous ownership, mutable history, nondeterministic replay,
and accidental authority expansion.

The project needs an architecture-only baseline before any production runtime work
begins.

## Decision

Adopt [Runtime Architecture Baseline v1](../runtime/RUNTIME_ARCHITECTURE_BASELINE_V1.md)
as the governing specification for future EDGEIQ runtime features.

The baseline requires:

- one semantic owner for every authoritative fact and decision;
- separation of facts, decisions, and external effects;
- immutable, append-only authoritative history;
- deterministic identifiers, serialization, ordering, and replay;
- compare-and-swap concurrency with explicit idempotency and stale-write handling;
- fail-closed authorization, trust, and organization boundaries;
- dependencies only on preceding authoritative artifacts;
- explicit negative routes and stable failure semantics;
- bounded, versioned extension points; and
- a completed Architecture Review Gate before implementation authorization.

Names such as `ExecutionPlan`, `WorkerSelection`, and `RuntimeHistoryStore` are
conceptual contracts. This decision does not require Python classes, services,
database tables, APIs, or any other specific representation.

## Rationale

Publishing the rules before implementing runtime features makes the architecture
reviewable independently from code. It also prevents downstream components from
quietly taking ownership of authorization, trust, readiness, execution, or history.

Deterministic replay and immutable evidence are especially important for explaining
why a runtime decision occurred. Optimistic concurrency and idempotency provide a
technology-neutral foundation for future distributed work without prematurely
selecting a queue, database, scheduler, or orchestration framework.

## Consequences

Positive:

- future runtime proposals have objective review criteria;
- ownership and dependency violations can be rejected before implementation;
- retained evidence can support deterministic reconstruction and audit;
- Worker Selection can be designed as ordering only, without dispatch leakage; and
- implementation technologies remain open behind stable semantic contracts.

Costs:

- runtime proposals require additional architecture evidence;
- historical policies and schemas must remain available for replay;
- accepted history cannot be corrected through mutation; and
- convenience dependencies on live or downstream state are prohibited.

## Scope and effectiveness

This milestone is documentation-only. It introduces no production code, runtime
behavior, APIs, persistence, migrations, execution logic, or runtime dependencies.

This ADR and its linked documentation make the baseline effective when merged.
Worker Selection and all downstream runtime capabilities remain deferred and require
their own successful Architecture Review Gate and separate implementation approval.

## Rejected alternatives

- **Implement Worker Selection first:** rejected because no governing runtime
  contracts existed.
- **Let implementation define the architecture:** rejected because code review would
  conflate constitutional decisions with technology choices.
- **Use mutable current-state records as history:** rejected because audit and replay
  would be incomplete.
- **Permit downstream state in upstream decisions:** rejected because it creates
  circular ownership and future-state leakage.
- **Choose a queue or orchestration framework now:** rejected as premature for an
  architecture-only milestone.
