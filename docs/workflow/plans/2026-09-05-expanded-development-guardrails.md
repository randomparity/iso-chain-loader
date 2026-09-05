# Expanded Development Guardrails Implementation Plan

Goal: extend shared repository checks with pinned Python, Markdown, and current-content secret
guardrails plus an explicit safe mutating command.

Architecture: focused `just` recipes remain the single command source used by local pre-commit
hooks and the aggregate CI check. Ruff, rumdl, and detect-secrets run from the existing hash-locked
Python environment; only `just fix` mutates content.

Tech stack: just, pre-commit 4.6.2, Ruff 0.16.6, rumdl 0.2.66, detect-secrets 1.5.0, Python 3.14.

Expected implementation size: 90–150 changed lines (M) — derived from four focused recipes, one
fix recipe, tool configuration, dependency pins, a baseline, hooks, and documentation.

## Global Constraints

- The development host is Linux x86_64 with Python 3.14 and just 1.57 or newer; the project output
  target is ppc64le.
- `just check`, every focused check, pre-commit, and CI are non-mutating.
- `just fix` alone applies safe Ruff lint fixes, Ruff formatting, and rumdl formatting before the
  complete check aggregate; it never updates the secret baseline or enables unsafe Ruff fixes.
- Secret detection covers current tracked content only, with NUL-safe filename handling, and does
  not print detected values.
- Check-only Ruff commands use `--no-cache`. Secret checks pass all tracked paths after `--` to one
  detector invocation against a disposable baseline copy; Git enumeration and oversized argument
  failures propagate.
- Python type checking and Git-history secret scanning remain excluded.
- Exact stable pins are Ruff 0.16.6, rumdl 0.2.66, and detect-secrets 1.5.0, resolved with artifact
  hashes alongside pre-commit 4.6.2.

## Task 1: Add the locked toolchain and focused contracts

Files: modify `requirements-dev.in`, `requirements-dev.lock`, `Justfile`, and
`.pre-commit-config.yaml`; create `pyproject.toml` and `.secrets.baseline`.

### Interfaces

- Consumes: ADR 0001's focused-recipe and aggregate-check contract.
- Provides: `check-python-lint`, `check-python-format`, `check-markdown`, `check-secrets`, and
  `fix` recipes; installed `ruff`, `rumdl`, and `detect-secrets-hook` executables.
- Later consumers: existing CI runs `just check`; developers run `just fix`; pre-commit invokes
  each focused recipe with no filename forwarding.

### Verification

- Mode: focused-test — dependency installation; after changing direct pins, run `just setup` and
  expect exit 0 plus exact tool versions from `.venv/bin/ruff --version`, `.venv/bin/rumdl
  --version`, and `.venv/bin/detect-secrets --version`.
- Mode: focused-test — each check rejects its controlled Python lint, Python format, Markdown, or
  fake-secret fixture; run the corresponding `just check-*` command and expect nonzero, remove or
  fix the fixture, and expect exit 0.
- Mode: focused-test — mutation boundaries; before and after `just check`, record and byte-compare
  the NUL-delimited tracked-path inventory with SHA-256 digests for every tracked file and a
  NUL-delimited `git status --porcelain=v1 --ignored --untracked-files=all` snapshot. Expect both
  comparisons to match; introduce fixable Python and Markdown fixtures, run `just fix`, and expect
  changed formatted fixtures followed by exit 0.
- Mode: focused-test — secret scanner isolation; use a controlled baseline entry absent from the
  tracked tree, copy `.secrets.baseline` before `just check-secrets`, and expect `cmp` plus both
  content-aware repository snapshot comparisons to succeed afterward. Track a filename beginning
  with `--exclude-files=` and a separate fake-secret fixture, then expect detection to fail without
  printing the value.
- Mode: focused-test — hook integration; run `.venv/bin/pre-commit run --all-files` and expect all
  configured hooks to pass without modifying tracked files.

### Steps

1. Add the three exact direct pins to `requirements-dev.in`; resolve the complete CPython 3.14
   Linux x86_64 dependency inventory and hashes into `requirements-dev.lock`; run `just setup` and
   verify the three exact versions.
2. Add minimal stable Ruff and rumdl configuration to `pyproject.toml`; generate and inspect a
   detect-secrets 1.5.0 baseline for the tracked tree, confirming it contains no plaintext secret.
3. Add the four non-mutating focused recipes and aggregate dependencies. Pass `--no-cache` to Ruff
   checks. Complete Git's NUL-delimited path inventory before secret scanning, copy the baseline to
   a temporary file, and use a single option-terminated detector invocation that fails if the
   argument set cannot fit; propagate Git and detector failures and clean up both temporary files.
4. Add `fix` with `ruff check --fix`, `ruff format`, `rumdl fmt`, then `just check`; do not pass an
   unsafe-fixes flag or invoke baseline generation.
5. Add matching local hooks using `language: system` and `pass_filenames: false`.
6. Introduce one controlled fault at a time, including the baseline-maintenance and option-shaped
   filename cases, and capture the expected red result; revert or safely fix it, then run `just
   check` and pre-commit with expected exit 0.
7. Commit as `chore: expand development guardrails` after reviewing the complete diff.

Acceptance: all four focused contracts fail on their matching fault and pass clean; `just check`
is demonstrably non-mutating; `just fix` mutates only fixable Python and Markdown content and ends
green; the environment installs only hash-locked artifacts.

Rollback: revert the implementation commit. Never discard formatter edits automatically; the
developer owns visible working-tree changes.

## Task 2: Document the developer workflow

Files: modify `README.md`.

### Interfaces

- Consumes: the exact `just check` and `just fix` behavior from Task 1.
- Provides: developer-facing commands and mutation expectations.
- Later consumers: contributors deciding whether to validate or rewrite files.

### Verification

- Mode: task-test-not-applicable — README prose has no executable consumer that validates semantic
  wording; command existence and behavior are already exercised by Task 1.

### Steps

1. Document that `just check` and hooks do not modify files, while `just fix` safely rewrites
   Python and Markdown and then checks the full tree. State that secret baseline changes are
   deliberate review actions and type checking is deferred until Python source paths exist.
2. Run `just check-markdown`, then the complete `just check`, expecting exit 0.
3. Commit as `docs: explain development guardrails` after reviewing the documentation diff.

Acceptance: a contributor can select the immutable or mutating workflow without inferring hook
behavior, and every documented command exists.

Rollback: revert the documentation commit if the implementation contract changes before merge.
