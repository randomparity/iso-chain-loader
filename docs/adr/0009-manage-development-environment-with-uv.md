# ADR 0009: Manage the Development Environment with uv

## Status

Accepted

## Context

ADR 0002 locks the development tools in `requirements-dev.lock` and installs them with pip
`--require-hashes`. `just setup` created `.venv` with the host's `python3` and then installed that
lock, which records artifacts for CPython 3.14 on Linux x86_64 only. On macOS the host `python3` is
3.9, so setup fails before installing anything, and the pinned `ruff` and `rumdl` hashes describe
Linux artifacts only.

## Decision

Keep `requirements-dev.in` as the requested-tool list and `requirements-dev.lock` as the pinned
artifact, and move both the interpreter and the installation to uv:

- The lock is regenerated with
  `uv pip compile --universal --generate-hashes --python-version 3.14 requirements-dev.in -o requirements-dev.lock`,
  so one lock carries every supported platform's artifacts and environment markers.
- `just setup` runs `uv venv --allow-existing --python 3.14 .venv`, then
  `uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock`, then
  installs the Git hook exactly as before.
- `.python-version` stays the single declared interpreter version, and `uv` joins `just` as a
  documented host prerequisite. The repository is verified with uv `0.12.12`, which CI pins; the
  lock is regenerated with that release, and a newer host uv is expected to work but is not what the
  pinned lock was produced with.

## Consequences

- One lock installs the identical tool set on macOS arm64 and Linux x86_64 — the two hosts this
  change verifies — and carries macOS x86_64 artifacts as well. `--require-hashes` keeps ADR 0002's
  verification contract unchanged.
- ADR 0002's consequence that the lock carries artifacts "for the declared Linux x86_64 host" no
  longer governs. The rest of ADR 0002, including the check composition it defines, stands.
- `just setup` depends on uv and on uv's ability to provide CPython 3.14, replacing its previous
  dependence on whichever `python3` the host happened to expose.

## Considered & rejected

- **uv project mode: a `[project]` table in `pyproject.toml`, `uv sync`, and `uv.lock`.**
  judgment: this tree ships no importable package, so distribution metadata would describe a
  package that is never built or published.
- **Keep pip and require a Linux development host.** verified: `just setup` on macOS 26 with system
  Python 3.9.6 fails with `ERROR: Could not find a version that satisfies the requirement
  cfgv==3.5.0 (from versions: ...)` before installing any tool.
- **One lock file per platform.** judgment: two pins drift apart, and the check consuming them
  would validate whichever file the current host happened to select.
- **A minimum uv version floor.** judgment: the repository can verify exactly one release, and a
  floor inferred from the flags in use would be a claim no run here supports; naming the verified
  release and pinning it in CI is the honest bound.
