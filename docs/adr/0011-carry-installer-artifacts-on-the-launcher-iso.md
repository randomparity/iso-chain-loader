# ADR 0011: Carry Installer Artifacts on the Launcher ISO

## Status

Accepted

## Context

Manifest v3 (ADR 0006) resolves every launcher artifact and `inst.repo` against one HTTP origin.
The prepared initramfs and the Kickstart are built by this repository, so every deployment needs a
private server that also mirrors a Fedora tree.

The operator's intent is that the launcher ISO carries what this repository produces, while a
public mirror serves Fedora's repository.

The first POWER9 PowerVM run (#6) also needs three things: PowerVM drivers in the launcher
initramfs, a preparation input consistent with a public mirror, and a way to build the ppc64le
initramfs from macOS. ADR 0005 anchors trust in an operator-verified Server DVD digest. That DVD's
tree differs from every public mirror tree.

## Decision

Replace manifest v3 with v4:

- The kernel, prepared initramfs, and Kickstart become media paths under `/profiles/` on the ISO.
  `build` stages them after checking their size and SHA-256.
- After its existing gates, the launcher mounts read-only the single `/dev/sr*` device whose
  `/iso-chain/config.json` matches `iso_chain.config_sha256`. It copies and verifies the kernel
  and initramfs, then fetches only the pinned `.treeinfo` and `repomd.xml` from `source`.
- `kexec` and the Anaconda arguments are unchanged. The Kickstart HTTP download from ADR 0006 is
  removed, because Anaconda already reads the embedded copy.

Move ADR 0005's trust anchor from the Server DVD to the Fedora netinst ISO of the mirror's own
tree:

- The operator verifies Fedora's GPG-signed `CHECKSUM` and supplies the netinst digest.
- `prepare-fedora-source` requires that digest. It also requires the copied `.treeinfo`'s
  `images/boot.iso` entry to equal it, and the kernel, initrd, and runtime it extracts from the ISO
  to equal the `.treeinfo` checksums.
- That binds the public tree to a signed release. `repomd.xml` is pinned as copied.

Add `container-prepare-initramfs` for non-ppc64le hosts, and the `ibmveth`, `ibmvscsi`, `sr_mod`,
and `isofs` drivers.

Specification: [ISO-carried installer artifacts](../workflow/specs/2026-10-01-iso-carried-artifacts-design.md).

## Consequences

- **No private server.** Any HTTPS mirror serving the prepared tree's `.treeinfo` and `repomd.xml`
  byte-for-byte can be `source`. Mirror drift fails at boot.
- **ISO size.** The ISO grows by the prepared initramfs, about 1 GB, and every ISO binds one
  partition's network. The VIOS media repository holds about 1 GB per partition.
- **Optical drive required.** The launcher depends on mounting optical media. A guest that sees
  the ISO only through firmware fails with `media: failed`.
- **Earlier ADRs narrowed.**
  - ADR 0007's validation now covers two artifacts.
  - ADR 0006's Kickstart download and its HTTP-evidence rule no longer apply.
  - ADR 0005's DVD anchor is replaced by the netinst anchor described above.
- **QEMU local runs.** A local QEMU run must serve a full copy of the same tree. Its end-to-end
  proof is deferred.
- **Tooling.** Preparation still needs `xorriso`, and on macOS it runs in the builder image.
  Emulated ppc64le builds are slow.

## Considered & rejected

- **Keep one origin and a lab HTTP server.** judgment: it contradicts the operator's stated
  purpose for the ISO, and it adds a host to every lab.
- **Split origins: custom artifacts from a lab host, the repository from a mirror.** judgment: it
  keeps the lab server and adds a second trust root to the manifest.
- **Load the payload as a second GRUB initrd.** judgment: it removes the mount code, but makes
  powerpc-ieee1275 GRUB claim about 1 GB of firmware memory on PowerVM. Nothing here has shown
  that working, and the optical mount carries no such risk.
- **Boot Fedora directly from GRUB.** judgment: it drops the metadata pinning, the memory gate,
  and the kexec chain that ADRs 0003 and 0004 accepted.
- **Trust the mirror's `.treeinfo` checksums alone.** judgment: a compromised mirror can rewrite
  `.treeinfo` and the images together. That replaces ADR 0005's signed anchor with an unsigned
  one.
- **Keep the Server DVD anchor and take the metadata from the mirror.** verified:
  - `_treeinfo_paths` in `scripts/iso_chain.py` requires variant `Server`.
  - The public tree is variant `Everything`
    (`https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le/os/.treeinfo`,
    curl, 2026-10-01).
  - The netinst is that tree's own `images/boot.iso`. Its signed digest `95e63afa…84ce` equals
    that tree's `images/boot.iso` entry (`gpgv` with `RPM-GPG-KEY-fedora-44-primary`,
    2026-10-01), so the netinst binds the tree and the DVD does not.
