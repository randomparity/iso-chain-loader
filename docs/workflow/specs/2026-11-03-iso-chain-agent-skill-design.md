# Agent skill for iso-chain tasks

## Problem

Issue #149: an agent must read README, AGENTS.md, guides and ADRs to pick a command, know when
the container or ppc64le path is mandatory, and avoid claiming PowerVM proof from QEMU evidence.

## Scope

Add `.agents/skills/iso-chain/SKILL.md`, the `.agents/skills/<name>/SKILL.md` layout the
sibling hmcpctl repository and Codex-style harnesses discover. Frontmatter holds
`name: iso-chain` and a `description` naming when to load it (choosing or running an iso-chain
task) and when not to (HMC/LPAR operations). Links are relative to the skill file; commands
run from the repository root as `.venv/bin/python scripts/iso_chain.py` or `just`. The body
links to the operator manual instead of restating guide steps:

- per README task-chooser row: the existing command(s) and owning guide anchor;
- per task, host versus target prerequisites: macOS uses `container-build` and
  `container-prepare-initramfs`; QEMU runs need a Linux host;
- `iso-chain-report-v1` from the eight `JSON_COMMANDS` with `--json`, dispatched on `version`;
  `iso-chain-media-v1` (key `format`, no `version`) from one-profile `build`/`container-build`
  and from `inspect --result` on unbound media;
- privacy: `umask 077`, fresh private paths, never paste manifests, logs, captures or disk
  hashes into tool output, issues or pull requests;
- proof: report arms run and their limits, QEMU is not PowerVM proof, success only from
  canonical evidence records;
- LPAR installation points to the target-bound media guide and hmcpctl.

README Development and the AGENTS.md source map each gain one reference. No ADR. `just
check-markdown` lints `.agents/` and reports missing paths (MD057) and cross-file anchors
(MD051), shown by a controlled fault with rumdl 0.2.66, so links need no new harness.

### Failure model

- Actors: an agent or contributor on macOS arm64 or x86_64 Linux; CI.
- Invariants: the skill never contradicts AGENTS.md safety, privacy or proof rules; every
  `scripts/iso_chain.py` subcommand and `just` recipe it names exists.
- Accepted: guide prose changing under a linked anchor (the guide owns wording); a harness that
  does not scan `.agents/skills/` (the path is charter-fixed).
- Covered elsewhere: hmcpctl skill, LPAR sequence and HMC details (hmcpctl); #150 reports.

## Success

1. The skill exists with frontmatter `name: iso-chain` and a non-empty `description`.
2. It maps each of the seven README task-chooser rows to commands and guide anchors.
3. It names every `JSON_COMMANDS` entry, both formats and their discriminators.
4. It carries the privacy, proof and hmcpctl-handoff rules above.
5. README and AGENTS.md each link to the skill.
6. `just check` passes; no runtime dependency or command is added.

## Validation

- Criteria 1, 3, 5 and the command invariant: `focused-test`. `AgentSkillTests` asserts the
  frontmatter, every `JSON_COMMANDS` entry and `MEDIA_FORMAT`, that each named subcommand is a
  `parser()` choice and each `just` recipe is in the Justfile, and the README/AGENTS.md links.
  Red before the file exists; green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.AgentSkillTests`.
- Links and anchors (criterion 2): `focused-test` via `just check-markdown`. Criterion 6:
  `just check` and `just check-tests`. Criteria 2, 4 prose: `task-test-not-applicable`; no
  executable consumer, and a wording snapshot would only restate it.
