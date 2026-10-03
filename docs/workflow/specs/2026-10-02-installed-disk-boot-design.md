# Installed-Disk Boot and Blank-Target Guard Design

Issue: #40. Decision: [ADR 0018](../../adr/0018-boot-installed-disk-and-require-blank-target.md).

## Problem

hmcpctl boots a partition with the launcher ISO first, so after an install the launcher's GRUB menu
defaults to an installer again, and no check stops an installer from writing over a disk that holds
data. Ubuntu (#24) and Rocky (#25) unattended installs need both guarantees first.

## Scope

In scope, for every profile (`fedora`, `rocky`, `ubuntu`, `opensuse`) that `build` accepts:

- `_grub_config` emits ADR 0018's installed-disk search and conditional `installed disk` entry.
- `iso-chain-launch.sh` runs ADR 0018's guard after the memory check and before any launch path.
- `DRACUT_TOOLS` installs `/usr/bin/dd`, which the guard reads the disk with.
- `verify_launcher_log` requires `disk: passed` after the memory evidence and before `media: passed`
  or `artifacts: passed`.
- README and AGENTS.md describe the menu entry, the guard, and the new marker.
- A QEMU experiment record under `docs/experiments/`.

Out of scope (owners): detaching media or reordering boot after install (hmc-mcp#1228); native
PowerVM proof, including CAS-reboot replay of the installed entry (hmc-mcp#1230); installer-side
disk selection in Kickstart or autoinstall (#24, #25).

No ownership transition: GRUB menu policy stays in `_grub_config`, the guard joins the launcher's
existing pre-`kexec` checks, and no caller migrates.

### GRUB configuration shape

After the `iso_chain_args_<n>` variables and before the profile entries:

```text
for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do
    if [ -z "$iso_chain_disk" ]; then
        if search --no-floppy --file --set=iso_chain_disk $iso_chain_directory/grubenv; then
            set iso_chain_config=$iso_chain_directory/grub.cfg
        fi
    fi
done
if [ -n "$iso_chain_disk" ]; then
    set default=installed_disk
    menuentry 'installed disk' --id installed_disk {
        configfile ($iso_chain_disk)$iso_chain_config
    }
fi
```

A QEMU spike on an x86_64 Fedora 44 host booted this shape with the Fedora 44 Cloud ppc64le image
attached and reached that image's login prompt through its own GRUB menu.

### Guard shape

`check_disk` settles udev, then counts `$ISO_CHAIN_SYS_BLOCK/*` (default `/sys/block`) entries with
a `device` link and a name not starting `sr`. For the one disk it reads `size`, requires a decimal
of at least 2048, and compares the SHA-256 of
`dd if=$ISO_CHAIN_DEV_DIR/<name> bs=512 skip=<s> count=2048` (default `/dev`) for `s = 0` and
`s = size - 2048` with the digest of 1 MiB of zero bytes. Any read or digest failure produces a
digest mismatch, so it refuses rather than passes. Reason lines: `disk-settle: failed`,
`disk-count: failed count=<n>`, `disk-blank: failed`, then `disk: failed`.

## Failure model

1. Actors and deployments
   - An operator or hmcpctl booting launcher media on QEMU pSeries or a PowerVM LPAR.
   - A developer running the unit and shell tests on Linux or macOS.
2. Invariants and assets at stake
   - Data on a non-blank disk: the launcher hands off only when exactly one disk is visible in
     `/sys/block` after `udevadm settle`, and that disk is blank.
   - An installed system: with the ISO attached it boots by default rather than reinstalling.
   - Every menu entry stays under the 1,024-byte CAS-replay buffer.
3. Accepted failure classes
   - A `grubenv` outside the four searched paths, as in openSUSE Leap's default btrfs snapshot
     layout, is not detected; the installer default then meets the guard's refusal (ADR 0018).
   - A detected `grubenv` without a loadable `grub.cfg` stops at GRUB with an error.
   - Multipath LUNs count twice and are refused; disks without a launcher driver are not counted.
   - A disk appearing after `udevadm settle` is not counted.
   - Each GRUB search costs about 26 seconds under QEMU TCG.
4. Covered elsewhere
   - Native PowerVM timing and CAS replay: hmc-mcp#1230.
   - Media detach after install: hmc-mcp#1228.
   - Which disk an installer writes: #24, #25, and the Fedora Kickstart's `--ondisk=vda`.

## Success

1. For a manifest with any set of profiles, `_grub_config` emits the search before the profile
   entries, the `installed disk` entry only inside the conditional, and every entry is under 1,024
   bytes; the profile default line is unchanged.
2. The launcher refuses, before any `mount`, `curl`, or `kexec` call and with no disk write, for
   zero disks, two disks, a non-blank first MiB, a non-blank last MiB, and a disk under 2,048
   sectors; optical `sr*` and link-less virtual devices are not counted.
3. With one blank disk the launcher prints `disk: passed` and continues to the existing handoff.
4. `verify_launcher_log` rejects a log without `disk: passed` or with it out of order.
5. A QEMU pSeries record shows the installed-disk default with the ISO attached and the refusal on a
   non-blank disk, labelled as emulator evidence.

## Validation

- Success 1: focused-test, `BuildTests` GRUB cases in `tests/test_iso_chain.py`.
- Success 2 and 3: focused-test, disk cases in `tests/test_iso_chain_launch.sh`.
- Success 4: focused-test, launcher-log cases in `tests/test_iso_chain.py`.
- `DRACUT_TOOLS` gains `dd`: focused-test, `PrepareTests` dracut-command assertion.
- Success 5: task-test-not-applicable; it is a QEMU boot with emulated firmware, which the unit
  suites cannot run, recorded in `docs/experiments/2026-10-02-installed-disk-boot.md`.
- README and AGENTS.md: task-test-not-applicable; prose with no executable consumer.
