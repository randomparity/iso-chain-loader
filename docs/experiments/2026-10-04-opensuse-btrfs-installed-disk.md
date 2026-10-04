# openSUSE btrfs Installed Disk VM Experiment

Date: 2026-10-04

## Result

With ADR 0024's `set btrfs_relative_path=y` before ADR 0018's search, a QEMU pSeries/POWER9 guest
booted an installed openSUSE Leap 15.6 disk by default through the launcher ISO, with the ISO
first in boot order and still attached. The ISO's GRUB found `/boot/grub2/grubenv` inside the
disk's default subvolume, `@/.snapshots/1/snapshot`, printed `ISO_CHAIN: GRUB installed-disk
handoff`, and ran Leap's own `grub.cfg`, which booted the Leap kernel to a `login:` prompt. The
launcher never ran. An ISO built from the same manifest at the base commit missed the disk, and
its launcher refused it. Two regression arms booted disks whose `grubenv` lies in a btrfs top
level. This is emulator evidence only; native PowerVM was not run.

| Arm | Disk | ISO | Console | Stop |
|---|---|---|---|---|
| a | Leap 15.6 | branch | installed-disk handoff, Leap 6.4.0-150600.21-default | `login:` at 100 s |
| b | Leap 15.6 | base | four search misses, `ISO_CHAIN: GRUB optical handoff` | `disk-blank: failed`, `disk: failed` at 155 s |
| c | Fedora Cloud 44 | branch | installed-disk handoff, Fedora 6.19.10-300.fc44 | `login:` at 105 s |
| d | synthetic btrfs, top level | branch | installed-disk handoff, the disk's marker line | marker at 35 s |

Times are from power-on, with arms a and b, and arms c and d, running two at a time.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 6,656 MiB, in the layout `smoke` uses: virtio disks, the ISO on a SCSI CD with
  `bootindex=1`, and one user-mode virtio NIC with the MAC `52:54:00:12:34:56`. Each arm booted a
  fresh qcow2 overlay or raw image and stopped at its stop line.
- **Manifest.** One unkeyed `opensuse` profile with the Leap 15.6 kernel and initrd pins of the
  [openSUSE installer record](2026-10-02-opensuse-installer.md), QEMU's user-mode addresses, and
  `minimum_memory_mib` 6,400. Its canonical digest was
  `cc1a7460f022c06c877d6ae3fe89f8f8f9bef92814167e7296145e3323d39be0`, volume ID
  `ISO_CHAIN_CC1A7460F022C06C`. No source server ran, because no arm had to download.
- **Launcher builds.** One initramfs, from the `iso-chain-initramfs:44` image at commit
  `882b94c` with a clean tree and the Fedora 7.2.8-200.fc44 kernel, served both ISOs; the
  launcher assets are identical at both commits. The branch ISO was built at `882b94c`, 109,852,672
  bytes, SHA-256 `af3e88265ceea3269417bc931e5cd171d79bd670d60bb0a89e13018e408aab06`. The base ISO
  was built from `git archive` of the fork point `88ab34f`, 109,852,672 bytes, SHA-256
  `f592bb7c712db1c16f18441b4ff2a0eaa07e3792b962f1fe715f492319dfb59e`. Their `grub.cfg` files
  differ only in the `set btrfs_relative_path=y` line. Both container commands ran with
  `--security-opt label=disable`, as in the earlier records.
- **Leap disk.** `openSUSE-Leap-15.6-DVD-ppc64le-Build710.3-Media.iso`, SHA-256
  `6f9504a6710d59ce20f3c16294fe3738be6b08c1b51e1dfd8d6f4a2f6eb8af5e`, matched its `.sha256`, which
  `gpgv` verified with key `AD485664E901B867051AB15F35A2F86E29B700A4`. QEMU booted the DVD's
  `boot/ppc64le/linux` and `initrd` with `install=cd:/`, 8,192 MiB, and a fresh 20 GiB qcow2. A
  private AutoYaST profile had no partitioning section, so YaST used its guided proposal, plus
  the `base` pattern and a root password. The install took 21 minutes. The disk held a PReP
  partition, a btrfs root, and swap. The btrfs has a 64 KiB sector size, which the host kernel
  cannot mount, so `btrfs inspect-internal dump-tree` and `btrfs restore` (btrfs-progs 7.1) read
  it. The default subvolume was `@/.snapshots/1/snapshot`, and it held `/boot/grub2/grubenv` and
  `/boot/grub2/grub.cfg`. Snapper had added a read-only snapshot 2. Leap's `grub.cfg` sets
  `btrfs_relative_path="y"` itself and loads `/boot/vmlinux-6.4.0-150600.21-default`.
- **Regression disks.** Arm c used the Fedora Cloud 44 image of the
  [installed-disk boot record](2026-10-02-installed-disk-boot.md), SHA-256
  `3bea270eba46cdedf3c6c71b20c6ffb03b54131631497a27ff826a497c1dfac6`. Its root partition is
  btrfs with subvolumes `root`, `boot`, `home`, and `var`, and the default subvolume is the top
  level, ID 5 (`guestfish --ro`, libguestfs 1.60.1). Arm d used a 2 GiB image from
  `mkfs.btrfs -r` with no subvolume, holding a 1,024-byte `boot/grub2/grubenv` and a `grub.cfg`
  that prints a marker line.

Raw manifests, the AutoYaST profile, console logs, and disks remain in private storage.

## Arm a detail

The search for `/grub2/grubenv` missed, and the next one, `/boot/grub2/grubenv`, found the disk.
The five-second menu then took the default `installed disk` entry. Leap's `grub.cfg` printed two
GRUB errors before its menu: `read_envblk_file:51:invalid environment block.` and
`read_sblock:303:not a Btrfs filesystem.` Leap's `grubenv` holds `env_block=512+1`, and its
`grub.cfg` reads that block from `${root}`, which is still the ISO's device when the ISO's GRUB
runs that file. The boot continued: its default entry searched for the root file system by UUID,
loaded the kernel and initrd, and Leap printed `Welcome to openSUSE Leap 15.6` and the login
prompt on `hvc0`.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. Whether a replayed `installed disk`
  entry boots after a PowerVM CAS reboot belongs to #28.
- The Leap disk came from the DVD under AutoYaST with YaST's guided proposal, not from a
  launcher-driven install. That an interactive install through the launcher gets the same layout
  is assumed.
- No snapper rollback was run, so a default subvolume other than `@/.snapshots/1/snapshot` was not
  booted.
- Because Leap's `env_block` read fails under the ISO's GRUB, a variable stored only in that
  block is not read on this path.
