# ADR 0011: Carry the Kickstart on the Launcher ISO

## Status

Accepted

> **Plain-HTTP sources restricted by
> [ADR 0026](0026-restrict-plain-http-to-private-ipv4-sources.md)** (2026-10-05): the grammar now
> accepts an `http://` source only on loopback and RFC 1918 IPv4 hosts.

## Context

Manifest v3 (ADR 0006) resolves every launcher artifact and `inst.repo` against one HTTP origin.
The prepared initramfs and the Kickstart are built by this repository, so every deployment needs a
private server that also mirrors a Fedora tree.

The operator wants a minimal launcher ISO that carries what this repository produces, while an
HTTPS mirror serves Fedora: a public mirror for now, and an internal one once it exists.

The first POWER9 PowerVM run (#6) showed that ADR 0005's bundle cannot boot there. The bundle joins
the netinst `initrd.img` with the 851 MB `install.img` runtime, 1,068,556,772 bytes in all.
Under PowerVM's hash MMU, both kexec paths confine segments to the real mode area. On the live
partition, `kexec_file_load` failed with `EADDRNOTAVAIL`, and `kexec_load` failed with
`Could not find a free area of memory of 0x3fb10000 bytes`. QEMU pSeries POWER9 guests run radix,
which has no such limit.

## Decision

Replace manifest v3 with v4:

- **Fedora artifacts.** A profile's `kernel` and `initramfs` are Fedora's own netinst `vmlinuz`
  and `initrd.img`, named by URL path under `source`. The launcher downloads them unmodified and
  checks size and SHA-256, as it already does for `.treeinfo` and `repomd.xml`.
- **Kickstart.** The Kickstart is the one media path, `/profiles/<directory>/<file>`, on the ISO.
  `build` stages it after checking its size and SHA-256.
- **Launcher.** After its existing gates, the launcher mounts read-only the single `/dev/sr*`
  device whose `/iso-chain/config.json` matches `iso_chain.config_sha256`, and verifies the
  Kickstart there.
- **Anaconda.** `build` sets the ISO volume ID to `ISO_CHAIN_` and the first 16 hex digits of the
  manifest digest. Anaconda reads the Kickstart with `inst.ks=cdrom:LABEL=<volume ID>:<path>`,
  since a bare `cdrom:<path>` takes whichever optical drive first holds that path. It fetches its stage2
  runtime through `inst.repo`.
- **Removed.** The initramfs bundle and its stage2 hook (ADR 0005) are removed.

Move ADR 0005's trust anchor from the Server DVD to the Fedora netinst ISO of the mirror's own
tree:

- The operator verifies Fedora's GPG-signed `CHECKSUM` and supplies the netinst digest.
- `prepare-fedora-source` requires the copied `.treeinfo`'s `images/boot.iso` entry to equal that
  digest. It also requires the kernel and initrd it extracts from the ISO to equal the `.treeinfo`
  checksums. Their sizes and digests become the profile's pins.

Add `container-prepare-initramfs` for non-ppc64le hosts, and the `ibmveth`, `ibmvscsi`, `sr_mod`,
and `isofs` drivers.

Specification: [ISO-carried installer artifacts](../workflow/specs/2026-10-01-iso-carried-artifacts-design.md).

## Consequences

- **Small ISO, no private server.** The ISO holds the launcher, the manifest, and Kickstarts:
  about 100 MB. Any HTTPS mirror serving the prepared tree byte-for-byte can be `source`. Mirror
  drift fails at boot.
- **Fits the real mode area.** The kexec payload is Fedora's kernel and initrd, about 291 MB.
- **Accepted risk: unpinned stage2.** Anaconda fetches `install.img` from the mirror, and no
  digest checks it. ADR 0005 rejected exactly this. The operator accepts it to keep the ISO
  minimal, relying on an internal mirror for production. With an `http://` source, which the
  grammar keeps for loopback and test servers, the runtime is also unauthenticated in transit.
- **Check-to-read gap.** The launcher checks the Kickstart on the media, and Anaconda reads it again
  later. A VIOS administrator who substitutes media in between is outside the threat model.
- **Optical drive required.** A guest that sees the ISO only through firmware fails with
  `media: failed`, and Anaconda cannot read the Kickstart.
- **Earlier ADRs narrowed.**
  - ADR 0005's bundle is withdrawn, and its DVD anchor is replaced by the netinst anchor.
  - ADR 0006's Kickstart download no longer applies.
  - ADR 0007's validation covers four artifacts.
- **QEMU local runs.** A local QEMU run must serve a full copy of the same tree. Its end-to-end
  proof is `docs/experiments/2026-10-03-fedora-v4-qemu-install.md`.

## Considered & rejected

- **Keep ADR 0005's bundle on the ISO.** verified: on the #6 partition (Fedora 44 kernel 7.2.8,
  kexec-tools 2.0.32), `kexec_file_load` failed with `EADDRNOTAVAIL`, and `kexec -c` failed with
  `locate_hole failed`. Both are bounded by `ppc64_rma_size` (`arch/powerpc/kexec/elf_64.c`) and
  `rma_top` (`kexec/arch/ppc64/kexec-ppc64.c`).
- **Carry `install.img` on the ISO, with the installer's dracut hook verifying it.** judgment: it
  keeps stage2 pinned, but it adds a fourth media artifact, about 850 MB per ISO, and new hook
  code. The operator chose a minimal ISO instead.
- **Carry Fedora's kernel and initrd on the ISO.** judgment: about 290 MB more per ISO, with no
  integrity gain, since the launcher pins the mirror's copies to the same digests.
- **Keep one origin and a lab HTTP server.** judgment: it contradicts the operator's stated
  purpose for the ISO, and it adds a host to every lab.
- **Boot Fedora directly from GRUB.** judgment: it drops the metadata pinning, the memory gate,
  and the kexec chain that ADRs 0003 and 0004 accepted.
- **Trust the mirror's `.treeinfo` checksums alone.** judgment: a compromised mirror can rewrite
  `.treeinfo` and the images together. That replaces ADR 0005's signed anchor with an unsigned
  one.
- **Keep the Server DVD anchor and take the metadata from the mirror.** verified:
  - `_treeinfo_paths` in `scripts/iso_chain.py` required variant `Server`.
  - The public tree is variant `Everything`
    (`https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le/os/.treeinfo`,
    curl, 2026-10-01).
  - The netinst is that tree's own `images/boot.iso`. Its signed digest `95e63afa…84ce` equals
    that tree's `images/boot.iso` entry (`gpgv` with `RPM-GPG-KEY-fedora-44-primary`,
    2026-10-01), so the netinst binds the tree and the DVD does not.
