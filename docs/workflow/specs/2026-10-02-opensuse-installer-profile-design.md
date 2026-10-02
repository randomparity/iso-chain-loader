# openSUSE Installer Profile

## Problem

Manifest v4 accepts `fedora`/`44`, `rocky`/`9.8`, and `ubuntu`/`26.04.1` profiles only
(`_installer_profile` in `scripts/iso_chain.py`). Issue #9 needs one POWER9 SUSE-family release.
It must reach its installer over the manifest's static IPv4 and local HTTP, discover the intended
storage without partition writes, never use DHCP, and record exact media, digests, and required RAM.
On 2026-10-02 the operator made three choices: openSUSE Leap 15.6 in place of SLES, operator-reviewed
installer evidence with no credential on the installer command line, and a local QEMU pSeries
POWER9 run in place of POWER9 hardware.

Decision record: [ADR 0014](../../adr/0014-hand-off-to-the-opensuse-linuxrc-installer.md).

## Contract

### Release and media

openSUSE Leap 15.6, Build710.3, the `distribution/leap/15.6/repo/oss` tree. Its `CHECKSUMS`
(72,410 bytes) passed `gpgv` against `CHECKSUMS.asc` with the openSUSE Project Signing Key
`AD485664E901B867051AB15F35A2F86E29B700A4` on 2026-10-02. It lists:

| Path | Size | SHA-256 |
|---|---|---|
| `boot/ppc64le/linux` | 50,387,704 | `de40d328d32fe24139d0ef48c4bbed71c7f48e282954ba4aa941c5a115c519b3` |
| `boot/ppc64le/initrd` | 198,543,156 | `adc47c075383454a0af39262ae96151a100a53f8a2c751b525d3aeff269ff449` |
| `media.1/products` | 23 | `19a69528609a145d6a5b404bca8cb73041fe2ce1d705fe634043fe101840113e` |

`media.1/products` is the single line `/ openSUSE-Leap 15.6-1`. `gpg --show-keys` reports that key
as expired on 2026-06-19; `gpgv` still exits 0, and the spike's console shows no expiry warning.

### Manifest v4 profiles

The top-level fields, version `4`, the network grammar, and the Fedora, Rocky, and Ubuntu profiles
are unchanged.

- **`opensuse`**, release `15.6`: exactly `distribution`, `release`, `kernel`, `initramfs`,
  `repository`, and `minimum_memory_mib`. `kernel` and `initramfs` have Fedora's grammar.
  `repository` is exactly `{path}`, a canonical URL path.
- An unknown pair fails with
  `profiles.<name>.distribution/release: must be fedora/44, opensuse/15.6, rocky/9.8, or
  ubuntu/26.04.1`.
- **openSUSE network subset.** If any profile is `opensuse`, then `network.routes` must be exactly
  the one route `0.0.0.0/0` and `network.dns` must hold at most one server. Otherwise loading fails
  with `profiles.<name>: opensuse handoff supports only the default route and at most one DNS
  server`.

For openSUSE, `_kernel_arguments` emits `iso_chain.profile_repository_path=<path>` and no
`.treeinfo`, `repomd`, Kickstart, or live-ISO argument. `build` stages nothing for openSUSE. The
`Repository` dataclass keeps `treeinfo` and `repomd`, which become `None` for openSUSE.
`_manifest_data` emits only `path` for such a repository, so an openSUSE manifest round-trips to
its canonical bytes.

### Preparation

```text
prepare-opensuse-source --checksums FILE --tree TREE --repository-path PATH
    --minimum-memory-mib N --output OUT
```

1. Validate the arguments: `FILE` is a regular file, `TREE` a directory, `PATH` a canonical URL
   path, `N` from 1 through 65536, and `OUT` absent. These checks precede any read of the tree.
2. Read `FILE`, bounded at 1 MiB. Every non-empty line must be `<64 lower-case hex>  <path>`, two
   spaces between them, with no path repeated. The entries for `boot/ppc64le/linux`,
   `boot/ppc64le/initrd`, and `media.1/products` must be present. Every failure reads
   `openSUSE CHECKSUMS: <reason>`.
3. `TREE/media.1/products`, bounded at 4 KiB, must hash to its entry and equal
   `/ openSUSE-Leap 15.6-1\n`; otherwise `openSUSE tree: not the Leap 15.6 repository`.
4. `TREE/boot/ppc64le/linux` and `TREE/boot/ppc64le/initrd`, each bounded at 2 GiB, must hash to
   their entries; otherwise `openSUSE tree: <file> does not match CHECKSUMS`. A missing or
   non-regular file reads `openSUSE tree <relative path>: unavailable` (or `must be a regular
   file`).
5. Publish `OUT` with no-replace publication. It holds only `profile.json`: an `opensuse` profile
   pinning `PATH/boot/ppc64le/linux` and `PATH/boot/ppc64le/initrd`, with `repository.path` `PATH`
   and the given minimum memory. The same parser validates it before publication.

The command runs no subprocess and makes no network request. The tool cannot check the signature;
it relies on the operator's `gpgv` run, as `prepare-fedora-source` relies on a digest the
operator copied from signed text.

### Launcher

- **Arguments.** `parse_arguments` accepts `opensuse:15.6` with `valid_opensuse_arguments`: a
  repository path that `valid_path` accepts; no `.treeinfo`, `repomd`, Kickstart, or live-ISO
  argument; exactly one route (the default); and at most one DNS server. Any other mix prints
  `configuration: failed`.
- **Capacity.** `check_capacity` is unchanged; the absent Fedora sizes count as zero.
- **Launch.** `launch_opensuse` creates the workspace, downloads `kernel` and then `initramfs`
  through `download_artifact`, prints `artifacts: passed`, and kexecs with
  `opensuse_command_line`:

  ```text
  ifcfg=<mac>=<address>,<gateway>[,<dns>] hostname=<lpar> install=<source><repository_path>
  textmode=1 self_update=0 console=hvc0 ipv6.disable=1
  ```

  `<address>` is the manifest's CIDR address. linuxrc matches the `ifcfg` device by hardware
  address (`match_netdevice` in linuxrc's `net.c`) and writes a static configuration, so it never
  starts DHCP on that adapter. `self_update=0` stops YaST from fetching an installer update. It
  prints no `media:` marker, and the kexec markers and failure handling are unchanged.

### Evidence

- **Console format.** The openSUSE kernel prints a caller field, as in
  `[    0.000000][    T0] Kernel command line: ...`. For an openSUSE profile only, the installer's
  `Kernel command line` reader accepts an optional `[ T<n>]` or `[ C<n>]` field after the
  timestamp; the launcher line and other profiles keep today's grammar.
- **`verify-launcher-log`.** It expects no `media: passed` for openSUSE. After quote stripping, the
  installer command line's whole argument list must equal `opensuse_command_line`'s output. linuxrc
  ignores case and `-`, `_`, and `.` in option names and has aliases such as `repo` and
  `insecure` (`strcasecmpignorestrich` and the key table in linuxrc's `file.c`), so a closed
  comparison replaces a key filter. After `kexec-exec: started`, the console must hold exactly one
  `IP addresses:` line, and the next line must be the manifest address without its prefix length.
- **Access log.** `_access_records` keeps rejecting `HEAD` by default. `verify-installer-evidence`
  admits `HEAD` with a 200 status and 0 bytes for an openSUSE profile only.
- **HTTP rule for openSUSE.** The first two records are 200 GETs of the kernel and then the
  initramfs at their manifest sizes, and no later record names either pin. Every later request is
  under `<repository.path>/`, and at least one later 200 GET corroborates the repository. These ten
  paths below `<repository.path>/` may appear only as 404, once each: `content`,
  `boot/ppc64le/yast2-trans-en_US.rpm`, `license.tar.gz`, `media.1/info.txt`, `part.info`,
  `README.BETA`, `autoinst.xml`, `driverupdate`, `add_on_products.xml`, and `add_on_products`. Any
  other 404, and any 200 for one of them, fails. The result line is
  `intended-source: operator-reviewed`.
- **Other commands.** `validate-external-source` checks the two pins. `install-fedora` and
  `verify-fedora-install-evidence` already reject non-Fedora profiles.

### Proof

The proof runs `prepare-opensuse-source`, `build`, and `smoke`: QEMU, TCG, pSeries, POWER9, a
blank 20 GiB qcow2 under `-snapshot`, and a fresh `serve-source` access log and capture per run.
The launcher initramfs is rebuilt from this branch with `container-prepare-initramfs`.

- **Served tree.** A local tree under `distribution/leap/15.6/repo/oss/` holds `CHECKSUMS` and its
  signature, `media.1/`, `repodata/`, the signing keys, `control.xml`, and `boot/ppc64le/`'s
  `linux`, `initrd`, `config`, `common`, `root`, `bind`, `control.xml`, and
  `cracklib-dict-full.rpm`. `validate-external-source` checks the two pins before the first run,
  against its own `serve-source` instance and access log.
- **RAM sweep.** As for Rocky: the build uses `minimum_memory_mib` 1024, and each arm records its
  `MemTotal` and stop point. The launcher's `/run` gate (kernel, initrd, and 1 GiB: 1,322,672,684
  bytes) is expected to bind near 6.4 GiB, so the arms are 6,144, 6,656, and 7,168 MiB. The
  published value is the smallest passing arm's `MemTotal`, rounded down to 256 MiB. A sweep with
  no passing arm ends the proof without publishing a value.
- **Acceptance run.** At that arm, a fresh run must show the launcher markers and linuxrc's `IP
  addresses:` line with the manifest address. YaST must download from the local repository. The
  operator answers No to "Activate online repositories", selects the Server role, and stops at
  Suggested Partitioning, which must list the blank virtio disk. No change is accepted. Any linuxrc
  digest or signature dialog, and any YaST signature or key warning, fails the run, and the record
  reports what was shown.
- **Pass condition.** The run passes `verify-installer-evidence` with a DHCP/IPv6-filtered capture
  and an unchanged disk hash. The summary goes to `docs/experiments/2026-10-02-opensuse-installer.md`.

## Failure model

1. **Actors and deployments.**
   - A local operator on x86_64 Linux or macOS arm64 prepares and builds.
   - A QEMU pSeries POWER9 guest boots the ISO. PowerVM runs the same launcher, but this change does
     not prove it there.
   - `source` is a loopback or controlled test server.
2. **Invariants and assets.**
   - Only kernel and initrd bytes bound in the manifest digest, and listed in the signed
     `CHECKSUMS`, reach `kexec`.
   - No DHCP, no IPv6, no alternate adapter, and no silent change of profile.
   - Neither the launcher nor the proof writes the disk.
   - Fedora, Rocky, and Ubuntu manifests, command lines, and evidence are unchanged.
3. **Accepted failure classes.**
   - **Package metadata beyond the pins.** YaST checks `repomd.xml.asc` itself; this project does
     not pin it.
   - **Installer-initiated external traffic.** In the spike, YaST fetched release notes from
     `doc.opensuse.org` over the static route; this design does not disable that. It is outside
     `source`, so the HTTP evidence does not cover it.
   - **End-of-life release.** Leap 15.6 gets no updates; the proof stops before installing.
   - **Unsupported network shapes.** Extra routes or a second DNS server fail at load.
   - **Slow emulation.** The cost is bounded.
4. **Covered elsewhere.**

   | Concern | Owner |
   |---|---|
   | Unattended AutoYaST install, SSH keys, disk-boot default | follow-up under epic #1 |
   | Native PowerVM run | epic #1's real-P9 success criterion, a separately authorized operator run (related: #28) |
   | Plain-HTTP restriction and public mirrors | #29 |

### Threat model

- **Boundaries.**
  - Added: the operator-supplied `CHECKSUMS` and tree files, read by `prepare-opensuse-source`.
  - Widened: the manifest parser, the launcher argument parser, and the verifiers each accept one
    more profile shape; the access-log reader admits `HEAD` for openSUSE.
- **Actors.** A compromised mirror or on-path attacker, and a mistaken operator. Trust sits with
  the operator's `gpgv` check and with linuxrc's digest checks.
- **Controls.**
  - `CHECKSUMS` is bounded and strictly parsed; tree files are bounded, size-checked, and hashed.
  - Pins are checked by size and SHA-256 under today's curl flags.
  - Parsers enforce exact field sets, and the URL-path grammar keeps shell metacharacters off the
    command line.
  - A mirror-served `autoinst.xml` is not in the signed digests, so linuxrc's secure mode stops for
    an operator decision (`url.c`, `digests_verify`), which fails the proof. The HTTP evidence also
    rejects a 200 for it.
  - The installer command line is compared whole, so `insecure=`, `repo=`, or a respelled option
    cannot be added unseen.
  - Messages name fields, never values.
- **Out of scope.** Firmware Secure Boot (ADR 0003) and public mirrors.

Tests are listed per task in the implementation plan.
