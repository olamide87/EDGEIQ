from dataclasses import dataclass

from app.runtime.execution_lease.canonical import canonical_json, namespaced_digest
from app.runtime.execution_lease.domain import ExecutionLeaseDigestMismatch, ExecutionLeaseVersionUnsupported

POLICY_NAMESPACE = "edgeiq.execution-lease-policy.v1"


@dataclass(frozen=True)
class RegisteredExecutionLeasePolicy:
    policy_id: str
    policy_version: str
    canonical_digest: str


def _policy(policy_id: str, policy_version: str) -> RegisteredExecutionLeasePolicy:
    content = canonical_json({
        "policy_id": policy_id,
        "policy_version": policy_version,
        "rules": (
            "one_authoritative_lineage", "owner_assigned_generation",
            "same_generation_renewal", "active_generation_supersession",
            "revocation_authority_deferred_fail_closed", "half_open_applicability",
            "no_post_revocation_generation",
        ),
    }).encode("utf-8")
    return RegisteredExecutionLeasePolicy(policy_id, policy_version, namespaced_digest(POLICY_NAMESPACE, content))


EXECUTION_LEASE_POLICY_V1 = _policy("execution-lease-policy", "execution-lease-policy.v1")
POLICY_REGISTRY = (EXECUTION_LEASE_POLICY_V1,)


def policy_for(policy_id: str, policy_version: str, canonical_digest: str) -> RegisteredExecutionLeasePolicy:
    matches = tuple(policy for policy in POLICY_REGISTRY if policy.policy_id == policy_id and policy.policy_version == policy_version)
    if len(matches) != 1:
        raise ExecutionLeaseVersionUnsupported("Unsupported Execution Lease policy identity or version.")
    policy = matches[0]
    if policy.canonical_digest != canonical_digest:
        raise ExecutionLeaseDigestMismatch("Execution Lease policy digest does not match the registered policy.")
    return policy
