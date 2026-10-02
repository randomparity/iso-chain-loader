# Ubuntu Installer VM Experiment

Date: 2026-10-02

## Result

A QEMU pSeries/POWER9 guest booted the optical launcher, configured only the declared static IPv4
interface, fetched and verified the Ubuntu 26.04.1 netboot kernel and initrd from a local
`serve-source` server, and kexecd into casper. casper configured the same adapter statically from
`ip=...:off` and `BOOTIF=`, downloaded the live-server ISO from that server through `iso-url=`, and
started subiquity. In the same run, subiquity showed the following:

- its network screen listing the matched virtio adapter as `static` with the manifest's address;
- its guided storage screen listing the blank 20 GiB virtio disk.

The operator stopped there. No installer update was offered, and none was taken. The run passed
`verify-installer-evidence`. Native PowerVM was not run, so this proves the emulator path only.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  and two CPUs, through `smoke`. The guest used QEMU's user-mode network, its documented default
  addresses, and the MAC `52:54:00:12:34:56`.
- **Ubuntu media.** `ubuntu-26.04.1-live-server-ppc64el.iso` is 1,647,902,720 bytes, SHA-256
  `3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826`. `gpgv` verified
  `SHA256SUMS` with key `843938DF228D22F7B3742BC0D94AA3F0EFE21092`.
- **Pinned artifacts.** `prepare-ubuntu-source` pinned the kernel and initrd from the ISO. They are
  byte-identical to cdimage's `netboot/ppc64el` files:
  - `linux`: 64,562,608 bytes,
    `fdbac0210ea568a7befac34eacd166bbf3836d5f6f35d110b21e0929f5ae395f`;
  - `initrd`: 84,554,281 bytes,
    `3181671f1e1fc8847f2e0e6f2b4cd7908fc3277e2f99e1cf2fa468b057b4dcd4`.
- **Served-tree check.** `validate-external-source`, run against the loopback server, matched all
  three pins.
- **Launcher build.** Commit `5c8c270`, with the launcher kernel Fedora 7.2.8-200.fc44 and an
  initramfs from the `iso-chain-initramfs:44` image. The ISO was 109,826,048 bytes, SHA-256
  `be344b449fa70257d4c1d98af74b78a6a8dd9c0dd9dc0e44e205f74e4c48bc3f`, volume ID
  `ISO_CHAIN_10D8C121B34C2740`.
- **Manifest.** The canonical manifest digest was
  `10d8c121b34c27402934acb17245b69e41faca6cc969f0dde17c9c0be59cfb10`. Raw manifests, console logs,
  access logs, captures, and disks remain in private storage.
- **Build-host deviations.** This host enforces SELinux, so both container commands ran with
  `--security-opt label=disable`. The initramfs build also copied the checkout's `scripts/` and
  `assets/` without extended attributes before running the image's own `prepare-initramfs`. Without
  that copy, dracut could not install the launcher assets but still exited 0. The launcher script
  in the built initramfs was byte-compared with the commit's.

## Memory

The launcher's checks come first: `minimum_memory_mib` against `MemTotal`, and then available
memory and `/run` space for the kernel and initrd plus 1 GiB. The sweep profile set
`minimum_memory_mib` to 1024, so that only the launcher and installer could stop an arm.

| QEMU `-m` | `MemTotal` | `/run` available | Stop point |
|---|---|---|---|
| 4,096 MiB | not printed | below 1,222,858,713 bytes | launcher `run-space: failed` |
| 6,144 MiB | 6,019 MiB | 1,248,329,728 bytes | subiquity guided storage |
| 8,192 MiB | 8,065 MiB | 1,677,459,456 bytes | subiquity guided storage |

The smallest passing arm's `MemTotal`, rounded down to a multiple of 256 MiB, gives the published
`minimum_memory_mib` of 5,888. At 6,144 MiB the launcher's `/run` gate, not the installer, sets the
floor. casper then holds the 1.6 GB ISO in RAM for the whole session.

## Evidence

The acceptance run at 6,144 MiB used its own server, access log, disk, and capture. The access log
held exactly three requests, in order: the kernel, the initrd, and the ISO, each once at its
pinned size. A derivative of the capture keeping only IPv6, DHCP, and BOOTP packets held only its
header. The guest made one HTTP connection to an Ubuntu ports archive host over the static default
route, as the failure model in the specification anticipates. `verify-installer-evidence`
returned:

```text
manifest: passed
memory: passed
http-evidence: passed
disk-unchanged: passed
dhcp-ipv6-filter: absent
capture-provenance: operator-reviewed
same-run: operator-reviewed
installer-readiness: operator-reviewed
storage-visibility: operator-reviewed
installer-network: operator-reviewed
```

An earlier 6,144 MiB arm passed the live ISO as `url=`. Its access log held three ISO GETs: one
from casper's `wget`, and two from `Cloud-Init/26.1-0ubuntu3~26.04.1`, which reads `url=` as a
cloud-config URL. The handoff now uses `iso-url=`, and the verifier rejects `url=` and
`cloud-config-url=`.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. PowerVM optical behaviour, real-P9
  storage, and firmware policy need a separately authorized run.
- `smoke` runs QEMU with `-snapshot`, so the unchanged disk hash shows only that the backing file
  was untouched. The absence of partition writes rests on the operator-reviewed stop at guided
  storage.
- The source was a loopback HTTP server. casper over a public HTTPS mirror was not tested.
