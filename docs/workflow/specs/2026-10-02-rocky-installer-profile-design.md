# Rocky Installer Profile

## Problem

Manifest v4 accepts `fedora`/`44` and `ubuntu`/`26.04.1` profiles only (`_installer_profile` in
`scripts/iso_chain.py`). Issue #7 needs one POWER9 RHEL-family release that reaches its installer
over the manifest's static IPv4 and local HTTP, discovers the intended storage without partition
writes, never uses DHCP, and records exact media, digests, and required RAM. On 2026-10-02 the
operator chose Rocky Linux in place of RHEL, and accepted a local QEMU pSeries POWER9 run in place
of POWER9 hardware.

Decision record: [ADR 0013](../../adr/0013-hand-off-to-the-rocky-anaconda-installer.md).

## Contract

### Release and media

Rocky Linux 9.8, `Rocky-9.8-ppc64le-boot.iso`, 1,467,269,120 bytes, SHA-256
`bd0db737aeaede1817971cade75e72027dffe836ff983852ad940a6923775a70`. That digest is the line in
`isos/ppc64le/CHECKSUM` that `gpgv` verified against `CHECKSUM.asc` with the Rocky 2022 release key
`21CB256AE16FC54C6E652949702D426D350D275D` on 2026-10-02. It equals the `images/boot.iso` checksum
in `BaseOS/ppc64le/os/.treeinfo` on `download.rockylinux.org`.

### Manifest v4 profiles

The top-level fields, version `4`, the network grammar, and the Fedora and Ubuntu profiles are
unchanged.

- **`rocky`**, release `9.8`: exactly `distribution`, `release`, `kernel`, `initramfs`,
  `repository`, and `minimum_memory_mib`. These have Fedora's grammar, and there is no `kickstart`.
  `repository.path` must end in `/BaseOS/ppc64le/os`, or loading fails with
  `profiles.<name>.repository.path: must end in /BaseOS/ppc64le/os`.
- An unknown pair fails with
  `profiles.<name>.distribution/release: must be fedora/44, rocky/9.8, or ubuntu/26.04.1`.
- Rocky imposes no network subset: dracut carries every route and up to three DNS servers.

For Rocky, `_kernel_arguments` emits Fedora's repository, `.treeinfo`, and `repomd` arguments and
no Kickstart arguments. `build` stages nothing for Rocky.

### Preparation

```text
prepare-rocky-source --iso ISO --iso-sha256 HEX --tree TREE --repository-path PATH
    --minimum-memory-mib N --output OUT
```

1. Validate the arguments as `prepare-fedora-source` does. `PATH` must also end in
   `/BaseOS/ppc64le/os`.
2. Read `TREE/.treeinfo` through the treeinfo helper shared with Fedora, parameterized by label,
   identity, and variants. Identity is `Rocky Linux`/`9.8`/`ppc64le` and the variant is `BaseOS`.
   `[variant-AppStream] repository` must be present and equal `../../../AppStream/ppc64le/os`, with
   or without one trailing `/`. `images/boot.iso` must equal `HEX`. Every failure, a missing section
   included, reads `Rocky treeinfo: <reason>`.
3. Copy and hash the ISO, extract the kernel and initrd with `xorriso`, and match them to
   `.treeinfo`, all as Fedora does (the code is shared).
4. Publish `OUT` with no-replace publication. It holds only `profile.json`: a `rocky` profile pinning
   `PATH/ppc/ppc64/vmlinuz`, `PATH/ppc/ppc64/initrd.img`, `.treeinfo`, and `repomd.xml`. The same
   parser validates it before publication.

Like `prepare-fedora-source`, it needs `xorriso`; on macOS it runs in the `iso-chain-builder:44`
image. Only the x86_64 Linux arm is exercised by the proof.

### Launcher

- **Arguments.** `parse_arguments` accepts `rocky:9.8` with `valid_rocky_arguments`: Fedora's
  repository, `.treeinfo`, and `repomd` arguments, no live-ISO path, no Kickstart argument, and a
  repository path ending in `/BaseOS/ppc64le/os`. Any other mix prints `configuration: failed`.
- **Launch.** `launch_fedora` becomes `launch_anaconda`, and `fedora_command_line` becomes
  `anaconda_command_line`. With no Kickstart path, they skip the media search and the Kickstart
  copy, print no `media:` marker, and emit no `inst.ks=`. Everything else is Fedora's.
- **Failures.** The download, digest, capacity, and kexec markers are unchanged.

### Evidence

- **Canonical manifest.** `_manifest_data`, which both verifiers use to rebuild the config digest,
  emits `kickstart` only when the profile has one, so a Rocky profile round-trips to its canonical
  bytes.
- **`verify-launcher-log`.** It expects no `media: passed` for Rocky. The installer command line,
  after quote stripping, must carry no `inst.ks`/`ks` key and exactly one `inst.repo=`, equal to
  `<source><repository.path>`.
- **`verify-installer-evidence`.** It reuses Fedora's HTTP rule: the launcher pins first, and the
  kernel and initramfs once. For Rocky, later GETs may also fall under the sibling prefix,
  `repository.path` with its last three segments replaced by `AppStream/ppc64le/os/`. Any other path
  fails. The result line is Fedora's `intended-source: operator-reviewed`.
- **Optional Anaconda probes.** Anaconda's stage1 requests `<repository.path>/images/updates.img`
  and `<repository.path>/images/product.img`, which Rocky does not publish (both return 404 on
  `download.rockylinux.org`). For Rocky, those two paths may appear with status 404, once each. Every
  other record must be 200, as today. `_access_records` admits 404, and each HTTP rule rejects a 404
  outside its profile's allowance (none for Fedora or Ubuntu). An allowed 404 never counts as repository
  traffic, so it cannot satisfy the post-kexec corroboration check.
- **Other commands.** `validate-external-source` checks the four pins.
  `install-fedora` and `verify-fedora-install-evidence` already reject non-Fedora profiles.

### Proof

The proof runs `prepare-rocky-source`, `build`, and `smoke`: QEMU, TCG, pSeries, POWER9, a blank
20 GiB qcow2 under `-snapshot`, and a fresh `serve-source` access log and capture per run. The
launcher initramfs is rebuilt from this branch with `container-prepare-initramfs`, or in the
`~/src/vm-ppc64le` Fedora 44 guest.

- **Served tree.** The local tree mirrors Rocky's paths. It holds BaseOS's `.treeinfo`,
  `images/install.img`, kernel, initrd, and `repodata/`, and AppStream's `repodata/`.
  `validate-external-source` checks the four pins before the first run.
- **RAM sweep.** The sweep builds with `minimum_memory_mib` 1024 and records each arm's `MemTotal`
  and stop point. The published value is the smallest passing arm's `MemTotal`, rounded down to
  256 MiB. A fresh acceptance run at that arm must show the launcher markers, the network spoke with
  the matched adapter static at the manifest address, the installation source as the local
  repository, and the blank disk in Installation Destination. Without a Kickstart, Anaconda first
  offers VNC or text mode, and the operator picks text. The operator stops there, before
  "Begin Installation".
- **Pass condition.** The run passes `verify-installer-evidence` with a DHCP/IPv6-filtered capture.
  The summary goes to `docs/experiments/2026-10-02-rocky-installer.md`.

## Failure model

1. **Actors and deployments.**
   - A local operator on x86_64 Linux or macOS arm64 prepares and builds.
   - A QEMU pSeries POWER9 guest boots the ISO. PowerVM runs the same launcher, but this change does
     not prove it there.
   - `source` is a loopback or controlled test server.
2. **Invariants and assets.**
   - Only kernel and initrd bytes bound in the manifest digest, and descended from the signed boot
     ISO, reach `kexec`.
   - No DHCP, no IPv6, no alternate adapter, and no silent change of profile.
   - Neither the launcher nor the proof writes the disk.
   - Fedora and Ubuntu manifests, command lines, and evidence are unchanged.
3. **Accepted failure classes.**
   - **Unpinned stage2 and AppStream metadata** (ADR 0011 class).
   - **Installer-initiated external traffic.** Examples are mirrorlist or NTP lookups over the
     static route. They are outside `source`, so the HTTP evidence does not cover them; this is
     accepted for a proof that stops before installing.
   - **Slow emulation**: the cost is bounded.
4. **Covered elsewhere.**

   | Concern | Owner |
   |---|---|
   | Unattended install, Kickstart, disk guard, disk-boot default | #25 |
   | Native PowerVM run | separately authorized operator run |
   | Plain-HTTP restriction | #29 |

### Threat model

- **Boundaries.**
  - Added: the operator-supplied Rocky ISO and mirror `.treeinfo`, read by `xorriso` and
    `configparser`.
  - Widened: the manifest parser, the launcher argument parser, and the verifiers each accept one
    more profile shape.
- **Actors.** A compromised mirror or on-path attacker, and a mistaken operator. Trust sits with the
  operator's `gpgv` check.
- **Controls.**
  - The ISO digest must match before extraction, and `.treeinfo` is size-bounded.
  - Extracted images must equal the `.treeinfo` checksums.
  - Pins are checked by size and SHA-256 under today's curl flags.
  - Parsers enforce exact field sets, and the existing URL-path grammar keeps shell metacharacters
    off the command line.
  - Messages name fields, never values.
- **Out of scope.** Stage2 integrity (ADR 0011), Secure Boot (ADR 0003), and public mirrors.

## Testing

- **Unit.**
  - Rocky parsing: the field set, a stray `kickstart`, the path suffix, and the new release
    message.
  - Rocky kernel arguments, with Fedora and Ubuntu unchanged.
  - `build` stages no Kickstart for Rocky.
  - `prepare-rocky-source` with `xorriso` faked: success, digest mismatch, wrong identity, wrong
    or missing AppStream path, bad suffix, existing output.
  - Rocky launcher-log handoff: a stray `inst.ks`, and a missing or wrong `inst.repo`.
  - HTTP evidence: AppStream allowed, other paths rejected.
- **Shell.**
  - A Rocky command line yields four downloads, no mount, and exact kexec arguments without
    `inst.ks`.
  - A Kickstart argument, a live-ISO argument, or a bad suffix fails configuration.
  - A digest mismatch fails.
  - HTTP evidence: Rocky's two 404 probes allowed; a 404 elsewhere, or for Fedora, rejected.
  - `_manifest_data` round-trips a Rocky manifest to its canonical digest.
- **Live.** The proof above.
