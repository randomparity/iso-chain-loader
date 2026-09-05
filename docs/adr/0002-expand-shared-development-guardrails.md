# ADR 0002: Expand Shared Development Guardrails

## Status

Accepted

## Context

ADR 0001 makes focused `just` recipes the source of truth for checks run by local hooks and CI.
The existing aggregate covers only Justfile formatting and trailing whitespace. The repository
needs Python lint and format checks, Markdown checks, and current-content secret detection before
runtime development begins, plus an explicit command for safe automatic fixes.

## Decision

Keep all commit and CI checks non-mutating. Add Ruff, rumdl, and detect-secrets to the existing
hash-locked Python development environment. Focused `just` recipes invoke the installed tools over
the repository, and both pre-commit and CI continue to consume those recipes. A separate `just
fix` command applies Ruff's safe fixes and formatter plus rumdl's formatter, then runs the complete
check-only aggregate. Secret detection checks tracked current content against a committed reviewed
baseline and does not scan Git history. Python type checking is deferred until owned Python source
paths exist.

## Consequences

The development lock gains platform-specific Ruff and rumdl artifacts for the declared Linux
x86_64 host. Updating the secret baseline is a deliberate review action, not part of `just fix`.
Formatter output remains visible in the working tree when a later check fails; automatic rollback
could overwrite concurrent edits. Adding Python later will immediately activate Ruff, while type
checking requires a separate change that names its source paths.

## Considered & rejected

- **Let pre-commit own remote tool environments.** judgment: this contradicts ADR 0001 and would
  separate local hook commands from the aggregate CI contract.
- **Add Node and Go toolchains for Markdown and secret checks.** judgment: Python-installable tools
  satisfy the requirements without two more provisioning and dependency surfaces.
- **Run formatters automatically from the commit hook.** judgment: commit-time mutation obscures
  the check-only contract explicitly selected for hooks and CI.
- **Run Python type checking over the repository root.** verified: `rg --files -g '*.py'` produced
  no paths at commit `8facf877a2a027c100ccd7fba5a74c90d55b8243`, so there is no owned source boundary to type-check.
- **Scan Git history on every commit.** judgment: issue #12 explicitly limits recurring detection
  to current tracked content.

