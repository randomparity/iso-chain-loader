# ADR 0024: Resolve Installed-Disk Paths in the btrfs Default Subvolume

## Status

Accepted

## Context

ADR 0018's menu finds an installed disk by searching every device for `grubenv` in `/grub2`,
`/boot/grub2`, `/grub`, or `/boot/grub`. Upstream GRUB resolves btrfs paths from the top-level
subvolume, so openSUSE Leap 15.6's default layout, a btrfs root whose snapper snapshot
`/@/.snapshots/<n>/snapshot` is the default subvolume, holds its `grubenv` where no search looks.
The installer stays the default and the blank-disk guard refuses the disk. A rollback changes `<n>`.

The builder image's GRUB carries openSUSE's btrfs patches: `btrfs.mod` in
`grub2-ppc64le-modules-2.12-66.fc44` holds the `btrfs_relative_path` variable and the
`btrfs-get-default-subvol` command. With `btrfs_relative_path=y`, a btrfs path resolves inside
the default subvolume. Leap's own `grub.cfg` sets the same variable before it loads its kernel.

## Decision

- **Probe.** `INSTALLED_DISK_MENU` sets `btrfs_relative_path=y` at top level before its search,
  so each of the four paths resolves inside a btrfs device's default subvolume. The set of paths,
  their order, and the `installed disk` entry are unchanged, and `COMPLETION_MENU`, derived from
  it, inherits the line. The variable stays set for the rest of the menu, so the keyed menu's
  `load_env` reads the file the search found. The entry's `configfile` opens a new context that
  keeps only exported variables; the patched `btrfs.mod` exports this one itself, and the
  prototype's `configfile` target printed `btrfs_relative_path=y`.
- **Scope.** Every built ISO's `grub.cfg` carries the line. It changes nothing on a file system
  other than btrfs, or on a btrfs device whose default subvolume is the top level.

## Consequences

- An installed openSUSE Leap 15.6 disk in its default layout boots by default through its own
  `grub.cfg`, run by the ISO's GRUB, with the ISO attached. A snapper rollback sets a new default
  subvolume, which the variable resolves into; no run has exercised a rollback.
- A btrfs disk whose default subvolume is not the top level, but whose `grubenv` is only in the
  top level, is no longer found; no distribution layout this project installs does that.
- Every ISO's `grub.cfg`, and so every media digest, changes; manifest digests and volume IDs
  do not.
- The number of searches, and so the per-miss cost ADR 0018 records, is unchanged. The
  `installed disk` entry is unchanged and stays under 1,024 bytes.
- The probe depends on the patched `btrfs.mod`. An upstream GRUB without it ignores the variable,
  and the menu behaves as ADR 0018 alone describes.
- openSUSE media carries no login values (ADR 0017 refuses them), so an interrupted openSUSE
  install that wrote `grubenv` boots by default, as ADR 0021 records for every unkeyed ISO.

## Considered & rejected

- **Search the first snapshot's path, `/@/.snapshots/1/snapshot/boot/grub2`.** judgment: fit; it
  misses a rolled-back disk and adds a search, about 26 seconds per miss under TCG.
- **Find the subvolume with `btrfs-get-default-subvol` per device.** judgment: complexity; the
  menu would iterate devices and build paths itself, while the variable gives the same
  resolution to the existing search, `configfile`, and `load_env`.
- **Keep openSUSE installer-default and record why.** verified: a QEMU pSeries boot of a GRUB
  menu that set the variable before ADR 0018's search found `/boot/grub2/grubenv` inside a btrfs
  default subvolume `@/.snapshots/1/snapshot` (built by `mkfs.btrfs` from btrfs-progs 7.1) and ran
  that `grub.cfg`. The
  [openSUSE btrfs installed-disk experiment](../experiments/2026-10-04-opensuse-btrfs-installed-disk.md)
  booted an installed Leap 15.6 disk the same way.
- **Do nothing.** judgment: fit; an installed Leap disk would never boot by default, so media-first
  boot always stops at the guard.

Specification:
[openSUSE btrfs installed disk](../workflow/specs/2026-10-04-opensuse-btrfs-installed-disk-design.md).
