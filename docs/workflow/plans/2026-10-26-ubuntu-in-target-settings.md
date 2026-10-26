# Ubuntu In-Target Settings Plan

Goal: apply the selected Ubuntu timezone and locale on the installed disk before the completion
marker ([ADR 0033](../../adr/0033-apply-ubuntu-timezone-and-locale-before-the-completion-marker.md),
[spec](../specs/2026-10-17-reusable-install-presets-design.md#ubuntu-in-target-settings-adr-0033)).

Architecture: `_ubuntu_user_data` in `scripts/iso_chain.py` already loads the fixed template
`assets/autoinstall/ubuntu-26.04.1.json` and sets the opt-in keys. It gains one fixed
`late-commands` entry, inserted at index 0, ahead of the template's `grub-editenv` marker command.
The interim parse-time hold (`UBUNTU_INSTALL_VALUES`) is deleted.

Tech stack: Python 3.14 standard library, `unittest`, `just`.

Expected implementation size: 120–180 changed lines (M) — one renderer edit, the hold removal,
about eight test edits, README, examples and the experiment record from the file map below.

## Global Constraints

- Standard library only in `scripts/`; Ruff and rumdl at 100 columns; `just check` green.
- Manifests without `install` keep byte-identical user data (pinned digest
  `faceb27c42e8b904b8a7d565dfab4d79dd96834512482c56c0909e544b5d50ff` in
  `test_install_defaults_are_explicit_and_legacy_bytes_stay_unchanged`).
- No operator-supplied command, mirror, package, privilege or template change.
- Private inputs, media and evidence stay on the runner under `umask 077`.

## File map

| File | Change |
| --- | --- |
| `scripts/iso_chain.py` | Add `UBUNTU_SETTINGS_SCRIPT`; insert the step in `_ubuntu_user_data`; delete `UBUNTU_INSTALL_VALUES` and its `_install_layer` check |
| `tests/test_iso_chain.py` | `UbuntuUserDataTests`, `OfflineValidationTests`, `UbuntuInstallEvidenceTests`, `ExampleConfigurationTests` edits below |
| `examples/ubuntu-block.json` | Restore `"timezone": "Europe/London", "locale": "en_GB.UTF-8"` |
| `README.md` | Ubuntu preset table back to the full allowlists; describe the step and the proof |
| `docs/experiments/2026-10-26-ubuntu-preset-install.md` | Add run 3 at the new commit; keep runs 1–2 as history |

## Task 1: Render the in-target settings step

Verification:

- Contract: step first, before the marker, carrying the effective values. Mode: focused-test.
  New `UbuntuUserDataTests.test_install_settings_step_precedes_the_completion_marker`. Red:
  `KeyError`/assertion, no step present. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuUserDataTests`.
- Contract: legacy bytes unchanged. Mode: focused-test. Existing digest test stays green.
- Contract: nondefault values accepted again, packages still refused before commands. Mode:
  focused-test. `OfflineValidationTests.test_install_settings_before_commands` and
  `test_ubuntu_settings_refused_before_build_commands`; red while the hold remains. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.OfflineValidationTests`.

Steps:

1. In `UbuntuUserDataTests`, update `test_install_settings_only_change_the_allowed_autoinstall_fields`
   to loop over all five timezones, both locales and both keyboards, expecting
   `late-commands` equal to `[step(timezone, locale), *legacy["late-commands"]]`, where the test
   helper is:

   ```python
   def step(timezone, locale):
       return [
           "curtin",
           "in-target",
           "--target=/target",
           "--",
           "sh",
           "-c",
           iso_chain.UBUNTU_SETTINGS_SCRIPT,
           "sh",
           timezone,
           locale,
       ]
   ```

2. Add the ordering test: render `install_data("ubuntu", timezone="Europe/London",
   locale="en_GB.UTF-8")`; assert `late-commands[0] == step("Europe/London", "en_GB.UTF-8")`,
   `late-commands[-1][4:] == ["grub-editenv", "/boot/grub/grubenv", "set",
   "iso_chain_installed=1"]`, and that the legacy render has no `sh` entry in `late-commands`.
   Pin the script independently of the constant: assert
   `iso_chain.UBUNTU_SETTINGS_SCRIPT == EXPECTED_SCRIPT`, where the test module defines the
   literal `EXPECTED_SCRIPT` with the same six lines as step 4.
3. In `OfflineValidationTests`, drop the `Europe/London`/`en_GB.UTF-8` rows from the refusal
   list and set the invalid condition back to `distribution == "ubuntu" and "packages" in
   settings`. Run the class: expect failures while the hold exists.
4. In `scripts/iso_chain.py`, delete `UBUNTU_INSTALL_VALUES` and the two-line check plus its
   comment in `_install_layer`. Add after `INSTALL_VALUES`:

   ```python
   # ADR 0033: Subiquity leaves these to first-boot cloud-init, after the completion marker.
   UBUNTU_SETTINGS_SCRIPT = (
       "set -eu\n"
       '[ -f "/usr/share/zoneinfo/$1" ]\n'
       'ln -sf "/usr/share/zoneinfo/$1" /etc/localtime\n'
       "printf '%s\\n' \"$1\" >/etc/timezone\n"
       'locale-gen "$2"\n'
       'update-locale "LANG=$2"\n'
   )
   ```

   In `_ubuntu_user_data`, inside `if manifest.install is not None:`, add:

   ```python
   autoinstall["late-commands"].insert(
       0,
       [
           "curtin",
           "in-target",
           "--target=/target",
           "--",
           "sh",
           "-c",
           UBUNTU_SETTINGS_SCRIPT,
           "sh",
           manifest.install.timezone,
           manifest.install.locale,
       ],
   )
   ```

5. Restore `examples/ubuntu-block.json` London/en_GB values; in
   `ExampleConfigurationTests.test_preset_systems` expect `Europe/London` and `en_GB.UTF-8`.
   In `UbuntuInstallEvidenceTests.test_install_manifest_evidence` use
   `install_data("ubuntu", timezone="Europe/London", locale="en_GB.UTF-8", keyboard="gb")` and
   change the locale probe to `en_US.UTF-8`. In
   `test_customized_user_data_size_bound_and_handoff_digest` use the same install data.
6. Run `just fix` then `just check`; expect exit 0 and `launcher shell tests: passed`.
7. Controlled faults, each reverted after observing red: remove the `insert` (ordering and
   allowed-fields tests fail); swap the two positional values (ordering test fails); delete the
   `[ -f` and `ln`/`printf` timezone lines from the constant, and separately the `locale-gen`
   and `update-locale` lines (the pinned-script assertion fails each time).
8. Commit `feat: apply Ubuntu timezone and locale in the target before the marker`.

## Task 2: Matching-build proof and record

Verification:

- Contract: canonical install applies all three settings. Mode: task-test-not-applicable — the
  observation is a QEMU install on the operator runner, not a repository test; its evidence is
  the canonical record verified by `verify-ubuntu-install-evidence` at the build commit.

Steps:

1. Push; check out the exact commit in the runner worktree; confirm `git rev-parse HEAD` equals
   the branch head and the tree is clean.
2. Build launcher media from the run-1 inputs (London, en_GB, gb on system B); confirm
   `/user-data` equals the rendering and `late-commands[0]` is the step.
3. Run `install-ubuntu` with a fresh server, access log, disk and output; verify with
   `verify-ubuntu-install-evidence` at the build commit; expect every line `passed` and filters
   `absent`.
4. Before any inspection boot (the harness boot phase has already run), read the published disk
   with `guestfish --ro`: `/etc/localtime` → `/usr/share/zoneinfo/Europe/London` and that target
   is a regular file, `/etc/timezone` `Europe/London`, `/etc/default/locale` `LANG=en_GB.UTF-8`,
   `/usr/lib/locale` holding the compiled `en_GB.utf8`, `/etc/default/keyboard`
   `XKBLAYOUT="gb"`, the grubenv marker, `/var/log/installer` showing the settings late command
   ran and succeeded before the marker command, and `/var/log/cloud-init.log` showing what the
   harness boot's locale and timezone modules did. Then overlay-boot for the SSH privilege checks
   and `locale -a`; confirm the published disk digest is unchanged.
5. Record run 3 in the experiment record; update README; `just check`; commit
   `docs: record the in-target Ubuntu settings proof`.

Rollback: revert the Task 1 commit; the template and legacy bytes are untouched.
