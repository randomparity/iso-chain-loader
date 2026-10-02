# ADR 0012: Hand Off to the Ubuntu Live-Server Installer

## Status

Accepted

## Context

Manifest v4 (ADR 0011) admits only `fedora`/`44` profiles. Issue #8 adds one POWER9 Ubuntu
release that reaches its installer with the manifest's static IPv4 settings and no DHCP.

Ubuntu 26.04.1 LTS publishes a ppc64el live-server ISO, a GPG-signed `SHA256SUMS` beside it, and
`netboot/ppc64el/{linux,initrd}`. Those netboot files are byte-identical to the ISO's
`casper/vmlinux` and `casper/initrd`. The casper initramfs takes `ip=` with `off` autoconfiguration,
`BOOTIF=` for adapter selection by MAC, and `url=<...>.iso`, which downloads the whole ISO into RAM
and boots its live filesystem. Subiquity, the installer, then runs on the console.

## Decision

- **Profile shape.** Each v4 profile's exact field set is chosen by `distribution`. Fedora's is
  unchanged. An `ubuntu`/`26.04.1` profile carries `kernel`, `initramfs`, `live_iso`, and
  `minimum_memory_mib`. `live_iso.path` ends in `.iso`, as casper requires. The manifest version
  stays `4`.
- **Trust anchor.** The operator checks Ubuntu's signed `SHA256SUMS` and supplies the ISO digest.
  `prepare-ubuntu-source` requires that digest and pins the kernel and initrd that it extracts from
  the ISO. The launcher downloads the netboot copies and checks their size and SHA-256.
- **Handoff.** The launcher kexecs the Ubuntu kernel with
  `ip=<address>::<gateway>:<netmask>:<lpar>::off[:<dns>...] BOOTIF=01-<mac>
  url=<source><live_iso.path> console=hvc0 ipv6.disable=1`. It does not mount the launcher media,
  because no Ubuntu artifact lives there.
- **Network bound.** `ip=` carries one gateway and at most two DNS servers. A manifest that pairs
  an Ubuntu profile with a route other than the single default route, or with three DNS servers, is
  rejected.
- **Generic tooling.** `serve-fedora-source` becomes `serve-source`, and `verify-fedora-evidence`
  becomes `verify-installer-evidence`. Both choose their behaviour from the selected profile's
  distribution.

Specification: [Ubuntu installer profile](../workflow/specs/2026-10-02-ubuntu-installer-profile-design.md).

## Consequences

- **Accepted risk: unpinned live ISO.** casper fetches the ISO with BusyBox `wget`, which follows
  redirects and does not verify TLS certificates, and nothing in the guest checks the digest. This
  risk is the same class as ADR 0011's unpinned stage2, but it covers the whole installer and
  package payload. The manifest still pins the ISO's size and digest. `validate-external-source`
  checks the digest from the host side only. The HTTP evidence shows that the guest requested the
  pinned path and that the server sent the pinned size. Nothing checks the bytes casper booted.
- **RAM.** The ISO occupies guest RAM for the whole session. `minimum_memory_mib` must cover it.
  The value is measured under QEMU and recorded in the experiment.
- **Network subset.** Static routes beyond the default route and a third DNS server have no Ubuntu
  handoff. Such manifests fail at load, before any traffic.
- **kexec payload.** The kernel and initrd come to about 149 MB, far inside PowerVM's real mode
  area (ADR 0011).
- **Renamed commands.** Callers of the old command names break. There are no aliases, because the
  project is pre-release.

## Considered & rejected

- **Pre-verify the ISO in the launcher before kexec.** judgment: it leaves a gap between the check
  and casper's read, doubles a 1.6 GB transfer, and raises the RAM floor. The operator rejected it
  on 2026-10-02.
- **Carry the live ISO on the launcher media.** judgment: about 1.6 GB per partition, against
  ADR 0011's minimal-ISO goal. casper would also have to pick the right optical volume. The operator
  rejected it on 2026-10-02.
- **Autoinstall `network:` configuration instead of `ip=`.** judgment: it adds an ISO-carried
  cloud-init datasource for issue #8, which has no unattended configuration (that belongs to #24).
  `ip=` already reaches subiquity: verified: a QEMU 10.2.2 pSeries POWER9 boot of the 26.04.1
  netboot kernel with `ip=...:off BOOTIF=...` showed `static 10.0.2.15/24` on subiquity's network
  screen, and the capture held no DHCP or IPv6 packet (2026-10-02).
- **Translate extra routes through a casper hook.** judgment: an overlay archive appended to the
  pinned initrd would keep the pin. But it adds launcher-generated, unpinned initrd content and hook
  code for a network shape issue #8 does not need.
- **A new version 5 manifest.** judgment: every v4 manifest stays valid, and the launcher and
  parser ship on the same ISO, so no reader sees a profile it predates.
- **Keep the Fedora-named commands.** judgment: their names would misstate what they serve and
  check. The operator chose the rename on 2026-10-02.
