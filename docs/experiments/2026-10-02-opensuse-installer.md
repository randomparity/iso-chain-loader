# openSUSE Installer VM Experiment

Date: 2026-10-02

## Result

A QEMU pSeries/POWER9 guest booted the optical launcher, configured only the declared static IPv4
interface, and fetched the two openSUSE Leap 15.6 pins from a local `serve-source` server: the
repository's `boot/ppc64le/linux` and `boot/ppc64le/initrd`. It verified each pin's size and
SHA-256 and kexecd into linuxrc on the Leap kernel 6.4.0-150600.21-default. linuxrc configured
`eth0` from `ifcfg=`, printed the manifest address under `IP addresses:`, loaded the installation
system from the same server, and started YaST. In the same run, the operator saw the following:

- the license agreement, with no linuxrc digest dialog and no YaST signature or key warning;
- the "Activate online repositories now?" prompt, answered No;
- the System Role screen, where the operator selected Server;
- Suggested Partitioning, proposing a new GPT, PReP, root, and swap layout on `/dev/vda`, the blank
  20 GiB virtio disk.

The operator stopped there and accepted no change. The run passed `verify-installer-evidence`.
Native PowerVM was not run, so this proves the emulator path only.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  and two CPUs, through `smoke`. The guest used QEMU's user-mode network, its documented default
  addresses, and the MAC `52:54:00:12:34:56`.
- **openSUSE media.** The `distribution/leap/15.6/repo/oss` tree, Build710.3. `gpgv` verified
  `CHECKSUMS.asc` over `CHECKSUMS` (72,410 bytes, SHA-256 `7cde59a3…cd9c`) with key
  `AD485664E901B867051AB15F35A2F86E29B700A4`. `gpg --show-keys` reports that key as expired on
  2026-06-19; `gpgv` still exited 0.
- **Pinned artifacts.** `prepare-opensuse-source` checked `media.1/products` against `CHECKSUMS`
  and pinned:
  - `boot/ppc64le/linux`: 50,387,704 bytes,
    `de40d328d32fe24139d0ef48c4bbed71c7f48e282954ba4aa941c5a115c519b3`;
  - `boot/ppc64le/initrd`: 198,543,156 bytes,
    `adc47c075383454a0af39262ae96151a100a53f8a2c751b525d3aeff269ff449`.
- **Served tree.** The tree mirrored `download.opensuse.org` paths below
  `distribution/leap/15.6/repo/oss/`: `CHECKSUMS` and its signature, `media.1/`, `repodata/`, the
  signing keys, `control.xml`, and `boot/ppc64le/`'s `linux`, `initrd`, `config`, `common`,
  `root`, `bind`, `control.xml`, and `cracklib-dict-full.rpm`.
  `validate-external-source`, run against its own loopback server and access log, matched both
  pins.
- **Launcher build.** Scripts at commit `57d9491`, whose launcher assets equal commit `7c2dd57`'s.
  The launcher kernel was Fedora 7.2.8-200.fc44 with an initramfs from the `iso-chain-initramfs:44`
  image; its launcher script, service, and target were byte-compared with the commit's. The
  acceptance ISO was 109,830,144 bytes, SHA-256
  `db2c10cd997bfa5b966131110d1593578adb4dac364890a26fad5503c9fdebc3`.
- **Manifest.** The acceptance manifest's canonical digest was
  `f7fd01cde686b8cafe80a85861aa5d20ffbf9bfb941b7e7a800a4cbf50f05209`, with one default route and
  one DNS server. Raw manifests, console logs, access logs, captures, and disks remain in private
  storage.
- **Build-host deviations.** These are the same as the Rocky record's. Both container commands
  ran with `--security-opt label=disable`, and the initramfs build used a copy of `scripts/` and
  `assets/` taken with `git archive`.

## Memory

The sweep profile set `minimum_memory_mib` to 1024, so that only the launcher and installer could
stop an arm. The launcher needs `/run` space for the kernel and initrd plus 1 GiB, which is
1,322,672,684 bytes.

| QEMU `-m` | `MemTotal` | `/run` available | Stop point |
|---|---|---|---|
| 6,144 MiB | not printed | below 1,322,672,684 bytes | launcher `run-space: failed` |
| 6,656 MiB | 6,529 MiB | 1,355,284,480 bytes | YaST started |
| 7,168 MiB | 7,041 MiB | 1,462,632,448 bytes | YaST started |

The smallest passing arm's `MemTotal`, rounded down to a multiple of 256 MiB, gives the published
`minimum_memory_mib` of 6,400. As for Rocky, the launcher's `/run` gate sets this floor, not the
installer.

## Evidence

The acceptance run at 6,656 MiB used the 6,400 MiB profile and its own server, access log, disk,
and capture.

- **Console.** The Leap kernel printed its command line with a caller field, exactly as
  `opensuse_command_line` builds it:
  `ifcfg=<mac>=<address>,<gateway>,<dns> hostname=<lpar> install=<source><path> textmode=1
  self_update=0 console=hvc0 ipv6.disable=1`. linuxrc printed `IP addresses:` followed by the
  manifest address.
- **Access log.** It held 45 requests. The first two were the pins in order, each at its pinned
  size. The ten optional paths the specification lists each returned 404 once. One `HEAD` of
  `repodata/repomd.xml` returned 200 with no body. Every other request was a 200 `GET` under the
  repository path, including `CHECKSUMS`, the inst-sys parts, and the repository metadata.
- **Capture.** A derivative of the capture keeping only IPv6, DHCP, and BOOTP packets held only its
  header. Outside `source` and the user-mode DNS server, the guest opened three HTTP and three
  HTTPS connections to `doc.opensuse.org`, whose address it resolved through DNS. This is YaST's
  release-notes fetch, which the specification's failure model accepts.
- **Verifier.** `verify-installer-evidence` returned:

```text
manifest: passed
memory: passed
http-evidence: passed
disk-unchanged: passed
dhcp-ipv6-filter: absent
capture-provenance: operator-reviewed
same-run: operator-reviewed
installer-readiness: operator-reviewed
storage-visibility: operator-reviewed
intended-source: operator-reviewed
```

`verify-launcher-log` re-derives the whole installer command line and the `IP addresses:` line
from the console. `intended-source` records that YaST built its cache from the local repository
`openSUSE-Leap-15.6-1` with online repositories declined.

## Controlled fault: a served autoinst.xml

A separate 6,656 MiB run served a 250-byte `autoinst.xml` holding only AutoYaST's `confirm` flag in
the repository root. linuxrc fetched it (200) with no digest prompt, and YaST showed "Preparing
System for Automated Installation". The operator stopped the run there; the disk hash was
unchanged. Its access log would fail `verify-installer-evidence`, which admits `autoinst.xml` only
as a 404. ADR 0014 records the resulting trust in `source`.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. PowerVM optical behaviour, real-P9
  storage, and firmware policy need a separately authorized run.
- `smoke` runs QEMU with `-snapshot`, so the unchanged disk hash shows only that the backing file
  was untouched. The absence of partition writes rests on the operator-reviewed stop at Suggested
  Partitioning.
- The source was a loopback HTTP server holding a partial mirror. A public HTTPS mirror was not
  tested, and neither was a package installation, which needs the package directories.
- Leap 15.6 reached end of life on 2026-04-30. The run used it only to reach storage.
