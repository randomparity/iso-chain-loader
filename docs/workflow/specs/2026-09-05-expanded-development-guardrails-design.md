# Expanded Development Guardrails Design

Issue: [#12](https://github.com/randomparity/iso-chain-loader/issues/12)
Decision: [ADR 0002](../../adr/0002-expand-shared-development-guardrails.md)

## Goal

Extend the repository's shared local and CI checks with non-mutating Python lint and format
validation, Markdown validation, and current-content secret detection. Provide a separate explicit
command that applies safe formatting fixes and proves the resulting tree with the full checks.

## Tool and command contract

Official package indexes were checked on 2026-09-05. The selected stable releases are Ruff 0.16.6,
rumdl 0.2.66, and detect-secrets 1.5.0. They are direct development dependencies alongside
pre-commit and are resolved with hashes for CPython 3.14 on Linux x86_64.

`just check-python-lint`, `just check-python-format`, `just check-markdown`, and `just
check-secrets` are focused non-mutating recipes. `just check` aggregates them with the existing
Justfile and whitespace checks. Local pre-commit entries call the focused recipes with
`pass_filenames: false`; CI needs no new orchestration because it already executes `just check`.

`just fix` runs safe Ruff lint fixes, Ruff formatting, and rumdl formatting in that order, then
runs `just check`. Ruff unsafe fixes are not enabled. A formatter failure stops immediately; a
later check failure leaves prior changes visible for the developer to inspect. The command never
updates the secret baseline.

Ruff uses stable behavior, targets the declared Python 3.14 development version, and passes
`--no-cache` on every check-only invocation. Its standard discovery rules exclude the repository
virtual environment. Python type checking is absent until a later change can name explicit
production and test paths.

rumdl checks tracked Markdown in the repository and uses the repository's 100-character line
limit. Generated or vendored content is not introduced by this change, so no speculative
exclusions are configured.

The secret recipe first completes a NUL-delimited tracked-file inventory from Git in a temporary
file. It copies `.secrets.baseline` to a second temporary file, then passes every inventoried path
in one `detect-secrets-hook` invocation after an explicit `--` option terminator. The invocation
fails rather than splitting when the platform argument limit cannot hold the complete set. Any
automatic baseline maintenance therefore changes only the disposable copy. Traps remove both
temporary files. A baseline change is separately generated and reviewed; neither checks nor fixes
accept findings automatically. The recurring check does not traverse Git history or untracked
files.

## Failure behavior

Each focused command returns the underlying tool's nonzero status and reports the affected path and
rule or detector. An unavailable executable fails with the shell's ordinary actionable error and
is remedied by `just setup`. Git file-enumeration errors fail the secret check rather than being
read as an empty repository. An empty Python file set is a successful Ruff check because no Python
contract exists yet; newly tracked Python files are discovered without changing recipes.

## Security model

### Boundary inventory

- Added: PyPI supplies Ruff, rumdl, detect-secrets, and their resolved transitive packages to
  `just setup`.
- Added: tracked repository bytes cross into detect-secrets detectors and are compared with the
  committed baseline.
- Widened: pull-request content reaches more executables in the existing read-only CI job.

### Actor model and controls

Developers and pull-request authors control checked-out content. Exact direct versions, resolved
artifact hashes, the existing isolated environment, and read-only CI permissions constrain the
dependency and CI boundaries. The tracked-file list is NUL-delimited so filenames cannot split
arguments. The option terminator prevents an attacker-controlled filename from becoming detector
configuration, and completing enumeration before invocation preserves Git failures. Detector
output may reveal the location and shape of suspected credentials, so CI and hook output must not
print secret values; detect-secrets' hook-style comparison provides that control. Baseline diffs
expose hashes and detector metadata rather than plaintext secrets and remain subject to human
review.

### Explicitly out of scope

The guardrail does not prove that tracked content contains no secret, scan prior commits, inspect
untracked files, revoke exposed credentials, or protect against a compromised package index or
maintainer. It prevents known detector findings from being introduced into the checked current
tree; repository history remediation and credential response require separately authorized work.

## Verification

- A temporary Python lint violation makes `just check-python-lint` fail; safe fixing removes it.
- A temporary unformatted Python file makes `just check-python-format` fail; `just fix` formats it.
- A temporary Markdown formatting violation makes `just check-markdown` fail; `just fix` formats it.
- A temporary nonfunctional fake credential matching an enabled detector makes `just
  check-secrets` fail without printing the credential value.
- After reverting fixtures, `just check` and `.venv/bin/pre-commit run --all-files` succeed.
- Before and after `just check`, a NUL-delimited tracked-path inventory and SHA-256 digest for every
  tracked file are byte-compared alongside a NUL-delimited `git status --porcelain=v1 --ignored
  --untracked-files=all` snapshot. Together they prove that the aggregate changes no tracked bytes
  and adds or changes no ignored or untracked repository path. A deliberately fixable fixture
  proves `just fix` does mutate and then exits green.
- A disposable test baseline containing an entry absent from the tracked tree proves the committed
  baseline remains byte-identical and the content-aware repository snapshots remain unchanged when
  detect-secrets performs maintenance.
- A tracked filename beginning with `--exclude-files=` plus a fake secret elsewhere proves option
  injection cannot disable detection.

## Scope and architecture context

The development host remains Linux x86_64 with Python 3.14 and just 1.57 or newer. The output target
remains ppc64le; these checks are architecture-insensitive except for the resolved development
wheels. Runtime loader work, type checking, history scanning, credential remediation, unsafe fixes,
and unrelated CI changes are excluded.

Quest continuation: branch `feat/expand-guardrails-12`; base branch `main`; guardrails are `just
check` and `.venv/bin/pre-commit run --all-files` after `just setup`.
