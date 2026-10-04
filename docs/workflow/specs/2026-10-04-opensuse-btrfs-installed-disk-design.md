# openSUSE btrfs Installed Disk Design

Issue: #49. Decision:
[ADR 0024](../../adr/0024-resolve-installed-disk-paths-in-the-btrfs-default-subvolume.md),
extending ADR 0018.

## Problem

ADR 0018's menu searches `/grub2`, `/boot/grub2`, `/grub`, and `/boot/grub` for `grubenv`. On
openSUSE Leap 15.6's default btrfs layout those paths live inside the default subvolume
`/@/.snapshots/<n>/snapshot`, and GRUB resolves them from the top level, so an installed Leap disk
is never the default. The issue accepts either a probe proven under QEMU or a recorded decision
that openSUSE stays installer-default. A prototype chose the probe: the builder image's GRUB
honours `btrfs_relative_path=y`, and a menu setting it found a `grubenv` inside a default
subvolume and ran that directory's `grub.cfg`.

## Scope

- **Menu.** In `scripts/iso_chain.py`, `INSTALLED_DISK_MENU` begins with
  `set btrfs_relative_path=y`, with its comment citing ADR 0024. `COMPLETION_MENU` derives from it
  and needs no edit. `_grub_config` is unchanged.
- **Tests.** `BuildTests.test_menu_offers_an_installed_disk_by_default` and
  `test_keyed_menu_requires_the_completion_marker` expect the line immediately before the search
  loop.
- **Documents.** ADR 0024; a one-line amendment banner in ADR 0018's Status section; README's menu
  paragraph; AGENTS.md's menu stage, ADR count and list, and proof list; a dated experiment record.
- No change to the launcher, harness, verifiers, assets, or manifest grammar.
- **Fallback.** If the Leap disk does not reach its login prompt through the ISO's GRUB, the menu
  change is reverted, ADR 0024 instead records that openSUSE stays installer-default with that
  evidence, and the experiment record keeps the failed run.

## Failure model

1. **Actors and deployments**
   - A local operator running `build` on a Linux or macOS host with the pinned builder image.
   - hmcpctl booting the ISO first on a PowerVM partition (hmc-mcp ADR 0191).
2. **Invariants and assets at stake**
   - A disk ADR 0018's search found before this change is still found: a non-btrfs disk, or a
     btrfs disk whose default subvolume is the top level.
   - The launcher ISO is never selected, and every menu entry stays under 1,024 bytes (#28).
   - A non-blank disk is never installed over; the launcher guard is unchanged.
3. **Accepted failure classes**
   - A btrfs disk whose default subvolume is not the top level but whose `grubenv` lies only in
     the top level is no longer found; no layout this project installs does that, and the result is
     the guard's visible stop (ADR 0024).
   - An interrupted openSUSE install that wrote `grubenv` boots by default; openSUSE media is
     unkeyed (ADR 0021).
   - The proof's Leap disk comes from the signed DVD under AutoYaST, not a launcher-driven install;
     both use the same YaST proposal, and the launcher's openSUSE handoff is proven separately.
4. **Covered elsewhere**
   - Unattended openSUSE profile: out of scope. CAS-reboot replay on PowerVM: #28.
   - Search latency and multipath disk counts: out of scope.

## Success

1. For the Fedora, Rocky, Ubuntu, and openSUSE test manifests, unkeyed, and the keyed Rocky and
   Ubuntu manifests, `_grub_config` emits `set btrfs_relative_path=y` once, immediately before the
   search loop, and the `installed disk` entry is byte-identical to before.
2. Under QEMU, an installed Leap 15.6 disk in its default layout, with an unkeyed openSUSE ISO
   from this change first in boot order, prints `ISO_CHAIN: GRUB installed-disk handoff`, boots
   the Leap kernel from the disk, and reaches a `login:` prompt with no launcher output.
3. Under QEMU, the same disk with an ISO built from the same manifest at the base commit prints no
   installed-disk handoff, and the launcher prints `disk-blank: failed` and `disk: failed`.
4. Under QEMU, ADR 0018's Fedora Cloud 44 disk with the ISO from this change still prints the
   handoff and reaches a `login:` prompt.

## Validation

- **Menu text (Success 1).** Mode: focused-test. The two `BuildTests` above. Red: the expected
  text, with the new line before the loop, is found 0 times.
- **QEMU proof (Success 2–4).** Mode: task-test-not-applicable; GRUB, SLOF, and the Leap boot are
  observable only by booting a ppc64le guest, recorded in
  `docs/experiments/2026-10-04-opensuse-btrfs-installed-disk.md`.
- **Documents.** Mode: task-test-not-applicable; prose with no executable consumer, held by
  `just check`'s Markdown lint.
