# Agent skill for iso-chain tasks

## Problem

Issue #149: an agent must read README, AGENTS.md, guides and ADRs to pick a command, know when
the container or ppc64le path is mandatory, and avoid claiming PowerVM proof from QEMU evidence.
No loadable agent guidance exists.

## Scope

Add `.agents/skills/iso-chain/SKILL.md`. Frontmatter holds `name: iso-chain` and a
`description` naming when to load it (choosing or running an iso-chain task) and when not to
(HMC/LPAR operations, which belong to hmcpctl). The body links to the operator manual and
does not restate guide steps:

- one row per README task-chooser row: the existing command(s) and the owning guide anchor;
- per task, host versus target prerequisites, with macOS using `container-build` and
  `container-prepare-initramfs` and QEMU runs needing a Linux host;
- `iso-chain-report-v1` from the eight `JSON_COMMANDS` with `--json`, dispatched on `version`;
  `iso-chain-media-v1` from `build`, `container-build` and `inspect --result`, dispatched on
  `format` (the media result has no `version` key, so the issue's wording is corrected here);
- privacy rules: `umask 077`, fresh private paths, never paste manifests, logs, captures or
  disk hashes into tool output, issues or pull requests;
- proof rules: report arms run and their limits, QEMU is not PowerVM proof, success only from
  canonical evidence records;
- LPAR installation points to the target-bound media guide and hmcpctl.

README Development and the AGENTS.md source map each gain one reference. No ADR: the path
follows the sibling repository's `.agents/skills/<name>/SKILL.md` convention.

`just check-markdown` lints `.agents/` and reports missing relative paths (MD057) and
cross-file anchors (MD051), shown by a controlled fault with rumdl 0.2.66, so links need no new
harness. A unittest guards frontmatter and command/format-name drift.

### Failure model

- Actors: an agent or contributor on macOS arm64 or x86_64 Linux reading the skill; CI.
- Invariants: the skill never contradicts AGENTS.md safety, privacy or proof rules; it names
  only commands and formats that exist.
- Accepted: guide prose changing under a linked anchor (the guide owns wording).
- Covered elsewhere: hmcpctl skill and LPAR sequence (hmcpctl repo); HMC details
  (target-bound media guide); JSON report extensions (#150).

## Success

1. The skill exists with frontmatter `name: iso-chain` and a non-empty `description`.
2. It maps each of the seven README task-chooser rows to commands and guide anchors.
3. It names every `JSON_COMMANDS` entry, both formats and their discriminators.
4. It carries the privacy, proof and hmcpctl-handoff rules above.
5. README and AGENTS.md each link to the skill.
6. `just check` passes; no runtime dependency or command is added.

## Validation

- Criteria 1, 3, 5: `focused-test`. `AgentSkillTests` asserts the frontmatter, every
  `JSON_COMMANDS` entry and `MEDIA_FORMAT`, and the README/AGENTS.md links. Red before the file
  exists; green: `.venv/bin/python -m unittest -v tests.test_iso_chain.AgentSkillTests`.
- Links and anchors (criterion 2): `focused-test` via `just check-markdown`. Criterion 6:
  `just check` and `just check-tests`.
- Criteria 2, 4 prose: `task-test-not-applicable`; guidance with no executable consumer, where
  a wording snapshot would only restate it. Reviewed in branch review.
