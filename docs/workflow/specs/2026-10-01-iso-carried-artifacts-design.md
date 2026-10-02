# ISO-carried Kickstart with a mirror-served installer

## Problem

The launcher fetches the Fedora kernel, the prepared initramfs, `.treeinfo`, `repomd.xml`, and the
Kickstart from a single `source` origin, then passes `inst.repo` on that same origin
(`assets/dracut/iso-chain-launch.sh` `download_artifact`, `fedora_command_line`). Two of those
files exist only because `prepare-fedora-source` built them. Every deployment therefore needs a
private HTTP server holding a Fedora tree beside them, and no public mirror can be used.

The Kickstart download is verified and then discarded, because Anaconda reads the copy embedded
in the prepared initramfs (`inst.ks=file:/iso-chain/ks.cfg`, ADR 0006).

Four further gaps block the first real POWER9 run (issue #6):

- **Real mode area.** Under PowerVM's hash MMU, kexec confines its segments to the real mode
  area, about 1 GiB. ADR 0005's bundle is 1,068,556,772 bytes, and the live partition refused it
  under both `kexec_file_load` and `kexec_load` (ADR 0011).
- **Drivers.** The launcher initramfs carries only virtio drivers (`DRACUT_DRIVERS`), so a PowerVM
  partition's `ibmveth` adapter and `ibmvscsi` optical drive are invisible to it.
- **Preparation input.** `prepare-fedora-source` reads the Server DVD, whose `.treeinfo` and
  `repomd.xml` differ from a public mirror's, so pinned digests cannot match a public repository.
- **Build host.** `prepare-initramfs` requires a ppc64le host, and the supported macOS path builds
  only the ISO.

Decision record: [ADR 0011](../../adr/0011-carry-installer-artifacts-on-the-launcher-iso.md).

## Contract

### Manifest version 4

Manifest v4 keeps v3's six top-level fields and exact-field validation. It changes the following:

- **`version`** must be the integer `4`. A v3 manifest fails with
  `manifest version: 3 is no longer supported; regenerate the profile with prepare-fedora-source`.
- **`source`** names only the Fedora repository origin. It uses HTTPS, or HTTP for loopback and
  controlled test servers, under the existing grammar.
- **Fedora artifacts.** Each profile's `kernel` and `initramfs` are Fedora's netinst `vmlinuz`
  and `initrd.img`, named by canonical URL path under `source`, with exact size and SHA-256.
- **Media path.** Each profile's `kickstart` path is a path on the ISO. It must match
  `^/profiles/[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$` with no `.` or `..` segment, which is a
  character set the launcher's `valid_path` accepts. Two profiles may name the same media path only
  with identical size and SHA-256.
- **`repository.path`** stays an origin-relative URL path. `.treeinfo` and `repodata/repomd.xml`
  keep their exact size and SHA-256.

The kernel command line keeps every v3 argument, including the three `profile_kickstart_*`
arguments, now naming the media path, and `iso_chain.config_sha256`. The whole line stays under
2,048 bytes. GRUB holds it in a top-level `iso_chain_args_<n>` variable, so each menu entry stays
under the 1,024 bytes Fedora's GRUB replays after a PowerVM CAS reboot.

### Preparation anchored on the signed netinst ISO

The command takes these arguments:

```text
prepare-fedora-source --iso NETINST --iso-sha256 HEX --tree DIR --repository-path PATH
    --kickstart FILE --minimum-memory-mib N --output OUT
```

They replace `--iso`/`--iso-sha256` on the Server DVD:

- `NETINST` is the Fedora 44 ppc64le netinst ISO.
- `HEX` is its SHA-256, which the operator takes from the signed text that `gpgv --output`
  extracts from Fedora's `CHECKSUM`, never from lines outside the signature. This is the same
  operator duty ADR 0005 assigns for the DVD.
- `DIR` holds `.treeinfo` and `repodata/repomd.xml` copied from the mirror tree that `PATH` names.

Preparation then runs these checks, in order:

1. Copy the ISO into the work directory under `OUT`'s parent while hashing it, bounded at 4 GiB,
   and require the digest `HEX`.
2. `.treeinfo` must name family `Fedora`, version `44`, arch `ppc64le`, and a variant in
   {`Everything`, `Server`}.
3. Its `[checksums]` section must carry `sha256:` entries for `images/boot.iso` and for the
   `images-ppc64le.kernel` and `images-ppc64le.initrd` paths. `images/boot.iso` must equal `HEX`,
   which binds the tree to that exact signed ISO.
4. Extract the kernel and initrd from the ISO with `xorriso` into the same work directory. Each
   must match its `.treeinfo` checksum. A missing entry or any mismatch fails before anything is
   published.
5. Publish `profiles/fedora-44/ks.cfg` and `profile.json`. The profile pins the kernel and initrd
   at `PATH/<treeinfo path>` with their extracted sizes and digests, sets `repository.path = PATH`,
   and pins `.treeinfo`/`repomd.xml` as copied. No image or repository tree is published.

The command makes no network request. It needs `xorriso`. On macOS it runs inside
`iso-chain-builder:44` through a documented `run` invocation.

Verified 2026-10-01:

- The `Fedora-Everything-44-1.7-ppc64le-CHECKSUM` signature checks with
  `RPM-GPG-KEY-fedora-44-primary`.
- The netinst SHA-256 `95e63afa…84ce` equals the mirror `.treeinfo` `images/boot.iso` entry.
- The images extracted from it equal the `.treeinfo` checksums.

### Build

`build` and `container-build` gain a required `--profiles DIR`. `build` handles each profile as
follows:

- It reads `DIR/<path>` for the profile's Kickstart.
- It checks the file's size and SHA-256 against the manifest, and stages it at its media path.
- Any mismatch fails before `grub2-mkrescue` runs.

The volume ID is `ISO_CHAIN_` and the first 16 hex digits of the manifest digest, uppercased.
Anaconda's bare `cdrom:<path>` takes the first optical drive holding that path; the label names
the verified ISO instead, and two ISOs share a label only when they share a manifest, and so a
Kickstart digest.

`container-build` mounts `DIR` read-only.

### Launcher

1. **Find the media.** After the existing configuration, adapter, profile, and memory gates, the
   launcher runs `udevadm settle`. It then tries to mount each existing `/dev/sr*` device
   read-only as iso9660 with `nodev,nosuid,noexec`, discarding the probe's stderr. It keeps the
   one device whose `/iso-chain/config.json` SHA-256 equals `iso_chain.config_sha256`.
   - Zero or several matches print `media: failed`.
   - So does any block device other than the match carrying its volume ID, as
     `blkid -c /dev/null -t LABEL=<volume ID> -o device` reports it, because Anaconda resolves
     the Kickstart by that label.
   - Otherwise it prints `media: passed`.
2. **Check the Kickstart.** It copies the Kickstart from the media into the existing `/run`
   workspace with exact size and SHA-256 checks, then unmounts. A wrong file reports
   `kickstart-size` or `kickstart-digest`.
3. **Fetch from the mirror.** It downloads the kernel, the initramfs, `.treeinfo`, and
   `repomd.xml`, in that order, with today's curl flags.
4. **Hand off.** The capacity check counts all five artifacts. `kexec` loads Fedora's unmodified
   kernel and initrd. The Anaconda command line takes
   `inst.ks=cdrom:LABEL=<volume ID>:<kickstart path>` in place of
   `inst.ks=file:/iso-chain/ks.cfg`, and Anaconda fetches stage2 through `inst.repo`.

`DRACUT_DRIVERS` gains `ibmveth ibmvscsi sr_mod isofs`. `DRACUT_TOOLS` gains `mount`, `umount`,
`cat`, and `blkid`. The shell tests can override the device glob with `ISO_CHAIN_MEDIA_DEVICES`.

### PowerVM example Kickstart

`assets/kickstart/fedora-44-powervm.ks` is the reference fixture `fedora-44-power9.ks` with one
difference: every disk directive (`ignoredisk`, `clearpart`, and each `part --ondisk`) names
`sda`, the first VIOS virtual SCSI disk, instead of `vda`. It destroys only that disk and writes
the same `installed-boot: passed boot_id=...` completion marker. `InstallTests` fails if the two
files differ in anything but that disk name.

### Container initramfs preparation

The new command is `container-prepare-initramfs --output-dir DIR [--engine NAME] [--image NAME]`.

- It runs `prepare-initramfs` inside `iso-chain-initramfs:44`.
- That image is built for `linux/ppc64le` from `Containerfile.initramfs`, using `Containerfile`'s
  pinned `fedora:44` index digest. The digest includes ppc64le (`docker manifest inspect`,
  2026-10-01). The image adds `dracut`, `kernel-core`, `kexec-tools`, `iproute`, `curl`,
  `systemd`, `util-linux-core`, `ca-certificates`, and `python3.14`.
- It publishes `DIR/vmlinuz` and `DIR/initramfs.img` from the image's single installed kernel.
  Zero or several installed kernels fail.
- `DIR` must exist, must not be the repository root, and must not already hold either file.
- `just build-initramfs-image` builds the image with the detected engine.

Emulation prerequisites, in the README:

- Docker Desktop on macOS arm64 is the verified host. On it,
  `docker run --platform linux/ppc64le busybox uname -m` printed `ppc64le` (2026-10-01).
- Podman needs `qemu-user-static` in its machine.
- Linux Docker needs a registered `binfmt_misc` ppc64le handler.
- Neither of the last two was run for this change.

### Local repository server

`serve-fedora-source` is unchanged. A local run serves an operator-held full copy of the same
Everything tree, sets `source` to that server, and sets `repository.path` to the tree's URL path.
An end-to-end QEMU run of that path is deferred (see Deferrals).

### Validation and evidence

- `validate-external-source` and its opt-in mirror test check the kernel, the initramfs,
  `.treeinfo`, and `repomd.xml`.
- Launcher HTTP evidence, both pre-install and install, expects exactly four launcher requests,
  kernel, initramfs, treeinfo, then repomd, followed by repository traffic. The
  Kickstart-request rule is removed.
- `verify-launcher-log` requires `media: passed` between memory and `artifacts: passed`, and
  treats `media: failed` as failure evidence.

## Failure model

1. **Actors and deployments.**
   - A local operator prepares and builds, on macOS arm64 with Docker Desktop or on x86_64 Linux.
   - The ISO boots in a QEMU pSeries POWER9 guest, or in a PowerVM POWER9 partition through a
     VIOS virtual optical device.
   - `source` is a public HTTPS Fedora mirror or a loopback or controlled test server.
2. **Invariants and assets.**
   - Only bytes whose size and SHA-256 are bound into the manifest digest reach `kexec`, and the
     Kickstart Anaconda reads is one the launcher verified on the same media.
   - Those bytes descend from a signed Fedora release ISO.
   - The kexec payload stays within PowerVM's real mode area.
   - There is no DHCP, no IPv6, no redirect, no alternate source or media device, and no silent
     profile change.
   - The disk is written only by the Kickstart.
3. **Accepted failure classes.**
   - `repomd.xml` is pinned only as fetched during preparation, not authenticated, and package
     payloads rely on Anaconda's repository checksums, as ADR 0007 already accepts.
   - The stage2 `install.img` comes from the mirror unpinned. The operator accepts this to keep
     the ISO minimal, and relies on an internal mirror in production (ADR 0011).
   - Mirror drift after preparation fails hard at boot, by design.
   - A transient mirror error fails the run, and the operator re-runs it. `dl.fedoraproject.org`
     returned two transient 404s on 2026-10-01, and retrying would not mask a real 404.
   - Emulated ppc64le builds are slow. That is a bounded wall-clock cost.
   - Each ISO binds one partition's network, so its size of about 100 MB is per partition.
4. **Covered elsewhere.**

   | Concern | Owner |
   |---|---|
   | Live PowerVM orchestration and HMC/VIOS mapping beyond the recorded run | epic #1 |
   | hmc-mcp REST faults | hmc-mcp #779 |
   | Other distributions | #7, #8, #9, #24, #25 |

### Threat model

- **Boundaries.**
  - Added: read-only media mounted inside the guest, and the operator-copied `.treeinfo` and
    `repomd.xml`.
  - Added on the build host: `container-prepare-initramfs` runs a container, as root under
    Docker, that sees the checkout read-only and the operator's `--output-dir` read-write. The
    operator chooses that directory and is trusted.
  - The HTTP origin supplies four pinned files, the unpinned stage2 runtime, and repository
    traffic.
- **Actors.** A network attacker or a compromised mirror, and a mistaken operator. The trusted
  parties are:
  - the operator's signature check of Fedora's `CHECKSUM`;
  - the VIOS media mapping.
- **Controls.**
  - **Signed anchor.** The ISO digest is checked against the operator-verified signature.
  - **Tree binding.** `.treeinfo` `images/boot.iso` must equal that digest, and the extracted
    images must equal the `.treeinfo` checksums.
  - **Media.** The media is identified by config digest equality and mounted read-only with
    `nodev,nosuid,noexec`. Anaconda is pointed at the same media by its digest-derived volume ID,
    so another optical drive holding the same Kickstart path is not read. The launcher refuses to
    continue when any other block device carries that volume ID.
  - **Artifacts.** Every launcher artifact is checked for size and SHA-256 before `kexec`.
  - **HTTP.** HTTP keeps the CA bundle, no redirects, and `--max-filesize`.
  - **Errors.** Error messages echo no tree values.
- **Out of scope.**
  - Firmware Secure Boot (ADR 0003).
  - Unauthenticated `repomd.xml` and the unpinned stage2 runtime, accepted above.
  - A VIOS administrator substituting the media between the launcher's check and Anaconda's read.
  - A substituted ISO whose config digest matches but whose Kickstart path holds an oversized
    file: the launcher copies it in full before the size check rejects it, so `/run` can fill
    before the run fails closed. `build` never stages such a file.

## Testing

- **Unit (`tests/test_iso_chain.py`).**
  - v4 parsing: v3 rejected with the exact message, the Kickstart media-path rule and its
    character set, and conflicting shared paths.
  - Command line carrying the media Kickstart, and menu entries under the CAS reboot buffer.
  - `build` staging only the Kickstart, and mismatch refused before `grub2-mkrescue` runs.
  - Netinst preparation: ISO digest, variant, a missing `boot.iso` or image checksum entry,
    `boot.iso` not equal to `--iso-sha256`, and an extracted-image mismatch, with `xorriso`
    faked. Plus a success case.
  - `container-prepare-initramfs` command shape and refusals.
  - External validation of four artifacts.
  - HTTP-evidence order, and the launcher-log `media` markers.
- **Shell (`tests/test_iso_chain_launch.sh`).** Fake `mount`, `umount`, and `udevadm` over
  directory media fixtures, covering:
  - one matching device, with no Kickstart request, the four downloads in order, and
    `inst.ks=cdrom:LABEL=<volume ID>:<path>`;
  - a matching device beside a foreign one, which is used;
  - zero, two, foreign-only, or unmountable devices, or a second device carrying the volume ID,
    giving `media: failed`;
  - a Kickstart size or digest mismatch on the media;
  - kernel and initramfs download, size, and digest failures.
- **Live.** The PowerVM run recorded in
  `docs/experiments/2026-10-01-powervm-iso-carried-kickstart.md` is the end-to-end proof for
  commit `7401c4b`. The later `blkid` volume-ID check has not run on PowerVM. The local container
  run of `container-prepare-initramfs` is recorded in the PR.

## Deferrals

| Item | Owner |
|---|---|
| End-to-end QEMU run of the local-server path, which needs `qemu-system-ppc64` and a full tree copy | #27 |
| GRUB CAS-reboot menu fix on a live PowerVM boot | #28 |
| The `blkid` volume-ID check on a live PowerVM boot, which the same boot exercises | #28 |
