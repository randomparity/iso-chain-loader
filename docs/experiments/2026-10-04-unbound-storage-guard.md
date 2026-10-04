# Unbound Storage Controller Guard QEMU Experiment

Date: 2026-10-04

## Result

A QEMU pSeries/POWER9 guest with one blank virtio disk and an attached `megasas` SAS adapter
carrying a second disk ran the launcher from commit `8068b38` (blob `c6bb217`). The launcher printed
`disk-controller: failed unbound=1`, then `disk: failed`, and stopped before any download or
`kexec`. The same guest without the adapter printed `disk: passed`. The launcher from the base
commit `df0fe9f` (blob `f284efc`), given the guest with the adapter, printed `disk: passed`: the gap
issue #46 describes, reproduced. No disk image changed in any run. This is emulator evidence only;
native PowerVM adapters were not run.

## Inputs and environment

- **Host and tools.** An x86_64 Fedora 44 host with QEMU 10.2.2 (`qemu-10.2.2-1.fc44`) using TCG,
  pSeries, POWER9 mode, two CPUs, and 6,656 MiB; zstd 1.5.7; GNU cpio 2.15.
- **Launcher.** A private launcher initramfs built with `dracut-108-8.fc44` for kernel
  `7.2.8-200.fc44.ppc64le` in the `iso-chain-initramfs:44` image, with the script
  `container-prepare-initramfs` runs, for an earlier experiment, decompressed
  with `zstd -dq`, padded to four bytes, and followed by an uncompressed `newc` archive holding
  only `usr/libexec/iso-chain-launch.sh` (mode 0755) from the commit under test. The kernel
  extracts both archives, and the second replaces the launcher. Appending the archive to the
  unmodified zstd image instead failed to unpack (`Initramfs unpacking failed: invalid magic at
  start of compressed archive`).
- **Boot.** QEMU loaded the matching kernel with `-kernel` and that initramfs with `-initrd`. The
  `-append` line was the kernel command line that GRUB passed when the launcher ISO booted the
  same Rocky profile in an earlier run. That ISO was attached as a `scsi-cd` behind
  `virtio-scsi-pci`, and its `/iso-chain/config.json` digest matched the command line's
  `iso_chain.config_sha256`. Networking used QEMU's user-mode network with its default guest
  address, gateway, DNS, and MAC. No source server ran, so a launcher that passed the guard
  stopped at its first download.
- **Disks.** A fresh 8 GiB qcow2 on `virtio-blk` per run. The adapter arm added
  `-device megasas` and a fresh 1 GiB qcow2 as a `scsi-hd` on that adapter's bus.

## Run

| Arm | Launcher | Adapter | Console lines after `memory: passed` |
|---|---|---|---|
| refuse | `8068b38` | `megasas` + disk | `disk-controller: failed unbound=1`, `disk: failed` |
| pass | `8068b38` | none | `disk: passed`, `kernel-http: failed`, `launcher: failed` |
| gap | `df0fe9f` | `megasas` + disk | `disk: passed`, `launcher: failed` |

In every arm the qcow2 SHA-256 digests taken before boot equalled those taken after.

## Evidence

A probe boot before the change used the same kernel and initramfs, with the launcher replaced by a
script that printed sysfs. The guest had `virtio-scsi-pci`, a virtio disk, `megasas` with a disk,
`spapr-vscsi` with a disk, `ich9-ahci`, and `nvme` with a namespace. It showed:

- PCI `class` values `0x030000` (display, no `driver`), `0x0c0330` (USB, driver bound),
  `0x010000` (virtio, bound to `virtio-pci`), `0x010400` (`megasas`, no `driver`), `0x010601`
  (AHCI, bound), and `0x010802` (NVMe, bound);
- VIO `modalias` values `vio:TserialShvterm1` (bound), `vio:TnvramSqemu,spapr-nvram` (no
  `driver`), and `vio:TvscsiSIBM,v-scsi` (bound), and a `vio` bus entry with no readable
  `modalias`;
- `/sys/block` entries `nvme0n1`, `sda` (the VIO vSCSI disk), and `vda`, and none for the
  `megasas` disk.

Console logs, disk digests, and the run scripts stay in private storage.

## Boundary

QEMU's `megasas` stood in for a physical SAS adapter. No Fibre Channel or NPIV adapter was emulated.
Their rules are covered only by the launcher shell test. Whether a real PowerVM adapter's class
and binding match these values belongs to the native PowerVM proof (#28, hmc-mcp#1230).
