# PowerVM CAS Reboot and Installed-Disk Boot Experiment

Date: 2026-10-17 (runs ended 2026-10-18 UTC)

This run exercised the Fedora 44 launcher on a native PowerVM partition for the three open questions
in #28: whether the menu fix of commit `c714143` survives a firmware CAS reboot, whether the
`blkid` volume-ID check of commit `fdeea6b` passes on PowerVM, and whether an installed disk boots
through the ISO's GRUB. **Only the first is answered, and only as worded: no abort followed a
CAS restart, but no window reached a menu replay.** The `blkid` check and the replayed
`installed disk` entry were not observed. The results below say which console lines support each
claim and which do not.

## Inputs and environment

The target was a new POWER9 PowerVM partition (`lpar-R1` on `sys-R1`) managed by an HMC (`hmc-R1`),
with 32 GiB memory, 4 virtual processors, one virtual Ethernet adapter, and a vSCSI client adapter
on `vios-R1` carrying a 100 GiB logical volume (`sda`) and a virtual optical device. The partition
had a static IPv4 address, route, and resolver in the manifest and no DHCP service. It could not
reach the build host, so the manifest's `source` was the upstream Fedora secondary-architecture
mirror (`https://download-ib01.fedoraproject.org`).

The ISO was built from commit `2eb99adf17fbdf5ca10730d82594bb0b93a42759` (`main` after PR #98),
which contains both `c714143` and `fdeea6b`. The launcher initramfs was rebuilt with the
repository's container recipe the same day; the launcher kernel was Fedora 7.2.10-200.fc44. The
profile pinned
Fedora 44's `Everything` ppc64le netinst files, unchanged from the
[2026-10-01 record](2026-10-01-powervm-iso-carried-kickstart.md), and the Kickstart was
`assets/kickstart/fedora-44-powervm.ks` (`a5545effaba65ce889fd6a845b7fb10f7f5f218ffc13f5802ad10918956f9ab2`).

- ISO: 109,867,008 bytes,
  `edc83829c57d2ad7df9af958af4347e3251690c74301a5ddeef9e583b0ebdaae`.
- Manifest SHA-256 (the kernel argument `iso_chain.config_sha256`):
  `33f75575dc0947db9e694b2bf30950c93d067725cc4f76e35ec6b173eafc03d6`.

The ISO was uploaded with `hmcpctl storage upload-iso` and loaded on the virtual optical device.
Console evidence came from bounded, output-only `hmcpctl lpars capture-console` windows. Raw
manifests, network values, console logs, HMC records, and the ISO remain in mode-0700 private
storage. No packet capture was taken.

## Result

**Activation 1, first boot on a new partition.** The console showed GRUB's own call
`Calling ibm,client-architecture-support from grub...`, the firmware restart, and a second
`Welcome to GRUB!`. That second pass printed `grub_search_fs_file ... no such device: /grub2/grubenv`
(the first of the four searches of ADR 0018) and neither `double free` nor an abort. The capture
ended on its idle limit while GRUB was still searching, so this window did not reach the menu or a
menu replay.

**Activation 2, a later power-on.** GRUB ran its four failed `grubenv` searches, showed the `fedora`
entry, and printed `ISO_CHAIN: GRUB optical handoff`. The launcher kernel's command line carried the
expected `iso_chain.*` arguments and `iso_chain.config_sha256`. The kernel then printed
`Calling ibm,client-architecture-support...`, the firmware restarted, and a third
`Welcome to GRUB!` appeared, followed again by the failed `grubenv` search. My capture then ended on
its duration limit. The launcher output that followed was lost, and this window shows neither the
menu nor an entry after the restart. In short, this is a kernel-side CAS reboot followed by a GRUB
pass that did not abort during the search; it is not a replayed menu entry.

**The launcher stalled in the initramfs emergency shell.** The operator's journal showed
`adapter-match`, `profile`, and `memory: passed`, then `disk-blank: failed`. `mklv` had created
`sda` without zeroing it, so the last MiB held data from earlier use. The operator zeroed the first
and last MiB (both then hashed to `30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58`)
and ran `systemctl restart --no-block iso-chain-launch.service` by hand. The operator reported a
download, a `kexec` boot, and Anaconda, but their scrollback was not kept and my capture did not
cover it.

**Install.** The next capture began mid-installation and shows packages 366 to 742 of 742 and then
`reboot: Power down`; the partition went to Not Activated. Anaconda's start-up, including its
Kickstart read, falls before this capture.

**Installed-disk boot.** I powered the partition on with the ISO still first in the boot order and
the installed disk attached. GRUB found the installed disk, printed
`ISO_CHAIN: GRUB installed-disk handoff`, and booted Fedora kernel 6.19.10-300.fc44 from `sda`.
That kernel printed `Calling ibm,client-architecture-support... done` with no restart.
The system then printed `installed-boot: passed boot_id=<REDACTED-BOOT-ID>` and powered off.

### Against the acceptance criteria of #28

| Criterion | Outcome |
| --- | --- |
| 1. A CAS reboot, then a second GRUB pass with no `double free` or abort | Two CAS restarts were captured (GRUB's own in activation 1, the kernel's in activation 2). Each following GRUB pass printed its search errors without aborting. Neither window reached a menu replay, so the fixed code path (replaying an entry after a restart) was not observed. |
| 2. A boot from a PR #30 or later ISO passes the `blkid` check and reaches the Kickstart read | **Not observed.** No console log holds `media: passed`. Anaconda did run from this ISO after a manual service restart, which indicates the check did not refuse it, but the check's output was never captured. |
| 3. Whether the replayed `installed disk` entry boots after a CAS reboot | **Not observed.** The `installed disk` entry booted on a cold power-on and the installed system came up, but no CAS restart happened in that boot's GRUB, so nothing was replayed. |

## Findings

- **GRUB's `grubenv` search is very slow on PowerVM.** Each failed search took roughly 8 to 11
  minutes, from polls of the console, against about 26 seconds under QEMU. A boot with no installed
  disk spends about 40 minutes in the four searches, and a CAS restart repeats them. This matches
  the 75-minute power-on-to-ping time in the
  [RHEL record](2026-10-15-rhel-installer.md). ADR 0018 lists PowerVM search timing as unmeasured;
  this is a first measurement, not an explanation of the cause.
- **`mklv` leaves stale data at the end of the volume.** A new logical volume failed
  `disk-blank` until its first and last MiB were zeroed. The guard did what ADR 0018 intends, but
  the operator procedure for a fresh volume does not say to zero it.
- **The installed-disk handoff works on native PowerVM.** The Fedora `installed disk` entry
  booted the installed kernel through the ISO's GRUB, and the first boot after the install printed
  `installed-boot: passed`.

## Proof limits

- Console only; no packet capture. Criteria 2 and 3 remain open, and criterion 1 is met only as
  worded (see the table).
- The launcher service was restarted by hand after `disk-blank: failed`, so the install did not
  follow the boot path unaided.
- Capture windows were bounded and chained by hand. Activation 1's capture ended on idle and
  activation 2's on duration; the output that followed each is unrecorded.
- This is one partition on one system. It makes no claim about other firmware, other VIOS
  configurations, multipath, or the Rocky, RHEL, Ubuntu, and openSUSE installed-disk entries.

Retained private evidence, by SHA-256: activation 1 console
`16a0bc9cf81738fd94d8e38448392b110977bb765701e5cec8c6d0afeefee45d`, activation 2 console
`85de3ab9920a5286546a23bcee18f327c24dae66df7ddab06c6d6c439ba2d9a1`, install console
`b2c7b3603d05c1bd7a1b4b5d95cd5059d4c9231a67de8d7d2c18b9b394579af8`, installed-disk boot console
`bd8fb0cfe04c6506b1ba6ec73a3eafe908457e7622f3f3e05fc8081d3418b204`. No disk image was hashed.

## Boundary and cleanup

Mutations stayed within the authorized partition, its VIOS mappings and logical volume, and the
VIOS media repository. The partition was left powered off with the uploaded ISO still loaded and in
the repository, pending operator cleanup.
