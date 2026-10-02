# ADR 0013: Hand Off to the Rocky Linux Anaconda Installer

## Status

Accepted

## Context

Issue #7 asks for a RHEL-family profile that reaches its installer on POWER9 with static IPv4 and
no DHCP. On 2026-10-02 the operator chose Rocky Linux over RHEL, which avoids subscription media
and credentials. RHEL 10 and Rocky 10 on ppc64le require POWER10, so Rocky 9.8 is the newest
release that runs on POWER9. It is also the release #25 selected.

Rocky 9.8's BaseOS `.treeinfo` has Fedora's layout: `ppc/ppc64/vmlinuz`, `ppc/ppc64/initrd.img`,
`images/install.img` as stage2, and `images/boot.iso`. Its checksum equals the boot ISO line of
the GPG-signed `isos/ppc64le/CHECKSUM`. That tree also names AppStream as the sibling repository
`../../../AppStream/ppc64le/os/`, which Anaconda adds by itself. Issue #7 needs a usable installer
that discovers storage, not an installation; the unattended Kickstart belongs to #25.

## Decision

- **Profile shape.** A `rocky`/`9.8` profile carries exactly `kernel`, `initramfs`, `repository`,
  and `minimum_memory_mib`. Its fields have Fedora's grammar, and there is no `kickstart`.
  `repository.path` must end in `/BaseOS/ppc64le/os`. Manifest version stays `4`.
- **Trust anchor.** As in ADR 0011, the operator supplies the boot ISO digest from the `gpgv`-checked
  `CHECKSUM`. `prepare-rocky-source` binds the mirror `.treeinfo` to that digest and pins the
  kernel and initrd extracted from the ISO. The treeinfo helper is shared with
  `prepare-fedora-source`.
- **Handoff.** The launcher downloads the four pins and does not mount the launcher media. It then
  kexecs with Fedora's Anaconda arguments (`inst.text`, `ifname=`, `ip=…:none`, `rd.route=`,
  `nameserver=`, `inst.repo=`) minus `inst.ks`, so Anaconda starts interactive.
- **Evidence.** Post-kexec HTTP traffic may reach the BaseOS repository and its sibling AppStream
  repository and nothing else.

Specification: [Rocky installer profile](../workflow/specs/2026-10-02-rocky-installer-profile-design.md).

## Consequences

- **Accepted risk: unpinned stage2 and AppStream metadata**, the same class as ADR 0011.
- **Interactive only.** Without a Kickstart this profile cannot install unattended. #25 adds that.
- **No network subset.** dracut's `rd.route=` and `nameserver=` carry every manifest shape, unlike
  Ubuntu's (ADR 0012).
- **Local mirror.** A local run must serve BaseOS's `install.img`, kernel, initrd, and metadata, and
  AppStream's metadata.

## Considered & rejected

- **RHEL 9 with subscription media.** judgment: it needs credentials the issue keeps out of every
  artifact, and the operator chose Rocky on 2026-10-02.
- **Rocky 10.** verified: the RHEL 10.0 release notes, which Rocky 10 rebuilds, list "IBM Power
  Systems, Little Endian (POWER10 and later)" (`curl` of
  `docs.redhat.com/.../red_hat_enterprise_linux/10/html-single/10.0_release_notes`, 2026-10-02).
- **Carry a Kickstart, as Fedora does.** judgment: a network-only partial Kickstart adds a media
  artifact and mount for no #7 criterion. #25 owns the Kickstart. The operator chose this on
  2026-10-02.
- **One generalized `prepare-anaconda-source`.** judgment: it renames a public command and needs
  distribution-dependent flags. Two thin commands over one helper are simpler.
- **Allow any path in post-kexec HTTP evidence.** judgment: the evidence would stop showing that
  the installer used the declared source.
