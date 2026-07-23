# EDGEIQ runtime architecture

Runtime Architecture Baseline v1 governs future EDGEIQ runtime features. These
documents define conceptual contracts only; they do not introduce production runtime
code or prescribe language-level interfaces.

## Governing documents

- [Runtime Architecture Baseline v1](RUNTIME_ARCHITECTURE_BASELINE_V1.md) — normative rules
- [ADR 0007](../decisions/0007-runtime-architecture-baseline-v1.md) — accepted decision
- [Architecture Review Gate](ARCHITECTURE_REVIEW_GATE.md) — mandatory proposal gate

## Supporting guidance

- [Runtime Component Map](RUNTIME_COMPONENT_MAP.md)
- [Runtime Lifecycle](RUNTIME_LIFECYCLE.md)
- [Immutable History and Replay](IMMUTABLE_HISTORY_AND_REPLAY.md)
- [Runtime Concurrency](RUNTIME_CONCURRENCY.md)
- [Runtime Security Boundaries](RUNTIME_SECURITY_BOUNDARIES.md)
- [Runtime Dependency Rules](RUNTIME_DEPENDENCY_RULES.md)

Supporting documents explain the normative baseline. If they conflict, the baseline
and ADR control. Worker Selection remains deferred until it passes the Architecture
Review Gate under the effective baseline.

## Active proposals

- [Worker Selection Foundation](WORKER_SELECTION.md)
- [Worker Selection Architecture Review Gate](proposals/WORKER_SELECTION_ARCHITECTURE_REVIEW.md)
- [Proposed ADR 0008](../decisions/0008-worker-selection-foundation.md)

The proposal is design-only. Its review is pending and implementation authority has
not been granted.
