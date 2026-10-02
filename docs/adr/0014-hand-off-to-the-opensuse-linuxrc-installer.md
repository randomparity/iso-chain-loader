# ADR 0014: Hand Off to the openSUSE linuxrc Installer

## Status

Accepted

## Context

Issue #9 asks for a SUSE-family profile that reaches its installer on POWER9 with static IPv4 and
no DHCP. On 2026-10-02 the operator chose openSUSE over SLES, which avoids subscription media and
credentials. The operator also chose Leap 15.6 over Leap 16.0: the Leap 16.0 release notes require
POWER10 and say POWER9 "may work" but is unsupported, and Leap 16 replaces linuxrc and YaST with
Agama, which is a web installer. Leap 15.6 reached end of life on 2026-04-30, and the operator
accepted that.

The Leap 15.6 `repo/oss` tree carries `CHECKSUMS` with a detached signature, `CHECKSUMS.asc`, from
the openSUSE Project Signing Key `AD485664E901B867051AB15F35A2F86E29B700A4`. It lists SHA-256 digests
for `boot/ppc64le/linux`, `boot/ppc64le/initrd`, and `media.1/products`. The initrd holds linuxrc,
whose `/etc/linuxrc.d/01_digests` file pins every inst-sys part linuxrc loads (`root`, `common`,
`bind`, `config`, `control.xml`, …). In its default secure mode, linuxrc refuses a fetched file
whose digest does not match and stops for an operator decision. The NET ISO's initrd is the same
bytes plus one 452-byte layer that sets `defaultrepo=https://download.opensuse.org/...`.

## Decision

- **Profile shape.** An `opensuse`/`15.6` profile carries exactly `kernel`, `initramfs`,
  `repository`, and `minimum_memory_mib`. `repository` is `{path}` only; the manifest version
  stays `4`.
- **Trust anchor.** The operator checks the repository's `CHECKSUMS` with `gpgv` and passes that
  file with a local copy of the tree. `prepare-opensuse-source` requires the tree's
  `boot/ppc64le/linux`, `boot/ppc64le/initrd`, and `media.1/products` to match it. It pins the
  kernel and initrd at their repository paths.
- **Handoff.** The launcher downloads only the two pins and kexecs linuxrc with
  `ifcfg=<mac>=<address>,<gateway>[,<dns>] hostname=<lpar> install=<source><path> textmode=1
  self_update=0 console=hvc0 ipv6.disable=1`. It does not mount the launcher media.
- **Network subset.** linuxrc's `ifcfg=` carries one gateway, and its DNS field is
  space-separated. So a manifest with an openSUSE profile allows only the default route and at most
  one DNS server.
- **Evidence.** The installer command line must equal the launcher's whole, because linuxrc
  ignores case and separators in option names and accepts aliases such as `repo` and `insecure`.
  Post-kexec HTTP traffic stays under `repository.path` and never re-fetches a pin. It may include
  `HEAD` requests and a fixed set of optional linuxrc and YaST probes, which must return 404.

Specification: [openSUSE installer profile](../workflow/specs/2026-10-02-opensuse-installer-profile-design.md).

## Consequences

- **Stage 2 is pinned transitively.** The pinned initrd fixes the inst-sys digests. The package
  metadata is checked by YaST's own `repomd.xml.asc` verification, not by this project.
- **Interactive only.** No AutoYaST profile; an unattended install is a follow-up under epic #1.
- **`source` integrity is trusted.** With no AutoYaST option, linuxrc reads the repository's
  `autoinst.xml` without a digest check and starts AutoYaST if one is served (linuxrc `auto2.c`,
  `auto2_read_repo_files`; a controlled-fault QEMU run, 2026-10-02). No boot option disables it.
  The HTTP evidence rejects a served `autoinst.xml`, and the operator stops at an "Automated
  Installation" screen; protecting `source` itself belongs to #29.
- **Network subset.** Extra static routes or a second DNS server fail at manifest load.
- **External traffic.** In the QEMU spike, YaST fetched release notes from `doc.opensuse.org`.
  This decision does not disable that, so the HTTP evidence covers `source` only.
- **End of life.** Leap 15.6 gets no security updates, and its signing key expired on 2026-06-19
  (`gpg --show-keys`; `gpgv` still accepts the signature). The installer is used only to reach
  storage.

## Considered & rejected

- **SLES with subscription media.** judgment: it needs credentials the issue keeps out of every
  artifact, and the operator chose openSUSE on 2026-10-02.
- **Leap 16.0 with Agama.** verified: the Leap 16.0 release notes
  (`doc.opensuse.org/release-notes/x86_64/openSUSE/Leap/16.0`, read 2026-10-02) state "POWER10 or
  higher" and "POWER9 systems may work with Leap 16.0 but are not supported". The operator chose
  15.6.
- **Anchor on the signed NET ISO digest, as Rocky and Ubuntu do.** verified: on the 15.6 Build710.3
  NET ISO (SHA-256 `032ba016…4b03`), `/boot/ppc64le/initrd` is the signed repository initrd plus a
  452-byte cpio holding `etc/linuxrc.d/10_repo` with `defaultrepo=https://download.opensuse.org/…`
  (`xorriso` extraction, `cmp`, `xz -dc | cpio`, 2026-10-02). It also needs `xorriso`. The
  operator chose the `CHECKSUMS` anchor on 2026-10-02.
- **Pin `CHECKSUMS` or `repomd.xml` in the launcher, as Rocky pins `.treeinfo`.** judgment: linuxrc
  already checks the inst-sys against the pinned initrd, so another pre-kexec download adds a pin
  without adding a check.
- **Quote `ifcfg=` to carry several DNS servers.** judgment: the evidence would need quote-aware
  command-line parsing, for a shape the QEMU proof cannot observe.
