# Security

EDGEIQ is a local-first research and paper-trading application. It does not automate
logins, scrape restricted sportsbook interfaces, or place wagers. Secrets belong in
environment configuration and must not be committed, logged, copied into research
artifacts, or exposed through error responses.

## Future runtime security

Future runtime work is governed by
[Runtime Architecture Baseline v1](docs/runtime/RUNTIME_ARCHITECTURE_BASELINE_V1.md)
and its [security boundaries](docs/runtime/RUNTIME_SECURITY_BOUNDARIES.md).

The baseline requires:

- explicit trust zones and organization scope;
- separation of authentication, authorization, identity, attestation, health,
  readiness, selection, claims, and execution;
- fail-closed handling for absent or invalid authority and evidence;
- least-authority artifact exchange;
- no cross-organization access without an approved federation contract;
- redacted diagnostic and audit output; and
- no downstream creation or extension of authority.

Worker Selection and all production runtime services remain unimplemented. Any future
proposal must pass the Architecture Review Gate before implementation is authorized.

## Reporting

Do not include secrets, credentials, private data, or exploit details in a public
issue. Contact the repository owner through GitHub for private coordination.
