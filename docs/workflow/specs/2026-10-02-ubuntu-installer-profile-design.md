# Ubuntu Installer Profile

## Problem

Manifest v4 accepts only `fedora`/`44` profiles (`_installer_profile` in `scripts/iso_chain.py`),
and the launcher hands off only to Anaconda (`fedora_command_line` in
`assets/dracut/iso-chain-launch.sh`). Issue #8 needs one POWER9 Ubuntu release that reaches its
installer over the manifest's static IPv4 settings and local HTTP, sees the intended storage
without writing partitions, and never uses DHCP. It must record exact media, digests, and the
RAM the installer needs.

The operator decided on 2026-10-02 that a local QEMU pSeries POWER9 run substitutes for a real
POWER9 partition.

Decision record: [ADR 0012](../../adr/0012-hand-off-to-the-ubuntu-live-server-installer.md).

## Contract

### Release and media

Ubuntu 26.04.1 LTS, `ubuntu-26.04.1-live-server-ppc64el.iso`, 1,647,902,720 bytes, SHA-256
`3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826`. The digest matches the
`SHA256SUMS` line that `gpgv` verified, against the "Ubuntu CD Image Automatic Signing Key (2012)"
key `843938DF228D22F7B3742BC0D94AA3F0EFE21092`, on 2026-10-02. `cdimage.ubuntu.com` serves it
without a redirect under `/ubuntu/releases/26.04.1/release/`. `netboot/ppc64el/linux` and
`netboot/ppc64el/initrd` are byte-identical to the ISO's `casper/vmlinux` (64,562,608 bytes,
`fdbac021…ae395f`) and `casper/initrd` (84,554,281 bytes, `3181671f…b4dcd4`).

### Manifest v4 profiles

The six top-level fields, the version `4`, and the network grammar are unchanged. A profile's exact
field set depends on its `distribution`:

- **`fedora`**, release `44`: unchanged.
- **`ubuntu`**, release `26.04.1`: exactly `distribution`, `release`, `kernel`, `initramfs`,
  `live_iso`, and `minimum_memory_mib`.
  - `kernel` and `initramfs` are `{path, size, sha256}` with canonical URL paths, as for Fedora.
  - `live_iso` is `{path, size, sha256}`. Its size is from 1 byte through 4 GiB. Its path is a
    canonical URL path ending in `.iso`, because casper accepts only `url=*.iso`.
- Any other distribution, or a known distribution with a different release, fails with
  `profiles.<name>.distribution/release: must be fedora/44 or ubuntu/26.04.1`.
- **Ubuntu network subset.** If any profile is `ubuntu`, then `network.routes` must hold exactly
  one route, `0.0.0.0/0`, and `network.dns` at most two servers. Otherwise loading fails with
  `profiles.<name>: ubuntu handoff supports only the default route and at most two DNS servers`.
  That message names only the profile key.

`_kernel_arguments` keeps every common argument, in today's order. For Fedora it is unchanged. For
Ubuntu it emits the kernel and initramfs path, size, and SHA-256 and then
`iso_chain.profile_live_iso_path=<path>` in place of the repository, `.treeinfo`, `repomd`, and
Kickstart arguments. The 2,048-byte limit and the per-entry GRUB variable are unchanged. `build`
stages a Kickstart only for Fedora profiles. `--profiles` stays required.

### Preparation

```text
prepare-ubuntu-source --iso ISO --iso-sha256 HEX --release-path PATH
    --minimum-memory-mib N --output OUT
```

The command runs these steps, in order:

1. Validate the arguments. `PATH` is a canonical URL path, `N` is from 1 through 65536, and `OUT`
   does not exist.
2. Copy the ISO into a work directory under `OUT`'s parent while hashing it, bounded at 4 GiB. The
   digest must be `HEX`, which the operator takes from the `gpgv`-verified `SHA256SUMS`.
3. Run `xorriso` to extract `/.disk/info`, `/casper/vmlinux`, and `/casper/initrd`. `.disk/info`
   must be at most 4 KiB and must start with `Ubuntu-Server 26.04.1 LTS` plus a space. It must
   also contain `- Release ppc64el` surrounded by spaces.
4. Publish `OUT/profile.json` with no-replace publication, as `prepare-fedora-source` does. It
   holds the `ubuntu` profile, which pins:
   - `kernel` at `PATH/netboot/ppc64el/linux`,
   - `initramfs` at `PATH/netboot/ppc64el/initrd`, and
   - `live_iso` at `PATH/ubuntu-26.04.1-live-server-ppc64el.iso`, with the extracted or copied
     sizes and digests and the given minimum memory.

   The profile is validated by the same parser before it is published.

The command makes no network request. A local server must serve those three paths byte-for-byte.

### Launcher

`parse_arguments` reads `iso_chain.profile_live_iso_path` and requires one distribution-specific
argument set:

- **Fedora** requires today's repository, `.treeinfo`, `repomd`, and Kickstart arguments, and no
  live-ISO path.
- **Ubuntu** requires a live-ISO path that `valid_path` accepts and that ends in `.iso`. It
  requires none of the Fedora-only arguments, exactly one route (the default), and at most two DNS
  servers.
- Any other combination prints `configuration: failed`.

`check_capacity` counts only the sizes the selected profile has, so the Fedora-only sizes count as
zero for Ubuntu.

`launch_ubuntu` creates the workspace, downloads `kernel` and then `initramfs` through
`download_artifact`, prints `artifacts: passed`, and kexecs with `ubuntu_command_line`:

```text
ip=<client>::<gateway>:<netmask>:<lpar>::off[:<dns1>[:<dns2>]] BOOTIF=01-<mac, ':' as '-'>
url=<source><live_iso_path> console=hvc0 ipv6.disable=1
```

`ip=` with `off` runs klibc `ipconfig` without DHCP. `BOOTIF` makes casper choose the adapter whose
MAC matches, whatever the Ubuntu kernel names it. It neither mounts the launcher media nor prints
a `media:` marker. The kexec markers, failure handling, and unload behaviour are unchanged.

### Local server

`serve-fedora-source` becomes `serve-source`, with the same arguments and behaviour. The handler,
server, and factory become `SourceRequestHandler`, `SourceHTTPServer`, and `_source_server`.

### Evidence

- **`verify-launcher-log`.** It expects `media: passed` only for Fedora profiles. For an Ubuntu
  profile, the installer's own kernel command line must carry, after quote stripping, exactly one
  each of `ip=`, `BOOTIF=`, and `url=`, equal to the values `ubuntu_command_line` produces from
  the manifest. Fedora's Kickstart check is unchanged.
- **`verify-fedora-evidence` becomes `verify-installer-evidence`.** The arguments, record fields,
  and digest binding are unchanged.
  - Ubuntu HTTP evidence must be exactly three GETs, in order: kernel, initramfs, and the live ISO,
    each once and at its manifest size.
  - The access-log byte bound rises from 2 GiB to 4 GiB.
  - The Ubuntu result lines replace `intended-source: operator-reviewed` with
    `installer-network: operator-reviewed`. The record's `intended_source_confirmed` flag then
    means that the operator saw subiquity's network screen list the matched adapter as static,
    with the manifest's address.
- **`validate-external-source`** checks the kernel, the initramfs, and the live ISO for Ubuntu.

### Proof

A fresh run uses `serve-source` on loopback, `build`, and `smoke` (QEMU 10.2.2, TCG, pSeries,
POWER9) with a blank 20 GiB qcow2 under `-snapshot`. Each memory arm boots in turn. The record
names the smallest of 2,048, 3,072, 4,096, and 6,144 MiB at which subiquity reaches its
guided-storage screen as the measured `minimum_memory_mib`. At that size, the acceptance run must
show all of the following:

- the launcher markers;
- subiquity's network screen showing the matched adapter as `static` with the manifest's address;
- the guided-storage screen listing the blank virtio disk.

The operator stops there. The run passes `verify-installer-evidence` with a DHCP/IPv6-filtered
capture and an unchanged disk hash. Its public summary goes to
`docs/experiments/2026-10-02-ubuntu-installer.md`.

## Failure model

1. **Actors and deployments.**
   - A local operator on x86_64 Linux or macOS arm64 prepares and builds.
   - The ISO boots in a QEMU pSeries POWER9 guest. A PowerVM partition runs the same launcher, but
     this change does not prove it there.
   - `source` is a loopback or controlled test server. A public HTTPS mirror is allowed by the
     grammar but not exercised.
2. **Invariants and assets.**
   - Only Ubuntu kernel and initrd bytes whose size and SHA-256 are bound into the manifest digest
     reach `kexec`. Those bytes descend from the signed ISO.
   - No DHCP, no IPv6, no alternate adapter, and no silent change of profile or distribution.
   - Neither the launcher nor this proof writes the disk.
   - Existing Fedora manifests, command lines, and evidence behave as before. The only change is the
     two renamed commands.
3. **Accepted failure classes.**
   - **Unpinned live ISO.** casper's BusyBox `wget` follows redirects, does not verify
     certificates, and runs no digest check (ADR 0012).
   - **Unsupported network shapes.** A manifest with extra static routes, or with three DNS
     servers, cannot carry an Ubuntu profile. It fails at load, which is actionable.
   - **External traffic.** Subiquity contacts the Ubuntu archive, NTP, and the snap store over the
     static route. That traffic is neither DHCP nor an alternate installation source, and the HTTP
     evidence covers only `source`.
   - **Slow emulation.** Wall-clock time under TCG is slow, but the cost is bounded.
4. **Covered elsewhere.**

   | Concern | Owner |
   |---|---|
   | Native PowerVM run and VIOS mapping window | epic #1, #28 |
   | Unattended install, disk selection, persistent network | #24 |
   | Target-bound producer output | #23 |
   | Plain-HTTP restriction | #29 |

### Threat model

- **Boundaries added.**
  - The operator-supplied Ubuntu ISO, read by `xorriso`.
  - The live ISO that casper fetches after kexec.
- **Boundaries widened.**
  - The manifest parser accepts a second profile shape.
  - The launcher's argument parser accepts the Ubuntu argument set.
  - The verifiers accept Ubuntu evidence.
- **Actors.** A network attacker or compromised mirror between the guest and `source`, and a
  mistaken operator. Trust sits with the operator's `gpgv` check of `SHA256SUMS`.
- **Controls.**
  - The ISO digest must equal the signed value before extraction. `.disk/info` is bounded and must
    match the release.
  - The kernel and initrd are pinned by size and SHA-256 and are fetched with today's curl flags:
    no redirect, CA bundle, and `--max-filesize`.
  - Manifest and launcher parsing use exact field sets. The live-ISO path uses the existing URL-path
    grammar plus the `.iso` suffix, so no shell metacharacter reaches the command line.
  - Error messages name fields, never values.
- **Out of scope.**
  - The unpinned live ISO and its transport, as accepted above.
  - Firmware Secure Boot (ADR 0003).
  - Public-mirror use (epic #1 orders local HTTP first).

## Testing

- **Unit.**
  - Ubuntu profile parsing: the exact field set, the `.iso` suffix, the size bound, the
    distribution/release message, and the network-subset rejection, each with `run` never called.
  - Ubuntu kernel arguments, and Fedora arguments unchanged.
  - `build` with an Ubuntu-only manifest stages no Kickstart.
  - `prepare-ubuntu-source` with `xorriso` faked: the digest mismatch, a wrong or oversized
    `.disk/info`, an existing output, and a success case.
  - Renamed parser commands.
  - Launcher-log and HTTP evidence for Ubuntu, including the wrong order, an extra path, and a
    missing or repeated `url=`, `ip=`, or `BOOTIF=`.
  - External validation of three artifacts.
- **Shell.**
  - An Ubuntu command line yields two downloads and the exact kexec arguments, with and without DNS.
  - Missing, extra, or Fedora-mixed arguments fail configuration.
  - A non-`.iso` path fails, as do a second route and a third DNS server.
  - A kernel or initrd digest mismatch fails.
- **Live.** The proof above.

## Deferrals

| Item | Owner |
|---|---|
| Native POWER9 PowerVM run of the Ubuntu profile | epic #1 (separately authorized live work) |
| casper over a public HTTPS mirror (BusyBox TLS) | epic #1 public-mirror goal |
