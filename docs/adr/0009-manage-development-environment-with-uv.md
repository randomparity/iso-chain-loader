# ADR 0009: Manage the Development Environment with uv

## Status

Accepted

## Context

ADR 0002 locks the development tools in `requirements-dev.lock` and installs them with pip
`--require-hashes`. `just setup` created `.venv` with the host's `python3` and then installed that
lock. On macOS the host `python3` is 3.9.6, and `cfgv` 3.5.0 publishes no artifact for it, so setup
failed before installing anything.

The lock is not the limitation. Its header names a Linux x86_64 resolution target, but its hash set
already carries the macOS arm64 wheels — `ruff` 0.16.6, `rumdl` 0.2.66, and `pyyaml` 6.0.3 were each
confirmed present — and `uv pip install --require-hashes -r requirements-dev.lock` installs all
eighteen packages on macOS arm64 under CPython 3.14.

## Decision

Keep `requirements-dev.in` and `requirements-dev.lock` unchanged, and move only the interpreter and
the installer to uv:

- `just setup` runs `uv venv --allow-existing --python 3.14 .venv`, then
  `uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock`, then
  installs the Git hook exactly as before.
- `.python-version` keeps declaring the interpreter version, and uv provides CPython 3.14 on a host
  that does not already have it.
- `uv` joins `just` as a documented host prerequisite, verified at release `0.12.12`, which CI pins.
  A missing uv fails setup with an explicit message naming both.

## Consequences

- `just setup` no longer depends on whichever `python3` the host happens to expose, and
  `--allow-existing` keeps a repeated setup safe, which the epic's requirement 1 asks for.
- The lock and its `--require-hashes` contract are untouched, so ADR 0002's check composition and
  pinning story stand. Its sentence that the lock carries platform-specific artifacts "for the
  declared Linux x86_64 host" understates the file: the macOS arm64 artifacts are present and are
  exercised by this change.
- Regenerating the lock stays a separate review action, exactly as before.
- A host without uv cannot provision the environment; the failure is explicit rather than a partial
  install.
- `uv` may fetch a managed CPython 3.14 build from its own interpreter source when the host has none,
  so provisioning can add a network fetch from a third-party distribution channel. Accepted, because
  the alternative is requiring every developer to install CPython 3.14 by hand, and CI pins the uv
  release that performs the fetch. The mitigation for a host that must not fetch is to install
  CPython 3.14 first, which makes `uv venv --python 3.14` use it.

## Considered & rejected

- **Regenerate the lock as a uv `--universal` lock.** verified: the existing lock installs cleanly
  on macOS arm64 (`uv pip install --require-hashes -r requirements-dev.lock`, 18 packages, exit 0,
  2026-09-11) and its hash set contains the macOS arm64 wheels for `ruff` 0.16.6, `rumdl` 0.2.66,
  and `pyyaml` 6.0.3, so the regeneration fixes nothing setup needs while replacing a reviewed,
  hash-pinned artifact wholesale.
- **uv project mode: a `[project]` table in `pyproject.toml`, `uv sync`, and `uv.lock`.**
  judgment: this tree ships no importable package, so distribution metadata would describe a
  package that is never built or published.
- **Keep pip and require a Linux development host.** verified: `just setup` on macOS 26 with system
  Python 3.9.6 fails with `ERROR: Could not find a version that satisfies the requirement
  cfgv==3.5.0 (from versions: ...)` before installing any tool.
- **Vendor a pinned uv binary or the tool wheels into the repository.** judgment: a second,
  unverified distribution channel for tooling that the host package managers already provide.
- **A minimum uv version floor.** judgment: the repository can verify exactly one release, and a
  floor inferred from the flags in use would be a claim no run here supports; naming the verified
  release and pinning it in CI is the honest bound.
