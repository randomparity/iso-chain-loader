# Development Environment Implementation Plan

Goal: establish an idempotent repository-local development environment and shared checks.

Architecture: `just` is the single command interface. Its focused recipes are consumed directly
by local pre-commit hooks and through an aggregate recipe in GitHub Actions; Python tooling stays
inside `.venv`.

Tech stack: just, Python `venv`/pip, pre-commit, GitHub Actions.

Expected implementation size: 120–190 changed lines (M) — derived from nine configuration and
documentation files.

## Global Constraints

- The declared development host is Linux on x86_64 with Python 3.14 and just 1.57 or newer.
- The project output target is ppc64le; the host and target architectures are separate facts.
- The current releases selected on 2026-09-05 are just 1.58.0 and pre-commit 4.6.2.
- CI uses Python 3.14 and pins actions/checkout 7.0.1, actions/setup-python 7.0.0, and
  extractions/setup-just 4 to their resolved immutable commit revisions.
- Setup installs the complete hash-locked development dependency set into `.venv` and installs
  hooks without deleting local state.
- No full hardware suite runs in this change.

## Task 1: Add repeatable setup and focused checks

Files: create `.gitignore`, `.python-version`, `requirements-dev.in`, `requirements-dev.lock`,
`Justfile`, `.githooks/pre-commit`, and `.pre-commit-config.yaml`.

Interfaces:

- Provides commands `just setup`, `just check`, `just check-justfile`, and
  `just check-whitespace`.
- Provides `.venv/bin/pre-commit` at version 4.6.2 and an installed hook at the path returned by
  `git rev-parse --git-path hooks/pre-commit`.
- The installed hook resolves and invokes `.venv/bin/pre-commit` in the worktree where Git runs it.
- The Git pre-commit stage supplies no positional arguments; the launcher runs
  `.venv/bin/pre-commit run --hook-stage pre-commit` with no argument forwarding.
- Task 2 and CI consume the exact `just setup` and `just check` commands.

Verification:

- Mode: focused-test — setup availability and idempotency; before implementation `just setup`
  fails with an unknown-recipe error; after implementation, run `just setup && just setup`, expect
  exit 0 both times, `.venv/bin/pre-commit --version` to print `pre-commit 4.6.2`, and the path from
  `git rev-parse --git-path hooks/pre-commit` to exist.
- Mode: focused-test — worktree-independent hook launcher; inspect the installed hook for the
  absence of the installing worktree's absolute path, then execute it from the current worktree,
  expecting it to resolve the current root and run that root's pre-commit executable. Stage a
  temporary trailing-whitespace fault and invoke the hook with no arguments, expecting nonzero;
  unstage and remove the fault, then invoke it again, expecting exit 0.
- Mode: focused-test — locked environment reproducibility; create two clean temporary virtual
  environments, install with `pip install --require-hashes -r requirements-dev.lock`, and compare
  `pip freeze --all` output byte-for-byte, expecting equality.
- Mode: focused-test — Justfile formatting; introduce a temporary formatting fault and run
  `just check-justfile`, expect nonzero; revert it and rerun, expect exit 0.
- Mode: focused-test — whitespace rejection; introduce trailing whitespace in a temporary tracked
  fixture and run `just check-whitespace`, expect nonzero; remove the fault and rerun, expect
  exit 0.
- Mode: focused-test — aggregate contract; run `just check`, expect both focused recipes and exit 0.

Steps:

1. Run `just setup` and retain the unknown-recipe failure.
2. Add `.venv/` to `.gitignore`, set `.python-version` to `3.14`, declare
   `pre-commit==4.6.2` in `requirements-dev.in`, and add a complete resolved
   `requirements-dev.lock` with hashes for the Linux x86_64 Python 3.14 environment.
3. Add `Justfile` recipes: `setup` uses `python3 -m venv .venv`,
   `.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r
   requirements-dev.lock`, and installation of `.githooks/pre-commit` at
   `git rev-parse --git-path hooks/pre-commit`; `check` depends on both focused checks;
   `check-justfile` runs `just --fmt --check`; `check-whitespace` uses `git grep` and preserves
   errors distinct from the clean no-match exit.
4. Add a POSIX hook launcher that resolves the current worktree and emits an actionable setup
   error if its `.venv/bin/pre-commit` is absent, then executes `pre-commit run --hook-stage
   pre-commit`. Git passes no arguments to this hook stage. Make setup refuse to overwrite a
   non-matching existing hook. Add local pre-commit hooks with
   `language: system`, `pass_filenames: false`, and entries `just check-justfile` and
   `just check-whitespace`.
5. Run the controlled faults and two-clean-environment comparison from the verification inventory,
   revert each fault, then run the setup and aggregate checks.
6. Commit the configuration as `chore: add repeatable development setup`.

Acceptance: both setup runs succeed, the full resolved package set is hash-locked, the two clean
inventories match, the Git-resolved hook exists, focused faults fail, and the aggregate check
passes.

Rollback: remove `.gitignore`, `.python-version`, `requirements-dev.in`,
`requirements-dev.lock`, `Justfile`, `.githooks/pre-commit`, and `.pre-commit-config.yaml`.
Remove the installed Git-resolved hook only when it still matches `.githooks/pre-commit`; preserve
any other hook. `.venv` is ignored local state and can be deleted by its owner.

## Task 2: Document prerequisites and enforce checks in CI

Files: modify `README.md`; create `.github/workflows/checks.yml`.

Interfaces:

- Consumes the exact `just setup` and `just check` commands from Task 1.
- Documents x86_64 host requirements separately from ppc64le build and validation requirements.
- Provides the GitHub Actions `checks` job on pushes and pull requests.

Verification:

- Mode: focused-test — workflow invokes shared setup and aggregate check recipes; inspect the YAML
  and run the workflow's commands locally (`just setup` followed by `just check`), expecting exit 0.
- Mode: task-test-not-applicable — README prerequisite prose has no executable consumer; verify it
  by comparing its host, target, and build-tool lists against the accepted design.
- Mode: focused-test — local hook configuration; run `.venv/bin/pre-commit run --all-files`,
  expecting both configured local hooks to pass.
- Mode: focused-test — GitHub workflow semantics; after pushing the pull request head, verify the
  GitHub `checks` job exists for that exact head commit and succeeds. This is the delivery gate.

Steps:

1. Expand README with development setup, command usage, and separate host, ppc64le build, and
   validation prerequisite sections.
2. Add a least-privilege GitHub Actions workflow using checkout commit
   `3d3c42e5aac5ba805825da76410c181273ba90b1`, setup-python commit
   `5fda3b95a4ea91299a34e894583c3862153e4b97`, and setup-just commit
   `53165ef7e734c5c07cb06b3c8e7b647c5aa16db3`, with release-version comments.
3. Configure Python 3.14 and just 1.58.0, then run `just setup` and `just check` in CI.
4. Run the verification inventory and `just check` locally.
5. Commit the documentation and CI as `ci: run shared repository checks`.

Acceptance: docs separate host and target needs, workflow permissions are read-only, action pins
match current release revisions, and CI uses the same repository recipes as local development.

Rollback: remove the workflow and revert the README expansion; Task 1 remains independently useful.
