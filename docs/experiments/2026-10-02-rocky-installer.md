# Rocky Installer VM Experiment

Date: 2026-10-02

## Result

A QEMU pSeries/POWER9 guest booted the optical launcher, configured only the declared static IPv4
interface, and fetched the four Rocky Linux 9.8 pins from a local `serve-source` server: kernel,
initrd, `.treeinfo`, and `repomd.xml`. It verified each pin's size and SHA-256 and kexecd into
Anaconda 34.25.7.14-1.el9.rocky.0.6 with no Kickstart. Anaconda fetched `install.img` and the
BaseOS and AppStream metadata from that server and started the text installer. In the same run,
the operator chose text mode at Anaconda's VNC prompt and saw the following:

- the hub listing the installation source as the local BaseOS repository, with network
  configuration `Connected: iso0`;
- the network spoke showing `iso0` at the manifest's address, netmask, gateway, and DNS server;
- Anaconda's shell reporting `ipv4.method` `manual` and `ipv6.method` `disabled` for `iso0`;
- Installation Destination listing the blank 20 GiB virtio disk.

The operator stopped there and did not begin installation. The run passed
`verify-installer-evidence`. Native PowerVM was not run, so this proves the emulator path only.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  and two CPUs, through `smoke`. The guest used QEMU's user-mode network, its documented default
  addresses, and the MAC `52:54:00:12:34:56`.
- **Rocky media.** `Rocky-9.8-ppc64le-boot.iso` is 1,467,269,120 bytes, SHA-256
  `bd0db737aeaede1817971cade75e72027dffe836ff983852ad940a6923775a70`. `gpgv` verified
  `CHECKSUM.asc` over `CHECKSUM` with key `21CB256AE16FC54C6E652949702D426D350D275D`.
- **Pinned artifacts.** `prepare-rocky-source` read the mirror's BaseOS `.treeinfo` (1,218 bytes,
  `fea461c6…dab38`), whose `images/boot.iso` entry equals the ISO digest. It pinned the kernel and
  initrd it extracted from the ISO, which are byte-identical to the mirror's
  `BaseOS/ppc64le/os/ppc/ppc64/` files:
  - `vmlinuz`: 47,225,925 bytes,
    `fb864a9f1d843adb5c8b466549f512ab82ebb5eed109671372eb324f3c5f510e`;
  - `initrd.img`: 209,438,548 bytes,
    `fbd8ac41d0392e23e7a5d1ee35ca42747787b982fc46e58abd3f6e9a48e570e0`.
- **Served tree.** The tree mirrored `download.rockylinux.org` paths below `/pub/rocky/9.8/`:
  - BaseOS's `.treeinfo`, `images/install.img` (1,203,630,080 bytes), kernel, initrd, and
    `repodata/`;
  - AppStream's `repodata/`.

  `validate-external-source`, run against the loopback server, matched all four pins.
- **Launcher build.** Commit `daf32c5`, with the launcher kernel Fedora 7.2.8-200.fc44 and an
  initramfs from the `iso-chain-initramfs:44` image. The ISO was 109,826,048 bytes, SHA-256
  `1af72573c190a408803b0480fdfdb5c08c6aeca7e9d91d0d2e952b265daad06e`, volume ID
  `ISO_CHAIN_9FF7D526430D72F1`. The launcher script in the initramfs was byte-compared with the
  commit's.
- **Manifest.** The canonical manifest digest was
  `9ff7d526430d72f1ecb52ac21bee657381236a6ab9aad8016a6cd67782edac37`. Raw manifests, console logs,
  access logs, captures, and disks remain in private storage.
- **Build-host deviations.** These are the same as the Ubuntu record's. Both container commands
  ran with `--security-opt label=disable`, and the initramfs build copied `scripts/` and `assets/`
  without extended attributes.

## Memory

The sweep profile set `minimum_memory_mib` to 1024, so that only the launcher and installer could
stop an arm. The launcher needs `/run` space for the kernel and initrd plus 1 GiB, which is
1,330,406,297 bytes.

| QEMU `-m` | `MemTotal` | `/run` available | Stop point |
|---|---|---|---|
| 6,144 MiB | not printed | below 1,330,406,297 bytes | launcher `run-space: failed` |
| 6,656 MiB | 6,529 MiB | 1,355,284,480 bytes | Anaconda Installation Destination |
| 7,168 MiB | 7,041 MiB | 1,462,632,448 bytes | Anaconda hub |

The smallest passing arm's `MemTotal`, rounded down to a multiple of 256 MiB, gives the published
`minimum_memory_mib` of 6,400. The launcher's `/run` gate, not the installer, sets this floor. A
pre-build spike booted the same kernel and initrd directly with the same Anaconda arguments at
4,096 MiB, and it reached the hub and Installation Destination.

## Evidence

The acceptance run at 6,656 MiB used its own server, access log, disk, and capture.

- **Access log.** It held 22 requests: the four pins in order, each at its pinned size, then
  `install.img`, then BaseOS and AppStream metadata. The other two requests were
  `images/updates.img` and `images/product.img`, which returned 404. Anaconda probes both, and
  neither is published on `download.rockylinux.org`.
- **Capture.** A derivative of the capture keeping only IPv6, DHCP, and BOOTP packets held only its
  header. Outside `source` and the user-mode DNS server, the guest sent only NTP queries to
  `2.rocky.pool.ntp.org` servers, as the specification's failure model anticipates.
- **Verifier.** `verify-installer-evidence` returned:

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
intended-source: operator-reviewed
```

`intended-source` records the operator's view of the hub's installation source. No verifier
re-derives the installer's static `ip=` argument from console evidence:

- the launcher shell test pins the exact kexec arguments;
- the capture shows no DHCP;
- the operator saw `ipv4.method` `manual` in Anaconda's shell.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. PowerVM optical behaviour, real-P9
  storage, and firmware policy need a separately authorized run.
- `smoke` runs QEMU with `-snapshot`, so the unchanged disk hash shows only that the backing file
  was untouched. The absence of partition writes rests on the operator-reviewed stop at
  Installation Destination.
- The source was a loopback HTTP server holding a partial mirror. Anaconda over a public HTTPS
  mirror was not tested, and neither was a package installation, which needs `Packages/`.
