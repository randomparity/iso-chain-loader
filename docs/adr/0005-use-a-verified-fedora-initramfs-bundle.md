# ADR 0005: Use a Verified Fedora Initramfs Bundle

## Status

Accepted

## Context

Issue #5 must launch a Fedora ppc64le installer from local HTTP without trusting that transport to
preserve executable content. The launcher must authenticate the installer kernel, initramfs, and
runtime before kexec, while Fedora's installer still needs an HTTP package repository. ADR 0003
assigns the second-kernel boundary to kexec and ADR 0004 assigns network policy to the Linux
launcher.

## Decision

Prepare a Fedora 44 source tree from the vendor's Server DVD ISO only after its caller-supplied
SHA-256 matches. Publish a kernel and one augmented initramfs bundle under a versioned profile
directory. The bundle joins Fedora's installer initramfs with its `images/install.img` runtime and
an initqueue hook that mounts that already-authenticated runtime through Fedora's existing
`anaconda_mount_sysroot` function. The remaining extracted tree is the installer's local-HTTP
package repository.

Manifest version 2 records exact byte sizes and SHA-256 digests for the kernel and bundle. The
launcher downloads each once with time and size limits, verifies both, constructs Fedora static
network arguments, loads them with kexec, and retains its diagnostic shell on failure. Fedora's
normal package-signature policy remains responsible for package payloads.

## Consequences

The runtime is not fetched a second time across an unauthenticated gap. The augmented bundle is
larger and raises the launcher's RAM requirement, so the profile records a measured minimum and
the launcher rejects insufficient memory before downloading. Source preparation additionally
requires `xorriso`, `cpio`, and the compression tool matching Fedora's initramfs.

This validates QEMU pSeries/POWER9 behavior, not PowerVM firmware, VIOS mappings, Secure Boot, or a
native LPAR. Later distro profiles may use another bundle recipe behind the same manifest contract.

## Considered & rejected

- **Let Anaconda fetch `install.img` from `inst.stage2`.** verified: Fedora Server 44 compose 1.7's
  `/usr/lib/anaconda-lib.sh` fetches stage2 from the repository URL and discovers
  `images/install.img`, but its boot parser exposes no caller-supplied digest; a network replacement
  would therefore cross the kexec boundary unauthenticated.
- **Keep a separate profile file beside manifest version 1.** judgment: two coupled configuration
  contracts would have to agree on profile identity, source, and network handoff.
- **Hard-code Fedora 44 in the launcher.** judgment: this would make the first profile smaller only
  by forcing another runtime redesign for the already-planned RHEL, Ubuntu, and SLES profiles.
- **Do nothing.** judgment: the current launcher intentionally stops after a one-byte HTTP probe and
  cannot reach an installer.
