# Operator-File Launcher Installs

Date: 2026-10-29

Issue #131, parent #120. Decision:
[ADR 0034](../adr/0034-carry-operator-installer-configuration-in-the-manifest.md). Verification:
[operator-file media](../guides/verification.md#operator-file-media).

## Result

Launcher media built from the shipped Fedora, Rocky and Ubuntu operator-file examples installed
under QEMU pSeries/POWER9 and passed their matching canonical installation verifiers. In each run
the operator's file ran to its end: the composed blank-disk guard passed, the installer rebooted
once, and the ISO's GRUB printed `ISO_CHAIN: GRUB installed-disk handoff`, which the menu prints
only after the composed file set `iso_chain_installed=1`. The harness stopped QEMU there
(`boot_stop: installed-disk-handoff`).

| Profile | Media-building commit | Result | Run time |
| --- | --- | --- | --- |
| Fedora 44 | `b10a181775c31b6d63edcc2975c1c9fc77adb445` | Installed; installed-disk handoff; `verify-fedora-install-evidence` passed | 40 min 35 s |
| Rocky 9.8 | `bedd4d0036f554e9d83d7ec14d282425f982c709` | Installed; installed-disk handoff; `verify-rocky-install-evidence` passed | 51 min 51 s |
| Ubuntu 26.04.1 | `bedd4d0036f554e9d83d7ec14d282425f982c709` | Installed; installed-disk handoff; `verify-ubuntu-install-evidence` passed | 25 min 23 s |

Run times are the `install-*` commands' wall times and exclude source preparation. Each arm's
verifier ran from the commit that built its media. A first Fedora attempt on `bedd4d0` did not
install; see [Fedora first attempt](#fedora-first-attempt). This is emulator evidence only. Native
PowerVM was not run (#72), and the installed system's boot and login are not proven: the harness
stops at the handoff and the verifiers drop the `login:` observation for operator media
(ADR 0034). The RHEL arm waits for #97. openSUSE has no operator mode.

## Inputs and execution

Each arm's media was built, and its evidence verified, from a clean checkout at the commit in the
result table. The Fedora arm ran after #142 (PR #143) fixed the shipped starter; the Rocky and
Ubuntu arms did not depend on that change.

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode and
  two CPUs, directly on the host through `install-fedora`, `install-rocky` and `install-ubuntu`,
  with 32,768 MiB (Fedora) or 8,192 MiB and a fresh 20 GiB disk each. The guest used QEMU's
  user-mode network with its documented default addresses (`10.0.2.15/24`, gateway `10.0.2.2`, DNS
  `10.0.2.3`) and the MAC `52:54:00:12:34:56`. Source preparation, the ISO build and the launcher
  initramfs ran on this host; the initramfs came from the emulated `iso-chain-initramfs:44`
  container path.
- **Manifests.** Each was derived from the shipped `examples/<distribution>-operator.json`. Only
  `lpar`, the network block, `source` and the profile object changed: the profile came from the
  matching `prepare-*-source` output, with the example's operator file kept. The Ubuntu user data's
  netplan block and host name were set to the same network values. The Kickstart and the key
  placeholders were not altered, and the example files were not changed.
- **Sources.** Fedora's signed `CHECKSUM` passed `gpgv` with the Fedora 44 release key and the
  Everything compose 1.7 netinst ISO matched
  `95e63afad3ea52af38940603a173ac4ea229db717549bcf607c5b7f3ced284ce`. Rocky's `CHECKSUM` passed
  `gpgv` with the Rocky 2022 release key (`21CB256AE16FC54C6E652949702D426D350D275D`); the boot ISO
  matched `bd0db737aeaede1817971cade75e72027dffe836ff983852ad940a6923775a70`. Ubuntu's `SHA256SUMS`
  passed `gpgv` with the CD image signing key (`843938DF228D22F7B3742BC0D94AA3F0EFE21092`); the live
  ISO matched `3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826`.
  `prepare-fedora-source`, `prepare-rocky-source` and `prepare-ubuntu-source` produced the profiles.
- **Served trees.** `serve-source` served each tree on loopback, which the guest reached at
  `10.0.2.2`. Ubuntu's tree hard-linked the verified ISO and the two prepared files. Rocky's and
  Fedora's trees held the repository metadata and only the packages the install requests (339 and
  742); a throwaway scratch install through a private caching fetcher collected them from the
  mirrors. All 339 Rocky packages matched the size and SHA-256 in their repository's `primary.xml`,
  and every package in both trees passed `rpmkeys --checksig` with the release key. The acceptance
  run started from a fresh server and access log.
- **Launcher build.** The initramfs was rebuilt at each build commit. The container commands ran
  with `--security-opt label=disable`; dracut logged xattr-copy errors for the launcher assets,
  exited zero, and the embedded shell, service and target compared byte for byte with the commit's
  assets. `container-build` produced 109,867,008-byte ISOs.
- **Retries.** Each arm has one acceptance run, but the harness around them had defects that
  discarded earlier attempts without evidence value: a host-side `validate-external-source`
  against the Ubuntu server wrote requests into that server's log, which was replaced before the
  run; the Rocky tree briefly held a package under its percent-encoded name, so the guest got four
  404s and the attempt was stopped and the file renamed; and the scratch Rocky install timed out
  once while the fetcher was still downloading `linux-firmware`.

Raw manifests, media, keys, logs, captures, disks and the session transcript remain private.

## Run and evidence

- **Fedora.** The launcher printed `memory: passed memtotal_mib=32581`, `disk: passed` and
  `media: passed`; Anaconda's command line carried
  `inst.ks=cdrom:LABEL=ISO_CHAIN_1C9A716282195BDE:/profiles/fedora/ks.cfg`. It printed
  `Installing boot loader` and `Running post-installation scripts`, then the kernel printed
  `reboot: Restarting system` once. The access log held 755 requests: the four pins first and in
  order, 742 package requests, and one 404 each for `images/updates.img` and `images/product.img`.
  The boot phase showed one handoff line.
- **Rocky.** The launcher printed `memory: passed memtotal_mib=8065`, `disk: passed` and
  `media: passed`; Anaconda's command line carried
  `inst.ks=cdrom:LABEL=ISO_CHAIN_F9FCEAB8B19A2EA0:/profiles/rocky/ks.cfg`. It printed
  `Installing boot loader`, `Running post-installation scripts` and `Installation complete`, then
  the kernel printed `reboot: Restarting system` once. The access log held 361 requests: the four
  pins first and in order, 339 package requests, and one 404 each for `images/updates.img` and
  `images/product.img`. The boot phase showed one handoff line and no login prompt.
- **Ubuntu.** The launcher printed `memory: passed memtotal_mib=8065`, `disk: passed` and
  `media: passed`; the early guard printed `autoinstall-disk: passed vda` once, and the kernel
  printed `reboot: Restarting system` once. The access log held exactly the kernel, initrd and
  live ISO, once each. The boot phase showed one handoff line and no login prompt.
- **Disk and captures.** Both disk digests changed from the blank-disk digest. Derivatives of the
  install and boot captures keeping only IPv6, DHCP and BOOTP packets held only their headers. -
  **Verifiers.** Per arm, a canonical version-1 record bound the manifest, both consoles, the access
  log, `result.json`, both filtered captures and both disk digests. All three verifiers exited zero
  and printed, in order:

```text
manifest: passed
kickstart: passed            (Ubuntu: user-data: passed)
network-config: passed
http-evidence: passed
installation: passed
reboot: passed
disk-mutation: passed
installed-disk-handoff: passed
install-dhcp-ipv6-filter: absent
boot-dhcp-ipv6-filter: absent
same-run: operator-reviewed
```

Bound identities, each a SHA-256:

- **Fedora 44**
  - manifest: `1c9a716282195bde92a891703fa029edb679a72696c0183dd8d976a412d923f3`
  - media: `1f293aeefb4219a921a9167770a8b0b48fd929addf000edf54965c11228d6cd7`
  - record: `47212c8efff1c799fbd76204dae9dde4714d81bc6e317b04875150526062d39d`
- **Rocky 9.8**
  - manifest: `f9fceab8b19a2ea0c366e92e5fefc153394daaf42450e39f22e4086bbe570137`
  - media: `72c0eb9baf55d0c3b2e40448abc619649e34712502ccd5944872f6a709bec9fa`
  - record: `88c785b09e0dac3254b9a9eaf382169b045a2686b038025e2eb80c307b63badc`
- **Ubuntu 26.04.1**
  - manifest: `74913e4428d8046f9b48e538fd0f2e614b02d10ee18f1f8fadf66f392ca6ca0f`
  - media: `eeb52f61d45954338b49f004f6ddda5871ba6926e7969caad1975c1fa0a44d03`
  - record: `4c8c9abf7118fbe16e427d02565ce9b45c35ee208a7d8bf759787edf9270a111`

## Fedora first attempt

The first Fedora attempt built media at `bedd4d0` (manifest
`715a8de7019f456900f93f8d45e2ab17734464ff1fc4424dd43a172901576e0a`, media
`b86f796237db385a370fd9716b2d477cc770751144a4f421e41fdefef1f6b3f5`) from the then-shipped
`examples/fedora-operator.json`. Anaconda loaded the repository and stopped at its text hub, waiting
for input, with `Software selection` marked `Warning checking software selection`. No installation
began; the hub was still waiting after about an hour and the run was ended with SIGTERM.

That starter selected `@^minimal-environment`. The signed repository metadata's comps for the
Fedora 44 ppc64le Everything tree (`comps-Everything.ppc64le.xml.zst`) list, among others,
`custom-environment` and `server-product-environment`, and no `minimal-environment`; the Server
tree's comps list only those two. The hub's own error text was not captured. Issue #142 (PR #143)
changed the starter and example to `@^server-product-environment`, and the accepted Fedora run above
used that shipped example unmodified apart from the network, source and profile values.

## Boundary

This is emulator evidence for the Fedora, Rocky and Ubuntu operator-file examples and these inputs.
It does not prove that either installed system boots or accepts a login, that the operator files'
accounts and privileges behave as written, or anything on native PowerVM (#72). The RHEL operator
arm (#97) is outstanding.
