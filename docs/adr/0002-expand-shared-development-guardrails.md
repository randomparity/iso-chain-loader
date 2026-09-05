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
the repository, and both pre-commit and CI continue to consume those recipes. A separate `just fix`
command applies Ruff's safe fixes and formatter plus rumdl's formatter, then runs the complete
check-only aggregate. Secret detection checks tracked current content against a committed reviewed
baseline and does not scan Git history. Python type checking is deferred until owned Python source
paths exist.

Check-only Ruff and rumdl invocations disable their filesystem caches. Every rumdl invocation names
the repository-root configuration, makes configuration warnings fatal, and disables preview
code-block tools on the command line; Markdown line-length enforcement excludes fenced code
payloads. Secret checking copies the committed baseline outside the repository, compares every
tracked path against that disposable copy in one option-terminated invocation, and discards the
copy. Git enumeration must complete successfully
before the detector starts, and an argument list too large for one comparison fails rather than
silently partitioning the baseline operation.

## Consequences

The development lock gains platform-specific Ruff and rumdl artifacts for the declared Linux
x86_64 host. Updating the secret baseline is a deliberate review action, not part of `just fix`.
Ordinary secret checks may update only a disposable baseline copy because detect-secrets' hook can
maintain the baseline it receives. Repository growth beyond one operating-system argument vector
requires a later scanning design rather than silently weakening comparison semantics.
Formatter output remains visible in the working tree when a later check fails; automatic rollback
could overwrite concurrent edits. Adding Python later will immediately activate Ruff, while type
checking requires a separate change that names its source paths. Markdown formatting may normalize
fence structure but does not rewrite the fenced examples' language payloads.

## Considered & rejected

- **Let pre-commit own remote tool environments.** judgment: this contradicts ADR 0001 and would
  separate local hook commands from the aggregate CI contract.
- **Add Node and Go toolchains for Markdown and secret checks.** judgment: Python-installable tools
  satisfy the requirements without two more provisioning and dependency surfaces.
- **Run formatters automatically from the commit hook.** judgment: commit-time mutation obscures
  the check-only contract explicitly selected for hooks and CI.
- **Run Python type checking over the repository root.** verified: `rg --files -g '*.py'` produced
  no paths at commit `8facf877a2a027c100ccd7fba5a74c90d55b8243`, so there is no owned source
  boundary to type-check.
- **Scan Git history on every commit.** judgment: issue #12 explicitly limits recurring detection
  to current tracked content.
- **Pass the committed baseline directly to detect-secrets-hook.** verified: the detect-secrets
  1.5.0 hook implementation saves maintenance changes to the baseline it receives, contradicting
  the check-only contract; a disposable copy contains those writes outside the repository.
- **Format fenced examples with their language linters.** judgment: examples may intentionally be
  incomplete or incorrect, so rewriting them would change documentation content rather than style.
- **Rely on rumdl's directory-based configuration discovery.** verified: rumdl 0.2.66 documents
  per-directory configuration resolution; naming the root configuration and disabling code-block
  tools at the CLI prevents a nested file from changing the repository contract.
