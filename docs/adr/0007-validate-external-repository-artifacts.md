# ADR 0007: Validate externally hosted repository artifacts before installation

## Status

Accepted

## Context

The launcher can point at an HTTP origin, but users have no copy-pasteable way
to check an independently hosted repository before booting. Public mirrors
must be protected by HTTPS, while local test servers need plain HTTP.

## Decision

Add a read-only `validate-external-source` command. It validates the manifest,
fetches the selected profile's five declared launcher artifacts, and checks
HTTP 200, exact size, and SHA-256. HTTPS uses the standard certificate and
hostname checks; redirects, credentials, queries, and fragments are rejected.
The command reports per-artifact JSON and does not mutate the server.

## Consequences

Users can fail fast on stale or incorrect mirror metadata. HTTPS public use is
explicit, and HTTP remains useful for loopback or controlled test fixtures.
The check does not enumerate every package requested by Anaconda. External
access logs need an adapter before they can satisfy the repository's stronger
JSONL evidence verifier.

## Considered & rejected

- **Permit only HTTPS.** judgment: the existing local server and deterministic
  tests use plain HTTP, and removing that path would break the documented local
  proof.
- **Download and hash the complete repository tree.** judgment: repository
  contents are open-ended and can be very large; the manifest's declared
  launcher artifacts are the bounded preflight contract.
- **Trust redirects or disable TLS verification.** verified: Python's default
  `urllib` opener follows redirects and its default HTTPS context verifies
  certificates; accepting either would weaken the explicit origin contract.
