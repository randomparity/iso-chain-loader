# ADR 0018: Boot an Installed Disk by Default and Require a Blank Install Target

## Status

Accepted

## Context

hmcpctl boots a partition with the launcher ISO first in boot order (hmc-mcp ADR 0191), so after an
unattended install the next boot re-enters the launcher. Its GRUB menu offers only installer
profiles, so that boot reinstalls, and nothing stops an installer from overwriting a disk that holds
data. The menu is `powerpc-ieee1275` GRUB from the builder image, which has no `chainloader`, and
after a PowerVM CAS reboot Fedora's GRUB replays an entry from a 1,024-byte buffer. The launcher
runs in a dracut initramfs with `sh`, coreutils `dd`, `sha256sum`, and sysfs, before `kexec`.

## Decision

- **Installed disk.** A device holds an installed disk when GRUB's `search --no-floppy --file`
  finds `grubenv` in one of `/grub2`, `/boot/grub2`, `/grub`, or `/boot/grub`, tried in that order.
  `grub2-install` and `grub-install` create `grubenv` beside the `grub.cfg` they boot. A launcher
  ISO from `build` carries no `grubenv`, so the search cannot select it.
- **Menu.** Every launcher ISO's `grub.cfg` runs that search at top level. When it finds a device,
  it defines the entry `installed disk` (id `installed_disk`), whose body is one `configfile` of
  that directory's `grub.cfg` on that device, and makes it the default. Otherwise the selected
  profile stays the default. `set timeout=5` is unchanged. The id cannot equal a profile name,
  because profile identifiers forbid `_`.
- **Blank disk.** A non-optical disk is a `/sys/block` entry with a `device` link whose name does
  not start with `sr`. A disk is blank when its sysfs size is at least 2,048 sectors and both its
  first and its last 1 MiB read as zero bytes.
- **Guard.** After the memory check and before any media mount, download, or `kexec`, for every
  profile, the launcher counts non-optical disks. Unless exactly one is present and it is blank it
  prints `disk-settle: failed`, `disk-count: failed count=<n>`, or `disk-blank: failed`, then
  `disk: failed`, and exits
  nonzero; it only reads the disk. On success it prints `disk: passed`, which
  `verify-launcher-log` requires between the memory and media evidence.

## Consequences

- An installed disk boots through its own `grub.cfg`, run by the ISO's GRUB, with the ISO still
  attached. Only a Fedora `grub.cfg` has been booted that way; the first Ubuntu and Rocky installs
  (#24, #25) need their own installed-disk boot with the ISO attached. Reinstalling
  needs the operator to zero the disk's first and last MiB first, because the guard refuses it.
- A `grubenv` outside the four paths is not detected. GRUB resolves btrfs paths from the top-level
  tree, so openSUSE Leap's default layout, a btrfs root with no separate `/boot` and snapper
  snapshots, keeps its files under `/@/.snapshots/<n>/snapshot/`. The installer then stays the
  default and the guard refuses the non-blank disk, a visible stop rather than a reinstall.
- Each search probes every device. Under QEMU TCG each miss took about 26 seconds, so a boot with
  no installed disk waits about 100 seconds before the menu; PowerVM timing is unmeasured.
- Two paths to one LUN, as dual-VIOS multipath presents, count as two disks and are refused, and a
  disk whose driver the launcher initramfs lacks is not counted.
- `verify-launcher-log` requires `disk: passed`, so a console log captured before this change
  verifies only with the commit that captured it.
- Whether a replayed installed-disk entry boots after a PowerVM CAS reboot is unproven and belongs
  to the native PowerVM proof (hmc-mcp#1230); every entry, including `installed disk`, stays under
  1,024 bytes.

## Considered & rejected

- **Chainload the disk's PReP partition.** verified: `ls /usr/lib/grub/powerpc-ieee1275` in
  `iso-chain-builder:44` (grub2-ppc64le-modules-2.12-66.fc44) lists no `chainloader.mod`.
- **Detect a PReP partition by type.** judgment: fit; GRUB's `probe` reports partition maps, file
  systems, UUIDs, and labels, not a partition type, and a PReP partition alone does not say which
  configuration to load.
- **Search for `grub.cfg` alone.** verified: the launcher ISO itself carries `/boot/grub/grub.cfg`
  (`xorriso -find /` on a `grub2-mkrescue` ISO from `iso-chain-builder:44`), so `search` can return
  the ISO.
- **Let the launcher kexec the installed kernel.** judgment: complexity; it needs per-distribution
  boot-entry parsing in the initramfs that the installed GRUB already does.
- **Define blank by `blkid` or `wipefs` signatures.** judgment: fit; a disk holding data without a
  known signature would pass, and the guard must fail closed.
- **Zero-check the whole disk.** judgment: cost; reading a multi-terabyte LUN before every install.
- **Zero-check only the first MiB.** judgment: fit; a GPT backup header and md 0.90 or 1.0
  superblocks live at the end of the disk.
- **Do nothing.** judgment: fit; media-first boot would reinstall over every installed partition.
