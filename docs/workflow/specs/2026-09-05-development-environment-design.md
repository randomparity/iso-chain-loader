# Development Environment Design

Issue: [#2](https://github.com/randomparity/iso-chain-loader/issues/2)  
Decision: [ADR 0001](../../adr/0001-share-development-checks-across-local-hooks-and-ci.md)

## Goal

A fresh checkout provides one repeatable command that creates an isolated development
environment, installs the declared development dependency, and installs local hooks. Local hooks
and pull-request CI execute the same focused repository checks.

## Environment contract

The declared development host is Linux on x86_64 with Python 3.14 and just 1.57 or newer. The
project output target is ppc64le; the host and target architectures are separate facts. Building
bootable media will additionally require ppc64le-capable GNU binutils, GRUB image tooling,
`xorriso`, and a ppc64le emulator or real system for end-to-end validation. This change neither
installs those build prerequisites nor runs a hardware suite.

The current releases selected on 2026-09-05 are just 1.58.0 and pre-commit 4.6.2. CI uses Python
3.14 and pins actions/checkout 7.0.1, actions/setup-python 7.0.0, and extractions/setup-just 4 to
their resolved immutable commit revisions.

## Components and flow

`just setup` creates `.venv` with `python3 -m venv`, installs the complete hash-locked dependency
set from `requirements-dev.lock` through that environment's interpreter, then installs the
repository's pre-commit hooks. `requirements-dev.in` names the direct dependency and the lock file
records its resolved transitive set. Repeating setup updates the same environment and hook
installation without deleting local state. `.venv` is ignored by Git.

Git stores hooks in the repository's resolved hooks directory. Linked worktrees therefore share
the installed hook by design. Verification uses `git rev-parse --git-path hooks/pre-commit`, which
works in an ordinary checkout and a linked worktree and makes the shared behavior explicit.

The `Justfile` exposes `check-justfile` and `check-whitespace` as focused checks and `check` as
their aggregate. Local hook entries call the focused recipes independently. GitHub Actions checks
out the repository, provisions the declared Python and just versions, runs `just setup`, and runs
`just check`. CI receives read-only repository contents permission.

Setup fails at the command that cannot create the environment, install a declared package, or
install hooks; no failure is suppressed. The whitespace check distinguishes a clean no-match from
a Git error. Every command runs from the repository root.

## Security model

The design adds two dependency boundaries: PyPI packages installed by pip and GitHub Actions code
executed by CI. A developer and a pull-request CI job are the actors. The development lock pins
every resolved Python package and artifact hash; workflow actions use immutable commit revisions
with release comments; the workflow grants only `contents: read`.

Untrusted pull-request contents can influence the checks but receive no write token or repository
secrets. This design does not protect against compromise of PyPI, GitHub, or a pinned upstream
release; dependency review and future update automation are outside issue #2.

## Verification

From a clean checkout, the first and second `just setup` runs both succeed, `.venv` exists, the
installed `pre-commit` reports version 4.6.2, two clean environments produce identical `pip
freeze --all` inventories, and the path from `git rev-parse --git-path hooks/pre-commit` exists.
`just check` succeeds. A temporary trailing-whitespace fault makes `just check-whitespace` fail,
and a temporary malformed Justfile makes `just check-justfile` fail; reverting each fault restores
green. The first pull request run provides the live CI proof.

## Scope

The change covers repository setup, hooks, focused guardrails, CI, and documentation of host and
target prerequisites. Runtime loader code, bootable-media construction, cross-compilation setup,
and full ppc64le hardware validation remain outside this change.
