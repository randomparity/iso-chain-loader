# RHEL Unattended Install Implementation Plan

**Goal:** `build` and `container-build` accept `ssh_authorized_keys` and `login_user` with `rhel`
profiles, derive and stage a Kickstart, bind it on the kernel command line, and the launcher
accepts it.

**Architecture:** The Rocky renderer takes the template by distribution; `rhel` uses a copy of
Rocky's template with its own volume-group name. The launcher routes RHEL's argument check to
Rocky's, which already bounds a Kickstart (ADR 0031).

**Tech stack:** Python 3.14, stdlib only; POSIX `sh` launcher; stdlib `unittest`; Bash shell test.

Expected implementation size: 250–400 changed lines (L) — about 25 Python, 60 template lines
(copy), 5 shell, 130 Python tests, 40 shell tests, 50 docs lines, counted from the tasks below.

## Global Constraints

- Python 3.14, standard library only in `scripts/`; ruff line length 100; rumdl 100 columns.
- Validation raises `ValidationError` naming fields, never values; it runs before any subprocess
  (`run.assert_not_called()`).
- Rocky, Fedora, Ubuntu and openSUSE manifests, Kickstarts, kernel arguments and launcher output
  stay byte-identical; keyless RHEL arguments stay byte-identical.
- Guardrails: `just check-tests` while iterating; `just check` before each commit. Refresh
  `.secrets.baseline` line numbers if a covered file shifts (`just check-secrets` shows drift).
- Spec: `docs/workflow/specs/2026-10-16-rhel-unattended-install-design.md`; ADR 0031.

## File map

| File | Change |
|---|---|
| `assets/kickstart/rhel-unattended.ks` | New: Rocky's template, RHEL header comment, `volgroup rhel`, `--vgname=rhel` |
| `scripts/iso_chain.py` | `RHEL_KICKSTART`; `_rocky_kickstart` becomes `_kickstart(manifest, distribution)`; `_profile_kickstart`; `_configuration_manifest` |
| `assets/dracut/iso-chain-launch.sh` | Delete `valid_rhel_arguments`; route `rhel:` cases to `valid_rocky_arguments` |
| `tests/test_iso_chain.py` | Rename call sites; new `RhelKickstartTests`; login-rule test; keyed RHEL build tests |
| `tests/test_iso_chain_launch.sh` | RHEL Kickstart arms flip from refusal to acceptance |
| `README.md`, `AGENTS.md` | Unattended RHEL profile and login rule |

Callers of `_rocky_kickstart`: `_profile_kickstart` (line ~1019), `_configuration_manifest`
(~1345), `tests/test_iso_chain.py` (~1326, ~1927). All migrate to `_kickstart`; no old name stays.
`ROCKY_KICKSTART` stays and the offline-validation test (~7371) keeps patching it.

## Task 1: Renderer, template and login rule

**Files:** create `assets/kickstart/rhel-unattended.ks`; modify `scripts/iso_chain.py`,
`tests/test_iso_chain.py`.

**Interfaces:** consumes `ROCKY_KICKSTART`, `Manifest`, `_manifest_error`. Provides
`RHEL_KICKSTART: Path` and `_kickstart(manifest: Manifest, distribution: str) -> bytes`
(`distribution` is `"rocky"` or `"rhel"`).

Verification:

- Contract: RHEL render equals Rocky render apart from the header and volume group. Mode:
  focused-test. `RhelKickstartTests.test_matches_rockys_rendering_apart_from_header_and_volume_group`.
  Red: `AttributeError: module 'scripts.iso_chain' has no attribute '_kickstart'`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.RhelKickstartTests`.
- Contract: unrenderable RHEL values refused without echo. Mode: focused-test.
  `RhelKickstartTests.test_refuses_unrenderable_values_without_echoing_them` (key starting `-`,
  `lpar` ending `-`; message names `rhel`). Red: same `AttributeError`.
- Contract: login rule. Mode: focused-test.
  `BuildTests.test_refuses_login_values_unless_every_profile_is_rocky_rhel_or_ubuntu_before_grub`
  (rename of the existing test; Fedora, openSUSE, Rocky+Ubuntu, Ubuntu+Fedora, Rocky+Fedora
  refused with `every profile must be rocky or rhel, or every profile ubuntu`; the RHEL entry
  removed). Red: RHEL manifest is still refused / regex mismatch. Green: command
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Contract: Rocky bytes unchanged. Mode: focused-test. Existing `RockyKickstartTests` and
  `test_rocky_login_values_stage_and_bind_a_derived_kickstart` stay green after the rename.

Steps:

1. Copy the Rocky template to `assets/kickstart/rhel-unattended.ks`. Replace its first two
   comment lines with a RHEL 9.0 to 10.2 header citing ADR 0031 (each line at most 100 columns),
   `volgroup rocky` with `volgroup rhel`, and `--vgname=rocky` with `--vgname=rhel`.
2. Write the three `RhelKickstartTests` tests and the renamed login-rule test; add
   `RhelKickstartTests.render(distribution_factory, ...)` using `rhel_manifest_data`. Run them and
   confirm the red results above.
3. In `scripts/iso_chain.py` add
   `RHEL_KICKSTART = REPOSITORY_ROOT / "assets/kickstart/rhel-unattended.ks"` beside
   `ROCKY_KICKSTART`.
4. Rename `_rocky_kickstart(manifest)` to `_kickstart(manifest, distribution)`: the template is
   `RHEL_KICKSTART if distribution == "rhel" else ROCKY_KICKSTART`; the lpar error reads
   `f"must not end in - for an unattended {distribution} install"`; the docstring cites ADR 0019
   and 0031. In `_profile_kickstart` test `profile.distribution not in ("rocky", "rhel")` and call
   `_kickstart(manifest, profile.distribution)`.
5. In `_configuration_manifest` allow `distributions <= {"rocky", "rhel"}` (non-empty) or
   `{"ubuntu"}`; message `login_user and ssh_authorized_keys: every profile must be rocky or
   rhel, or every profile ubuntu (ADR 0017, ADR 0019, ADR 0020, ADR 0031)`; render once per
   distribution in the set when it is not Ubuntu. Update the comment above it.
6. Rename call sites in `tests/test_iso_chain.py` (~1326, ~1927).
7. Run `.venv/bin/python -m unittest -v tests.test_iso_chain.RhelKickstartTests
   tests.test_iso_chain.RockyKickstartTests tests.test_iso_chain.BuildTests`; expect all pass.
8. Commit: `feat: derive an unattended RHEL Kickstart from the manifest`.

## Task 2: Keyed RHEL media, staging and menu

**Files:** modify `tests/test_iso_chain.py`.

**Interfaces:** consumes Task 1's `_kickstart`; provides tests only.

Verification:

- Contract: keyed RHEL build stages `/profiles/rhel/ks.cfg`, binds path/size/SHA-256 in
  `grub.cfg`, and keyless RHEL stays unchanged. Mode: focused-test.
  `BuildTests.test_rhel_login_values_stage_and_bind_a_derived_kickstart` (mirrors the Rocky
  test). Red before Task 1: manifest refused. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Contract: mixed keyed Rocky+RHEL media stages one Kickstart per profile.
  Mode: focused-test. `BuildTests.test_mixed_rocky_and_rhel_login_values_stage_each_kickstart`;
  the two staged files differ only in header and volume group.
- Contract: completion menu. Mode: focused-test. Extend
  `test_keyed_menu_requires_the_completion_marker` factories with `rhel_manifest_data`.
- Contract: launcher-log derivation. Mode: focused-test.
  `RHELEvidenceTests.test_keyed_rhel_requires_the_media_kickstart_beside_both_repositories`,
  mirroring `test_unattended_rocky_requires_media_kickstart_and_repository_evidence`: a keyed
  RHEL manifest passes `verify_launcher_log` with `inst.ks=cdrom:LABEL=...`, `inst.repo` and
  `inst.addrepo` plus `media: passed`, and is refused when the Kickstart is missing.

Steps:

1. Add the tests above; they depend on Task 1 and so are expected green at once. Prove they
   bite: temporarily make `_profile_kickstart` return `None` for `rhel`, confirm red, restore.
2. Run `.venv/bin/python -m unittest -v tests.test_iso_chain`; expect all pass.
3. Commit: `test: cover keyed RHEL media staging, menu and launcher evidence`.

## Task 3: Launcher

**Files:** modify `assets/dracut/iso-chain-launch.sh`, `tests/test_iso_chain_launch.sh`.

**Interfaces:** consumes `valid_rocky_arguments`; nothing else relies on `valid_rhel_arguments`
(grep: only the `case` at line 470 calls it).

Verification:

- Contract: RHEL with a Kickstart accepted; `inst.ks=cdrom:LABEL=...` precedes `inst.repo=` and
  `inst.addrepo=`; media mounted; workspace cleaned. Mode: focused-test.
  `bash tests/test_iso_chain_launch.sh`. Red: the flipped `RHEL with a Kickstart` arm fails
  because the launcher still refuses. Green: output ends `launcher shell tests: passed`.
- Contract: partial, oversized, digest-mismatched RHEL Kickstart refused with no download. Mode:
  focused-test, same file.

Steps:

1. In the shell test replace the `RHEL with a Kickstart` refusal with an `rhel_kickstart`
   acceptance block copied from the Rocky one (expected args derived from `expected_rhel_args`
   with `inst.ks=` inserted before `inst.repo=`), and add partial, oversized and media-digest
   refusals. Keep the partial-Kickstart refusal. Run; confirm the red result.
2. Delete `valid_rhel_arguments` and change the case line to
   `rocky:9.8 | rhel:9.[0-8] | rhel:10.[0-2]` only if the two share a handler; otherwise keep two
   lines both calling `valid_rocky_arguments`. Update the comment above `valid_rocky_arguments`.
3. Run `bash tests/test_iso_chain_launch.sh`; expect `launcher shell tests: passed`.
4. Commit: `feat: accept a media Kickstart for RHEL profiles in the launcher`.

## Task 4: Documents

**Files:** modify `README.md`, `AGENTS.md`, `.secrets.baseline` (line numbers only).

Verification:

- Contract: prose and baseline numbers. Mode: task-test-not-applicable; README and AGENTS prose
  has no executable consumer, held by `just check`'s Markdown lint, and `.secrets.baseline` drift
  is held by `just check-secrets`.

Steps:

1. README intro ("Red Hat Enterprise Linux 9.0 through 10.2 text installer, interactive") becomes
   "interactive or, with SSH keys and a login user, unattended"; AGENTS.md's profile
   line "RHEL 9.0 to 10.2 (interactive, ADR 0028)" becomes "(interactive or unattended, ADR 0028,
   ADR 0031)".
   README RHEL section: replace the sentence refusing login values with the unattended
   description (Kickstart from `assets/kickstart/rhel-unattended.ks`, ADR 0031, no `repo` line,
   `inst.addrepo` unchanged, install harness tracked in #97). Update the login-values
   paragraph to "every profile is Rocky or RHEL, or every profile is Ubuntu".
2. AGENTS.md: login bullet (derived Rocky/RHEL Kickstart), Kickstart row in the source map, and
   ADR 0031 link.
3. Run `just check`; if `check-secrets` reports shifted line numbers, refresh them with the
   command it names. Expect a clean `just check`.
4. Commit: `docs: describe the unattended RHEL profile`.

## Deferrals

- Install harness and install evidence for RHEL: owner #97.

## Final verification

`just check-tests` then `just check`; both exit 0. Not run: Anaconda install on RHEL (ADR 0031).
