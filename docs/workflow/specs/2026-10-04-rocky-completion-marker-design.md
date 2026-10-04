# Rocky Completion Marker Design

Issue: #45. Decision: [ADR 0021](../../adr/0021-require-a-completion-marker-on-keyed-media.md),
extending ADR 0018, 0019, and 0020.

## Problem

A keyed Rocky ISO uses ADR 0018's menu, which makes any disk with a `grubenv` the default. Anaconda
writes `/boot/grub2/grubenv` when it installs the bootloader, before it creates the login user and
runs `%post`, so an interrupted unattended Rocky install leaves a disk the launcher boots by
default. Keyed Ubuntu media closed this gap with `iso_chain_installed=1` (ADR 0020).

## Scope

- **Menu selection.** In `scripts/iso_chain.py`, rename `UBUNTU_COMPLETION_MENU` to
  `COMPLETION_MENU`, unchanged in text, and select it in `_grub_config` when
  `manifest.login_user is not None`, replacing the `_profile_user_data(...)` test. Every other
  manifest keeps `INSTALLED_DISK_MENU`. Update `build`'s comment on mixed keyed manifests to say
  the user data is rendered for the selected profile only; the refusal itself is unchanged.
- **Rocky marker.** Append to `assets/kickstart/rocky-9.8-unattended.ks`, between the `%pre`
  section's `%end` and `reboot`, a section
  `%post --erroronfail --interpreter=/bin/sh` / `set -eu` /
  `grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1` / `%end`, with one comment line
  citing ADR 0021. The rendered Kickstart then holds two `%post` sections: the rendered network
  section first, the marker section last.
- **Documents.** README's menu and Rocky Kickstart paragraphs, AGENTS.md's menu stage, ADR count,
  ADR list, and Rocky template line, and a dated experiment record.
- No change to the launcher, harness, verifiers, Fedora or openSUSE assets, or ADR 0018's body.

## Failure model

1. **Actors and deployments**
   - A local operator running `build`, `install-rocky`, and the verifiers on a Linux or macOS host.
   - hmcpctl booting keyed media on a PowerVM partition, ISO first (hmc-mcp ADR 0191).
2. **Invariants and assets at stake**
   - The keyed ISO's default entry never boots a disk whose install did not reach its last `%post`.
   - A finished keyed install still boots its disk by default with the ISO attached.
   - Unkeyed media and keyed Ubuntu media keep byte-identical `grub.cfg`.
3. **Accepted failure classes**
   - Disks from keyed Rocky media built before this change lose the default; emulator-only, with
     the `grub2-editenv` remedy in ADR 0021.
   - An install interrupted inside the marker `%post`, after `grub2-editenv` rewrote the file,
     is marked; the command is the section's last action.
   - Unkeyed media keeps ADR 0018's `grubenv`-only rule (ADR 0021 Scope).
4. **Covered elsewhere**
   - Fedora marker or Kickstart changes: out of scope by operator decision.
   - openSUSE btrfs `grubenv` detection: #49. Rocky administrative access: #48.
   - Blank-disk driver binding: #46. Native PowerVM proof: #28 and #6.

## Success

1. A keyed Rocky or keyed Ubuntu manifest's `grub.cfg` contains the completion-checking search
   exactly once; an unkeyed Fedora, Rocky, Ubuntu, or openSUSE manifest's contains no `load_env`.
2. The rendered keyed Rocky Kickstart's last `%post` section is exactly the marker section, it
   follows the network `%post`, and the file still ends in `reboot`.
3. Under QEMU, a keyed Rocky install killed after `Creating users` and before `Running
   post-installation scripts` leaves `/grub2/grubenv` on the `/boot` partition without
   `iso_chain_installed`; the next boot with the same ISO prints no installed-disk handoff and the
   launcher prints `disk-blank: failed` and `disk: failed`.
4. Under QEMU, an uninterrupted keyed Rocky install sets the marker, boots the disk through
   `ISO_CHAIN: GRUB installed-disk handoff` to the login prompt, and
   `verify-rocky-install-evidence` passes.

## Validation

- **Menu selection (Success 1).** Mode: focused-test.
  `BuildTests.test_keyed_menu_requires_the_completion_marker` over keyed Rocky and keyed Ubuntu
  manifests, and the existing
  `test_menu_offers_an_installed_disk_by_default` over the unkeyed ones plus openSUSE. Red: the
  keyed Rocky subtest finds no `load_env`.
- **Rocky marker (Success 2).** Mode: focused-test.
  `RockyKickstartTests.test_ends_with_the_completion_marker_after_every_rendered_step`. Red: no
  marker section.
- **QEMU proof (Success 3, 4).** Mode: task-test-not-applicable; GRUB, Anaconda, and SLOF
  behaviour is observable only by booting a ppc64le guest, recorded in
  `docs/experiments/2026-10-04-rocky-completion-marker.md`.
- **Documents.** Mode: task-test-not-applicable; prose with no executable consumer, held by
  `just check`'s Markdown lint.
