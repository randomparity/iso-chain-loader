# ADR 0021: Require a Completion Marker on Every Keyed ISO

## Status

Accepted

> **Unkeyed media decided by [ADR 0025](0025-keep-the-grubenv-only-rule-on-unkeyed-media.md)**
> (2026-10-04): the last Consequences bullet below is accepted as stated, with its rationale.

## Context

ADR 0018 makes any disk holding a `grubenv` in one of four directories the launcher menu's default.
ADR 0020 found that subiquity writes `grubenv` before it creates the user, so a keyed Ubuntu ISO's
menu also requires `iso_chain_installed=1` in that `grubenv`, set by the user data's last late
command. Anaconda has the same order: the unattended Rocky install (ADR 0019) prints `Installing
boot loader` before `Creating users` and `Running post-installation scripts`, and the installed
disk's `/boot/grub2/grubenv` exists after the bootloader step. A keyed Rocky ISO still selects
ADR 0018's plain menu, so an install interrupted between those steps leaves a disk the launcher
boots by default, with no login user or key. Fedora media carries the operator's own Kickstart,
which `build` neither renders nor edits.

## Decision

- **Scope.** A manifest that carries `ssh_authorized_keys` and `login_user` is keyed, and its
  install answers are rendered by `build`: all-Rocky media from ADR 0019's Kickstart, all-Ubuntu
  media from ADR 0020's user data. Every keyed ISO requires the completion marker. An ISO without
  login values keeps ADR 0018's `grubenv`-only rule, whatever its profiles.
- **Menu.** `_grub_config` selects the completion-checking menu, ADR 0020's
  `UBUNTU_COMPLETION_MENU` renamed `COMPLETION_MENU`, whenever the manifest is keyed. The menu text
  is unchanged, so a keyed Ubuntu ISO's digest is unchanged. This widens ADR 0020's Completion
  marker decision from all-Ubuntu media to every keyed ISO, and replaces ADR 0019's End rule that
  keyed Rocky media boots its disk through ADR 0018's plain menu.
- **Rocky marker.** `assets/kickstart/rocky-9.8-unattended.ks` ends with a second `%post
  --erroronfail` section, after the rendered network `%post`, that runs `grub2-editenv
  /boot/grub2/grubenv set iso_chain_installed=1` in the installed system. Anaconda runs `%post`
  scripts after it installs the bootloader, writes the network configuration, and creates the
  user and keys, and runs them in file order, so the marker is the install's last change before
  `reboot`. A failure stops the install visibly instead of leaving an unmarked disk.

## Consequences

- An unattended Rocky install interrupted before its last `%post` leaves a non-blank disk without
  the marker: the keyed ISO's menu keeps the Rocky entry as the default, and the launcher's
  blank-disk guard refuses the disk.
- Every keyed Rocky ISO's Kickstart, and so its media digest, changes.
- A disk installed from keyed Rocky media built before this decision lacks the marker, so a
  keyed ISO built from this revision boots the installer entry, which refuses the disk. Running
  `grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1` on that system admits it. Only
  emulator runs used such media.
- `grub2-editenv set` keeps other variables, so Rocky's later kernel updates and boot-success
  writes preserve the marker.
- `build` still refuses a keyed manifest that mixes Rocky and Ubuntu profiles: the user data is
  rendered for the selected profile only (ADR 0020).
- An unkeyed Fedora, Rocky, Ubuntu, or openSUSE ISO still boots an interrupted install's disk by
  default when the installer wrote `grubenv`.

## Considered & rejected

- **Select the completion menu per profile, for a Rocky profile with a rendered Kickstart or an
  Ubuntu profile with user data.** judgment: complexity; keyed media is already all-Rocky or
  all-Ubuntu, and both now write the marker, so the manifest's login values decide alone.
- **Require the marker on every ISO, including unkeyed media.** judgment: fit; the operator's
  Fedora Kickstart and the interactive installers are not rendered by `build`, so the ISO cannot
  promise the marker, and every such installed disk would stop booting by default.
- **Write the marker from the rendered network `%post`.** judgment: fit; the fixed parts of the
  install belong in the template (ADR 0019), and a separate last section keeps the marker after
  every rendered step.
- **Use `%post --nochroot` against `/mnt/sysimage`.** judgment: complexity; the chrooted
  `grub2-editenv` is the installed system's own tool and path.
- **Use Anaconda's `%onerror` or an `%anaconda` hook.** judgment: fit; neither runs only after
  a successful install.
- **Do nothing.** verified: the unattended Rocky install log of
  [the Rocky unattended experiment](../experiments/2026-10-02-rocky-unattended-install.md) prints
  `Installing boot loader` before `Creating users`, and that run's disk held `/grub2/grubenv` on
  its `/boot` partition (`guestfish --ro`, libguestfs 1.60.1, 2026-10-04), so an interruption in
  between leaves a default-bootable disk without its user.

Specification: [Rocky completion marker](../workflow/specs/2026-10-04-rocky-completion-marker-design.md).
