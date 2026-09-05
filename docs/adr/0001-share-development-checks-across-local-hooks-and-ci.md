# ADR 0001: Share Development Checks Across Local Hooks and CI

## Status

Accepted

## Context

The repository has no repeatable setup, local checks, or continuous integration. The first
development environment must keep local feedback and pull-request enforcement aligned without
introducing a second build system.

## Decision

`just` owns small, focused check recipes and one aggregate `check` recipe. A tracked hook launcher
invokes pre-commit from the current worktree, local pre-commit hooks invoke the focused recipes,
and GitHub Actions invokes the aggregate recipe after running the same `setup` recipe developers
use. The direct Python package is declared in
`requirements-dev.in`; its complete resolved set is hash-locked in `requirements-dev.lock` and
installed into a repository-local `.venv`.

## Consequences

Developers need Python 3.14 and just 1.57 or newer on the host. Setup is safe to repeat and does
not install Python packages globally. Git hooks are shared by linked worktrees through Git's
resolved hooks directory, while the launcher resolves the current worktree's `.venv` at hook run
time. Removing the worktree that installed the shared hook cannot strand an interpreter path. A
changed check has one recipe to update, while hooks still report the failing check separately. CI
action revisions and tool releases remain visible and reviewable in repository files.

The launcher implements only Git's `pre-commit` stage, which receives no positional arguments. It
executes the public command `.venv/bin/pre-commit run --hook-stage pre-commit`; no Git hook
arguments are dropped or transformed. Setup refuses to overwrite an unrelated existing hook.

## Considered & rejected

- **Duplicate shell commands in hooks and CI.** judgment: duplication would let local and remote
  enforcement drift as soon as either command changes.
- **Use only remote pre-commit hooks as the check runner.** judgment: this would hide the focused
  project commands behind pre-commit and make CI depend on hook orchestration for every check.
- **Install development tools globally.** verified: Python's standard `venv` module provides an
  isolated environment whose scripts can be invoked directly (Python 3.14 documentation, checked
  2026-09-05).
- **Pin only the direct development package.** verified: installing pre-commit 4.6.2 in a fresh
  Python 3.14 environment resolved nine additional packages on 2026-09-05, so a direct pin alone
  does not fix the installed package inventory.
