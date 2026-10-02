# ISO-carried installer artifacts with a public repository

## Problem

The launcher fetches the Fedora kernel, the prepared initramfs, `.treeinfo`, `repomd.xml`, and the
Kickstart from one `source` origin, then passes `inst.repo` on that same origin
(`assets/dracut/iso-chain-launch.sh` `download_artifact`, `fedora_command_line`). Two of those
files exist only because `prepare-fedora-source` built them, so every deployment needs a private
HTTP server holding a Fedora tree beside them, and no public mirror can be used. The Kickstart
download is verified and then discarded, because Anaconda reads the copy embedded in the prepared
initramfs (`inst.ks=file:/iso-chain/ks.cfg`, ADR 0006).

Three further gaps block the first real POWER9 run (issue #6):

- the launcher initramfs carries only virtio drivers (`DRACUT_DRIVERS`), so a PowerVM partition's
  `ibmveth` adapter and `ibmvscsi` optical drive are invisible to it;
- `prepare-fedora-source` reads the Server DVD, whose `.treeinfo` and `repomd.xml` differ from any
  mirror's, so pinned digests cannot match a public repository;
- `prepare-initramfs` requires a ppc64le host, and the supported macOS path builds only the ISO.

Decision record: [ADR 0011](../../adr/0011-carry-installer-artifacts-on-the-launcher-iso.md).

## Contract

### Manifest version 4

Manifest v4 keeps v3's six top-level fields and exact-field validation. Changes:

- `version` must be the integer `4`. A v3 manifest fails with
  `manifest: version 3 is no longer supported; regenerate the profile with prepare-fedora-source`.
- `source` names the Fedora repository origin only: HTTPS, or HTTP for loopback and controlled
  test servers, under the existing grammar.
- Each profile's `kernel`, `initramfs`, and `kickstart` paths are media paths. Each must be
  `/profiles/<directory>/<file>`, exactly two canonical segments under `/profiles`, and the
  three paths within one profile must be distinct. Two profiles may name the same media path only
  with identical size and SHA-256. Otherwise the manifest is rejected, because one ISO file cannot
  satisfy both.
- `repository.path` stays an origin-relative URL path. `.treeinfo` and `repodata/repomd.xml` keep
  exact size and SHA-256.

The kernel command line drops the three `profile_kickstart_*` arguments. Everything else stays,
including `iso_chain.config_sha256`, and it stays under the 2,048-byte limit.

### Preparation from a mirror tree

`prepare-fedora-source --tree DIR --repository-path PATH --kickstart FILE --minimum-memory-mib N
--output OUT` replaces `--iso`/`--iso-sha256`. `DIR` is an operator-fetched copy of at least five
files from one mirror tree: `.treeinfo`, `repodata/repomd.xml`, and the three files `.treeinfo`
names under `images-ppc64le.kernel`, `images-ppc64le.initrd`, and `stage2.mainimage`.

- `.treeinfo` must name family `Fedora`, version `44`, arch `ppc64le`, and a variant in
  {`Everything`, `Server`}.
- Its `[checksums]` section must carry a `sha256:` entry for each of those three paths, and each
  file must match it. A missing entry or a mismatch fails.
- The output holds `profiles/fedora-44/{vmlinuz,initramfs.img,ks.cfg}` and `profile.json`. No
  extracted repository is published. `PATH` becomes `repository.path`.

The command makes no network request. Copying the tree is the operator's step, and its result is
checked against `.treeinfo`.

### Build

`build` and `container-build` gain a required `--profiles DIR`. For every profile, `build` reads
`DIR/<path>` for its kernel, initramfs, and Kickstart, checks size and SHA-256 against the
manifest, and stages each file at its media path. Any mismatch fails before `grub2-mkrescue` runs.
`container-build` mounts `DIR` read-only.

### Launcher

1. After the existing configuration, adapter, profile, and memory gates, the launcher settles
   udev. It mounts each `/dev/sr*` device read-only as iso9660 with `nodev,nosuid,noexec`, and
   keeps the one whose `/iso-chain/config.json` SHA-256 equals `iso_chain.config_sha256`. Zero or
   several matches print `media: failed`. Exactly one prints `media: passed`.
2. It copies the kernel and initramfs from the media into the existing `/run` workspace, checking
   exact size and SHA-256 as `download_artifact` does, then unmounts the media.
3. It downloads only `.treeinfo` and `repomd.xml`, with today's curl flags (no redirects, CA
   bundle, `--max-filesize`). The Kickstart download is gone.
4. The capacity check counts kernel, initramfs, treeinfo, and repomd bytes. `kexec` and the
   Anaconda command line are unchanged: `inst.ks=file:/iso-chain/ks.cfg` and
   `inst.repo=<source><repository.path>`.

`DRACUT_DRIVERS` adds `ibmveth ibmvscsi sr_mod isofs`, and `DRACUT_TOOLS` adds `mount` and
`umount`. The device glob can be overridden as `ISO_CHAIN_MEDIA_DEVICES` for the shell tests only,
matching the existing `ISO_CHAIN_*` injection points.

### Container initramfs preparation

`container-prepare-initramfs --output-dir DIR [--engine NAME] [--image NAME]` runs
`prepare-initramfs` inside `iso-chain-initramfs:44`, an image built for `linux/ppc64le` from
`Containerfile.initramfs`. That image uses the same pinned `fedora:44` index digest as
`Containerfile` and adds `dracut`, `kernel-core`, `kexec-tools`, `iproute`, `curl`, and
`systemd`. The container publishes `DIR/vmlinuz` and `DIR/initramfs.img` from the image's single
installed kernel. Zero or several kernels fail. `DIR` must exist and must not already hold either
file. A new `just build-initramfs-image` recipe builds the image with the engine
`build-image` detects. On a non-ppc64le host the engine emulates ppc64le (verified:
`docker run --platform linux/ppc64le busybox uname -m` printed `ppc64le` on macOS arm64,
2026-10-01).

### Validation and evidence

- `validate-external-source` checks `.treeinfo` and `repomd.xml` only.
- The launcher's HTTP evidence (`_verify_install_http_requests` and the pre-install verifier)
  expects exactly two launcher requests, treeinfo then repomd, followed by repository traffic.
  The Kickstart-request rule is removed.
- `verify-launcher-log` requires `media: passed` before `artifacts: passed`.

## Failure model

1. **Actors and deployments.** A local operator on macOS arm64 or x86_64 Linux prepares and
   builds. The ISO boots in a QEMU pSeries POWER9 guest, or in a PowerVM POWER9 partition through
   a VIOS virtual optical device. The mirror is a public HTTPS Fedora mirror or a loopback test
   server.
2. **Invariants and assets.** Only bytes whose size and SHA-256 are bound into the manifest digest
   reach `kexec`. There is no DHCP, no IPv6, no redirect, no alternate source, no alternate media
   device, and no silent profile change. The disk is written only by the Kickstart.
3. **Accepted failure classes.**
   - The repository's package payloads beyond `repomd.xml` are not pinned by the launcher.
     Anaconda's own repository checksums and Fedora's package signatures hold them, as ADR 0007
     already accepts.
   - Mirror content drifting after preparation causes a hard digest failure at boot. That is the
     intended no-fallback outcome.
   - Emulated ppc64le preparation is slow. Its cost is bounded wall-clock time, not correctness.
4. **Covered elsewhere.** The live run and HMC/VIOS mapping are owned by #6. hmc-mcp REST faults
   are owned by hmc-mcp #779. Other distributions are owned by #7, #8, #9, #24, and #25.

### Threat model

- **Boundaries.** This change adds one boundary: read-only media mounted inside the guest. It
  narrows one: the HTTP origin now supplies only two pinned files plus repository traffic. Local
  preparation of the copied tree is unchanged in kind.
- **Actors.** A network attacker or a compromised mirror, and a mistaken operator. The operator
  and the VIOS media mapping are trusted.
- **Controls.** The media is identified by config digest equality and mounted read-only,
  `nodev,nosuid,noexec`. Every executed artifact is checked for size and SHA-256 before `kexec`.
  HTTP keeps the CA bundle, no redirects, and `--max-filesize`. `.treeinfo` checksums gate
  preparation. Error messages echo no paths or values from the tree.
- **Out of scope.** Firmware Secure Boot and signed GRUB, as in ADR 0003. A malicious VIOS
  administrator substituting media while it is mounted.

## Testing

- **Unit (`tests/test_iso_chain.py`).**
  - v4 parsing: v3 rejected, the media-path rule, duplicate paths.
  - Command-line content: no Kickstart arguments, still within the length limit.
  - `build`: staging, and digest or size mismatch with `run.assert_not_called()`.
  - Tree preparation: variant set, missing checksum entry, checksum mismatch, Everything success.
  - `container-prepare-initramfs` command shape and existing-output refusal.
  - External validation of two artifacts.
  - HTTP-evidence order and launcher-log `media: passed`.
- **Shell (`tests/test_iso_chain_launch.sh`).** Fake `mount`/`umount`, and media devices built as
  directories:
  - one matching device: pass, with no Kickstart request;
  - zero matching devices: `media: failed`;
  - two matching devices: `media: failed`;
  - kernel size mismatch on the media;
  - initramfs digest mismatch on the media.
- **Live.** The first POWER9 run under #6 is the end-to-end proof. This change records no live
  result.
