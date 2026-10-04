# Rocky Completion Marker Implementation Plan

Goal: a keyed Rocky ISO boots an installed disk by default only when its unattended install
reached the Kickstart's last `%post`. Spec:
`docs/workflow/specs/2026-10-04-rocky-completion-marker-design.md`; ADR 0021.

Architecture: the Rocky Kickstart template gains a last `%post` that sets `iso_chain_installed=1`
in the installed `grubenv`, and `_grub_config` selects ADR 0020's completion-checking menu for
every manifest carrying login values instead of only Ubuntu user data.

Tech stack: Python 3.14 standard library, Anaconda Kickstart, `unittest`, QEMU pSeries for the
proof.

Expected implementation size: 120–170 changed lines (M) — about 10 Python, 6 Kickstart, 50
unit-test, 25 README and AGENTS.md, and 50–80 experiment-record lines across the two tasks below;
the design artifacts are excluded.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function.
- Markdown is linted by rumdl at line length 100.
- `just check` and `just check-tests` stay green; `.secrets.baseline` covers only `Justfile`, so
  no line-number refresh is needed.
- Private evidence (manifests, keys, logs, captures, disks) stays under
  `~/iso-chain-private/` with `umask 077` and is never committed; the record cites digests only.
- ADR 0018's body is not edited.

## File map

- `scripts/iso_chain.py` — owns the menu text and selection. Change: rename
  `UBUNTU_COMPLETION_MENU` to `COMPLETION_MENU`, update its comment, and select it in
  `_grub_config` when `manifest.login_user is not None`; update the comment above `build`'s
  mixed-keyed refusal. No caller outside `_grub_config` and the tests uses the old name.
- `assets/kickstart/rocky-9.8-unattended.ks` — owns the fixed Rocky install. Change: append the
  marker `%post` before `reboot`.
- `tests/test_iso_chain.py` — `BuildTests` and `RockyKickstartTests` changes below.
- `README.md`, `AGENTS.md` — describe the keyed menu and the Rocky marker.
- `docs/experiments/2026-10-04-rocky-completion-marker.md` — new QEMU record.

## Task 1: Marker and menu selection

Files: modify `scripts/iso_chain.py`, `assets/kickstart/rocky-9.8-unattended.ks`,
`tests/test_iso_chain.py`.

Interfaces: consumes `iso_chain._grub_config(manifest: Manifest, digest: str) -> str`,
`iso_chain._rocky_kickstart(manifest: Manifest) -> bytes`, `iso_chain.ROCKY_KICKSTART: Path`,
and the test fixtures `manifest_data`, `rocky_manifest_data`, `ubuntu_manifest_data`,
`opensuse_manifest_data`, and `KEY`. Provides `iso_chain.COMPLETION_MENU: str` (the former
`UBUNTU_COMPLETION_MENU`, same text).

The two changes ship together: the menu without the marker would stop every keyed Rocky install
from booting its disk.

### Verification

- **Keyed menu.** Mode: focused-test. `BuildTests.test_keyed_menu_requires_the_completion_marker`
  renders keyed Rocky and keyed Ubuntu manifests. Red: the Rocky subtest finds the search 0 times.
  Green: `.venv/bin/python -m unittest -v
  tests.test_iso_chain.BuildTests.test_keyed_menu_requires_the_completion_marker`.
- **Unkeyed menu.** Mode: focused-test. `BuildTests.test_menu_offers_an_installed_disk_by_default`
  gains `opensuse_manifest_data()`; it already asserts no `load_env` for the other unkeyed
  manifests. Green: the same command with that test name.
- **Rocky marker.** Mode: focused-test.
  `RockyKickstartTests.test_ends_with_the_completion_marker_after_every_rendered_step`. Red: the
  marker section is absent. Green: `.venv/bin/python -m unittest -v
  tests.test_iso_chain.RockyKickstartTests`.

### Steps

1. In `BuildTests`, rename `test_keyed_ubuntu_menu_requires_the_completion_marker` to
   `test_keyed_menu_requires_the_completion_marker` and wrap its body in a loop over
   `(rocky_manifest_data(...), "rocky")` and `(ubuntu_manifest_data(...), "ubuntu")`, both with
   `ssh_authorized_keys=[KEY], login_user="core"`, under `self.subTest(profile=selected)`, with
   the existing `search` text and assertions, the `startswith` check using `selected`. Add
   `opensuse_manifest_data()` to the tuple in `test_menu_offers_an_installed_disk_by_default`.
2. In `RockyKickstartTests.test_every_key_round_trips_through_the_kickstart_tokenizer`, change the
   header loop so `%pre` and `%packages` occur once and `%post` twice. Add:

   ```python
   def test_ends_with_the_completion_marker_after_every_rendered_step(self):
       rendered = self.render()
       marker = (
           "%post --erroronfail --interpreter=/bin/sh\n"
           "# ADR 0021: the last change of a finished install; the menu boots only a marked disk.\n"
           "set -eu\n"
           "grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1\n"
           "%end\n"
           "\n"
           "reboot\n"
       )
       self.assertTrue(rendered.endswith(marker))
       self.assertEqual(rendered.count("iso_chain_installed"), 1)
       self.assertLess(rendered.index("ISO_CHAIN_KEYFILE"), rendered.rindex("%post "))
   ```

3. Run the three focused commands; expect the keyed-Rocky subtest and the new Kickstart test to
   fail, and the `%post` count assertion to fail.
4. In the template, replace the final `reboot` line with the `marker` text above (the comment
   line included), so the file ends `%end\n\nreboot\n`.
5. In `scripts/iso_chain.py`, rename the constant, reword its comment to "An unattended install
   creates grubenv before its user exists; the rendered Kickstart's last `%post` or the user
   data's late command then sets this marker, so an interrupted keyed install never becomes the
   default (ADR 0020, ADR 0021).", and in `_grub_config` write
   `menu = INSTALLED_DISK_MENU if manifest.login_user is None else COMPLETION_MENU`. Reword the
   `build` comment's last sentence to "The user data is rendered for the selected profile only,
   so the two cannot share an ISO (ADR 0020)."
6. Run the focused commands; expect OK. Run `just check-tests` and `just check`; expect exit 0.
7. Commit `fix: require the completion marker on keyed Rocky media`.

Rollback: revert the commit; no persisted state changes outside built media.

## Task 2: QEMU proof and documents

Files: create `docs/experiments/2026-10-04-rocky-completion-marker.md`; modify `README.md`,
`AGENTS.md`.

Interfaces: consumes Task 1's committed tree, `install_qemu_commands`, `install-rocky`,
`verify-rocky-install-evidence`, `serve-source`, and the private Rocky mirror and launcher kernel
recorded in `docs/experiments/2026-10-02-rocky-unattended-install.md`.

### Verification

- **QEMU proof.** Mode: task-test-not-applicable; GRUB, Anaconda, and SLOF behaviour on a
  ppc64le guest has no host-side executable observation.
- **Documents.** Mode: task-test-not-applicable; prose with no executable consumer, linted by
  `just check-markdown`.

### Steps

1. Build a fresh launcher initramfs and keyed Rocky ISO from Task 1's commit with a clean tree,
   as the 2026-10-02 Rocky unattended run did, into a fresh private directory.
2. Interrupted arm: fresh 20 GiB disk and fresh `serve-source`. A private Python driver, like
   the Ubuntu record's, imports `scripts.iso_chain`, takes the install command from
   `install_qemu_commands(iso, disk, manifest, pcap, 8192)[0]` plus `-no-reboot`, runs it with
   the console written to a file, polls that file every 5 seconds, and kills QEMU on the first
   `Creating users`; confirm `Running post-installation scripts` is absent. The record names
   this driver and the last console line before the kill. Read
   `/grub2/grubenv` from the `/boot` partition with `guestfish --ro`; expect the file present and
   no `iso_chain_installed`. Boot the same ISO, disk, and NIC; expect no
   `ISO_CHAIN: GRUB installed-disk handoff`, then `disk-blank: failed` and `disk: failed`.
3. Completed arm: `install-rocky` on a fresh disk and server, then
   `verify-rocky-install-evidence`; expect every line `passed` as in the 2026-10-02 record. Read
   the disk's `grubenv` and expect `iso_chain_installed=1`.
4. Write the experiment record with Result, Inputs and environment, Run, Evidence, and Boundary
   sections, citing commit, ISO and Kickstart digests, and the verifier output.
5. README: in the menu paragraph, add that a keyed ISO defines the entry only when that `grubenv`
   holds `iso_chain_installed=1` (ADR 0020, ADR 0021); in the Rocky Kickstart list, replace the
   `reboot` bullet with one saying a last `%post` sets the marker and the Kickstart then reboots.
   Generalise the Ubuntu sentence "A keyed Ubuntu ISO's menu" to "A keyed ISO's menu".
6. AGENTS.md: "a keyed Ubuntu ISO also requires" becomes "a keyed ISO also requires", citing
   ADR 0020 and ADR 0021; ADR count "twenty" to "twenty-one" and "0001–0020" to "0001–0021"; add
   ADR 0021 to Important Files; the Rocky template entry mentions the marker `%post`; add the
   experiment to the Project Overview's proof list.
7. Run `just check`; expect exit 0. Commit `docs: record the Rocky completion-marker QEMU proof`.
