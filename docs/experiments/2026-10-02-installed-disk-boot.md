# Installed-Disk Boot and Blank-Disk Guard VM Experiment

Date: 2026-10-02

## Result

With the launcher ISO first in boot order, QEMU pSeries/POWER9 guests showed both halves of
ADR 0018:

- **Installed disk.** With a Fedora 44 Cloud ppc64le disk attached, the launcher's GRUB found
  `/boot/grub2/grubenv` on `ieee1275/disk,gpt2`, defaulted to `installed disk`, and after the
  five-second countdown loaded the disk's own `grub.cfg`. That menu booted
  `vmlinuz-6.19.10-300.fc44.ppc64le` from the disk to a login prompt. The launcher never ran.
- **Guard.** With no installed disk, GRUB kept the `rocky` profile as default and the launcher ran:

| Disks attached | Launcher lines after `memory: passed` | `kexec` | Disk hashes |
|---|---|---|---|
| one blank 8 GiB disk | `disk: passed`, then `kernel-http: failed` | none | unchanged |
| one 8 GiB disk with 4 KiB of `0x5a` at offset 0 | `disk-blank: failed`, `disk: failed` | none | unchanged |
| two blank 8 GiB disks | `disk-count: failed count=2`, `disk: failed` | none | unchanged |
| no disk | `disk-count: failed count=0`, `disk: failed` | none | none attached |

The blank arm's `kernel-http: failed` is expected: no source server ran, because the arm only had to
reach the guard. Native PowerVM was not run, so this proves the emulator path only.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 6,656 MiB, in the layout `smoke` uses: virtio disks, the ISO on a SCSI CD with
  `bootindex=1`, and one user-mode virtio NIC with QEMU's default MAC `52:54:00:12:34:56`.
- **Launcher build.** Commit `f4ace98`, with the launcher kernel Fedora 7.2.8-200.fc44 and an
  initramfs from the `iso-chain-initramfs:44` image, whose launcher script was byte-compared with
  the commit's. The ISO was 109,852,672 bytes, SHA-256
  `286bfed2ddbf0235b88c382a062244ece062115c2452b0d98729873c9b930f06`, volume ID
  `ISO_CHAIN_6716FC22A236FBD2`. `xorriso -find / -name 'grubenv*'` on it found nothing.
- **Manifest.** The Rocky 9.8 sweep manifest from the Rocky record, with canonical digest
  `6716fc22a236fbd2dcafb61d4f63fccf265690d6b087fe7bb943ed7aa3e3e789`.
- **Installed disk.** A qcow2 overlay over
  `Fedora-Cloud-Base-Generic-44-1.7.ppc64le.qcow2` from `dl.fedoraproject.org`, SHA-256
  `3bea270eba46cdedf3c6c71b20c6ffb03b54131631497a27ff826a497c1dfac6`. Fedora's image build, not
  this launcher, installed it.
- **Build-host deviations.** As in the Rocky record: both container commands ran with
  `--security-opt label=disable`, and the initramfs build copied `scripts/` and `assets/` without
  extended attributes. Console logs and disks remain in private storage.

## Search cost

Each `search --file` that found nothing printed `no such device` and took about 43 seconds with the
five arms running at once. A single-VM spike measured about 26 seconds per miss. QEMU's firmware
logs `SCSI-DISK: Access beyond end of device` while GRUB probes the CD, which accounts for much of
the delay. With no installed disk, the last search ended 157 to 172 seconds after power-on; with the
Fedora disk it appeared after one miss, about 30 seconds in.

## btrfs default subvolume

Two spikes with an earlier ISO carrying the same search, each with one raw btrfs disk, checked
ADR 0018's openSUSE consequence. With `boot/grub2/grubenv` and `grub.cfg` at the top level, GRUB
found the disk and loaded its `grub.cfg`. With the same files only inside a subvolume set as the
default, as openSUSE Leap's snapper layout does, all four searches missed and the profile stayed
the default.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. PowerVM search timing, multipath disk
  counts, and whether a replayed `installed disk` entry boots after a CAS reboot need the native
  proof (hmc-mcp#1230).
- The installed disk came from Fedora's cloud image, not from a launcher-driven install, and no
  Ubuntu, Rocky, or openSUSE installed disk was booted.
- The refusal arms ran without `-snapshot`; unchanged qcow2 hashes show the launcher wrote nothing
  to those disks.
