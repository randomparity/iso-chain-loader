# ADR 0011: Carry Installer Artifacts on the Launcher ISO

## Status

Accepted

## Context

Manifest v3 (ADR 0006) resolves every launcher artifact and `inst.repo` against one HTTP origin.
The prepared initramfs and the Kickstart are built by this repository, so every deployment needs a
private server that also mirrors a Fedora tree. The operator's intent is that the launcher ISO
carries what this repository produces, while a public mirror serves Fedora's repository. The first
POWER9 PowerVM run (#6) also needs PowerVM drivers in the launcher initramfs, a mirror-consistent
preparation input, and a way to build the ppc64le initramfs from a macOS host.

## Decision

Replace manifest v3 with v4. The kernel, prepared initramfs, and Kickstart become media paths
under `/profiles/<profile>/` on the ISO. `build` stages them after checking size and SHA-256.
After its existing gates, the launcher mounts the single `/dev/sr*` device whose
`/iso-chain/config.json` matches `iso_chain.config_sha256`, read-only. It copies and verifies the
kernel and initramfs, then fetches only the pinned `.treeinfo` and `repomd.xml` from `source`.
`kexec` and the Anaconda arguments are unchanged. The Kickstart HTTP download from ADR 0006 is
removed, because Anaconda already reads the embedded copy.

`prepare-fedora-source` reads an operator-copied mirror tree and checks it against that tree's
`.treeinfo` `[checksums]`, instead of the Server DVD. `container-prepare-initramfs` runs
`prepare-initramfs` in a `linux/ppc64le` container built from the same pinned `fedora:44` index.
The launcher initramfs gains `ibmveth`, `ibmvscsi`, `sr_mod`, and `isofs`.

Specification: [ISO-carried installer artifacts](../workflow/specs/2026-10-01-iso-carried-artifacts-design.md).

## Consequences

- No private HTTP server is needed. Any HTTPS mirror that serves the prepared tree's `.treeinfo`
  and `repomd.xml` byte-for-byte can be the source. Mirror drift fails at boot, by design.
- The ISO grows by the prepared initramfs (about 1 GB, mostly `install.img`), which the VIOS media
  repository must hold.
- The launcher depends on mounting optical media. A guest that sees the ISO only through firmware
  fails with `media: failed`.
- ADR 0007's external validation narrows to two artifacts. ADR 0006's Kickstart download, and its
  HTTP-evidence rule requiring exactly one Kickstart request, no longer apply.
- Emulated ppc64le initramfs builds are slow on non-ppc64le hosts.

## Considered & rejected

- **Keep one origin and run a lab HTTP server.** judgment: it contradicts the operator's stated
  purpose for the ISO. It also adds a host to provision for every lab.
- **Split origins: custom artifacts from a lab host, repository from a mirror.** judgment: it
  keeps the lab server and adds a second trust root to the manifest.
- **Have GRUB load the payload as a second initrd.** judgment: it removes the mount code, but
  makes powerpc-ieee1275 GRUB claim about 1 GB of firmware memory on PowerVM. No run has shown
  that to work, and the optical mount carries no such risk.
- **Boot Fedora directly from GRUB, without the launcher.** judgment: it drops the mirror
  metadata pinning, the memory gate, and the `kexec` chain accepted in ADRs 0003 and 0004.
- **Take the images from the DVD and the metadata from the mirror.** verified: the DVD tree
  requires variant `Server` (`scripts/iso_chain.py` `_treeinfo_paths`). The public tree
  `https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le/os/.treeinfo`
  is variant `Everything`, with its own `[checksums]` (curl, 2026-10-01). Pairing them pins two
  trees whose consistency nothing checks.
- **Download the tree inside `prepare-fedora-source`.** judgment: it adds bounded network code to
  preparation, and a plain copy checked against `.treeinfo` gives the same assurance.
