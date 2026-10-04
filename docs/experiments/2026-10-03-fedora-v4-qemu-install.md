# Fedora Manifest v4 QEMU Install Experiment

Date: 2026-10-03

## Result

A QEMU pSeries/POWER9 guest booted a launcher ISO built from a manifest v4 Fedora profile. The
launcher found the ISO on the guest's SCSI optical drive (`sr0`), verified the media Kickstart,
fetched and verified the pinned Fedora kernel, initrd, `.treeinfo`, and `repomd.xml` from a local
`serve-source` server, and kexecd into Anaconda with
`inst.ks=cdrom:LABEL=ISO_CHAIN_116A32C51A50667C:/profiles/fedora-44/ks.cfg`. Anaconda read that
Kickstart from the optical drive, took `install.img` and every package from the served tree,
installed Fedora 44 Server onto the fresh 20 GiB virtio disk with no prompt, and powered off. The
disk then booted with no ISO and no network adapter and printed exactly one installed-boot marker.
`verify-fedora-install-evidence` passed at commit `9a60595`, after the fix described under
[Defect found](#defect-found). This is emulator evidence only; native PowerVM was not run.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 32,768 MiB, through `install-fedora` with a 7,200-second install timeout and a
  600-second boot timeout. The guest used QEMU's user-mode network with its documented default
  guest address, gateway, and DNS, and QEMU's default MAC. `install-fedora` attached the ISO as a
  `scsi-cd` device with `media=cdrom` behind `virtio-scsi-pci`.
- **Source.** The full Fedora 44 Server ppc64le release tree, compose 1.7, copied from the Fedora
  secondary architecture mirror: `.treeinfo`, `images/`, `ppc/`, `repodata/`, and the 2,192
  packages of `Packages/`. The signed `Fedora-Server-44-1.7-ppc64le-CHECKSUM` verified with
  `RPM-GPG-KEY-fedora-44-primary`, and `Fedora-Server-netinst-ppc64le-44-1.7.iso` (1,160,095,744
  bytes) matched its SHA-256
  `db84e9e9e2ca979f322c877a96584633226d0c4d8052b97ec5cdcdfcc4c7c17f`, which equals the tree's
  `.treeinfo` `images/boot.iso` entry. `serve-source` served the tree on loopback under the
  mirror's path, `/pub/fedora-secondary/releases/44/Server/ppc64le/os`.
- **Server for Everything.** The design names the Everything tree for local runs; this run used
  the Server tree, which `prepare-fedora-source` accepts as the other allowed variant, by operator
  decision on 2026-10-03.
- **Preparation.** `prepare-fedora-source` with the netinst ISO, the tree, `--minimum-memory-mib
  8192`, and `assets/kickstart/fedora-44-power9.ks` (1,450 bytes, SHA-256
  `b30be8bbf1f8563cb8914f76d6bca9dd1781eef80c81297de047c3d419b0b044`) pinned the kernel (66,211,760
  bytes) and initrd (224,706,724 bytes) it extracted from the ISO, `.treeinfo` (1,166 bytes), and
  `repomd.xml` (5,925 bytes). The canonical manifest digest was
  `116a32c51a50667cd794895efb78dc9a976b46bc97da1dc1b97f9aab31569c59`.
- **Launcher build.** The launcher kernel was Fedora 7.2.8-200.fc44, with an initramfs built from
  the `iso-chain-initramfs:44` image at commit `c0e883d`, whose `assets/dracut/` equals that of
  `dadd808`; the embedded `iso-chain-launch.sh` was compared byte for byte with the asset.
  `container-build` at `dadd808` produced a 109,860,864-byte ISO, SHA-256
  `64ae4e399d9dff4f38d8eb0a0613b6bab8e79bcc3aba31e28ec2eab223787c29`, volume ID
  `ISO_CHAIN_116A32C51A50667C`, and `inspect` returned the manifest's canonical bytes. As in the
  earlier records, the container commands ran with `--security-opt label=disable`, and the
  initramfs build copied `scripts/` and `assets/` without extended attributes.

Raw manifests, console logs, access logs, captures, disk digests, and disks remain in mode-0700
private storage.

## Run

One acceptance run used a fresh `serve-source` server, access log, and `install-fedora` output
directory. It took 38 minutes 48 seconds: about 36 minutes for the install phase and 2 minutes 42
seconds for the disk-only boot.

- **Install phase.** The launcher printed `ISO_CHAIN: configuration passed`, `adapter-match: passed`,
  `profile: passed`, `memory: passed memtotal_mib=32581 memavailable_mib=32124
  run_available_bytes=6818824192`, `disk: passed`, `media: passed`, `artifacts: passed`,
  `kexec-load: passed`, and `kexec-exec: started`. Anaconda 44.30-2.fc44 reported `Starting
  automated install`, installed 671 packages from the `server-product-environment` group, ran the
  Kickstart's `%post`, and the kernel printed `reboot: Power down`; QEMU exited 0.
- **Boot phase.** QEMU booted the disk with `-boot c`, no ISO, and `-nic none`. Fedora's installed
  kernel 6.19.10-300.fc44 printed one `installed-boot: passed boot_id=...` line from the
  Kickstart's service, then powered off; QEMU exited 0.

## Evidence

- **Access log.** 685 GET requests, all under the repository path: the kernel, initrd,
  `.treeinfo`, and `repomd.xml` first, in that order and at their pinned sizes; then `.treeinfo`,
  `images/install.img`, one 404 each for `images/updates.img` and `images/product.img`, and the
  rest of the repository traffic, including the 671 packages. The kernel and initrd were each
  requested once, and no request named a Kickstart.
- **Capture.** The derivative of the install capture keeping only IPv6, DHCP, and BOOTP packets
  held only its header.
- **Disk.** The fresh disk's digest changed, and `result.json` records both QEMU exit statuses as
  0.
- **Verifiers.** `verify-fedora-install-evidence`, on a canonical record binding the manifest,
  Kickstart, both consoles, the access log, the result, the filtered capture, and both disk
  digests, returned:

```text
manifest: passed
kickstart: passed
network-config: passed
http-evidence: passed
installation: passed
disk-mutation: passed
disk-only-boot: passed
dhcp-ipv6-filter: absent
same-run: operator-reviewed
```

`verify-launcher-log` on the install console returned `configuration`, `adapter-match`,
`profile`, `memory`, `disk`, `media`, `artifacts`, and `kexec-load` passed, then `kexec-exec:
started`, and `verify-pcap` on the filtered capture returned `dhcp-ipv6-filter: absent`.

## Defect found

At `dadd808` the same evidence failed with `error: access log contains failed or reordered
requests`. Manifest v4 takes Fedora's `install.img` from the repository (ADR 0011), and
Anaconda's stage1 then probes `images/updates.img` and `images/product.img` beside it, as it does
for Rocky. The Fedora 44 tree publishes neither, but the HTTP evidence rules admitted those two
404s for Rocky only. Commit `9a60595` admits them once each for Fedora too, in both
`verify-installer-evidence` and the install verifiers; any other failed request, or a repeated
probe, still fails. Manifest v3 never showed the probes, because its installer initramfs carried
the stage2 runtime. The ISO and launcher are unaffected by the fix.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. The live PowerVM proof belongs to #28.
- The source was a loopback HTTP server holding a full copy of the Server tree. A public HTTPS
  mirror was not tested.
- The guest saw one optical drive and one virtio disk. The launcher's refusals for other media
  and disk layouts are covered by the shell tests and the
  [installed-disk experiment](2026-10-02-installed-disk-boot.md), not by this run.
