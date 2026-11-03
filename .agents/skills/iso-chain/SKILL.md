---
name: iso-chain
description: Use when choosing, preparing, building, validating or verifying iso-chain launcher media for ppc64le POWER9 in this repository, or when reading its JSON reports and media results. Do not use for HMC, VIOS or LPAR operations; those belong to hmcpctl.
---

# iso-chain tasks

This skill routes an agent to the right `scripts/iso_chain.py` command and the guide that owns
it. The [README](../../../README.md) and [guides](../../../docs/guides/) are the operator
manual; follow their worked sequences instead of reconstructing steps from this page. The
safety and data contracts in [AGENTS.md](../../../AGENTS.md#binding-safety-and-data-contracts)
bind every task.

## Before running anything

- Run commands from the repository root. On a development host, use `.venv/bin/python
  scripts/iso_chain.py <command>` after `just setup`; `<command> --help` lists every input
  without side effects. A direct `prepare-initramfs` on a ppc64le Linux host runs as the
  [building media guide](../../../docs/guides/building-media.md#building-the-launcher-initramfs-on-macos)
  shows.
- The host and the target differ. Development hosts are macOS arm64 or x86_64 Linux; the media
  targets ppc64le POWER9. Never infer the target from the host.
- `just setup` installs no target tools. Check the
  [host and task prerequisites](../../../README.md#host-and-task-prerequisites) for the task
  before running it, and stop with the missing tool named rather than improvising a substitute.
- On macOS, never attempt a direct `build`, `prepare-initramfs` or QEMU run. Use the container
  commands below, and leave QEMU proofs to a Linux host. On any non-ppc64le host,
  `prepare-initramfs` needs the container path.

## Choose a task

| Task | Commands | Guide | Host and target boundary |
| --- | --- | --- | --- |
| Build launcher media | `prepare-initramfs` or `container-prepare-initramfs`, `prepare-<distribution>-source`, then `build` or `container-build` | [Building media](../../../docs/guides/building-media.md#build-the-iso) and the distribution guide's [Prepare the profile](../../../docs/guides/fedora.md#prepare-the-profile) | `prepare-initramfs` needs a ppc64le Linux host. Elsewhere run `just build-initramfs-image` then `container-prepare-initramfs`; macOS arm64 with Docker Desktop is the verified host, and Linux emulation is unverified ([section](../../../docs/guides/building-media.md#building-the-launcher-initramfs-on-macos)). `build` needs GRUB and `xorriso`; on macOS run `just build-image` then `container-build` ([section](../../../docs/guides/building-media.md#building-the-launcher-iso-on-macos)). |
| Check a manifest offline | `validate-config` | [Validate configuration offline](../../../docs/guides/building-media.md#validate-configuration-offline) | Any development host; no artifacts, network or build. |
| Check an existing source | `validate-external-source`; `serve-source` for a local tree | [Validate source pins](../../../docs/guides/sources.md#validate-source-pins) | Any development host with access to the source. It downloads pinned files; it proves no install. |
| Exercise QEMU proofs | `smoke`, `install-fedora`, `install-rocky`, `install-ubuntu`, then the `verify-*` commands the sequence names | [Installer smoke proof](../../../docs/guides/verification.md#installer-smoke-proof) or [unattended installation proof](../../../docs/guides/verification.md#unattended-installation-proof) | Linux host with `qemu-system-ppc64`, `qemu-img` and `tcpdump`; never macOS. |
| Reuse settings across systems | `validate-config`, `build` or `container-build` with `--target` and `--base-config`, optionally `--block-config` | [Presets](../../../docs/guides/presets.md) | As for the offline check and build rows. |
| Publish media for hmcpctl | `build` or `container-build` with `--target`, `--base-config`, `--publish-dir` and `--publish-url`; `inspect` | [Target-bound media](../../../docs/guides/target-bound-media.md) | As for the build row. |
| Contribute | `just setup`, `just check`, `just check-tests`, `just fix` | [Development](../../../README.md#development) | Any development host; builds and boots no media. |

Profile-specific preparation, signature checks and limits live in the distribution guides
linked from the README [support matrix](../../../README.md#support-matrix). Authenticated FTP
sources follow the [operator runbook](../../../docs/ftp-operator-runbook.md).

## Machine-readable output

Two JSON contracts exist. Dispatch on the discriminator field, never on stdout position or
prose.

- `iso-chain-report-v1`, keyed by `version`: printed when `--json` is given to
  `validate-config`, `verify-log`, `verify-launcher-log`, `verify-pcap`,
  `verify-installer-evidence`, `verify-fedora-install-evidence`,
  `verify-rocky-install-evidence`, `verify-ubuntu-install-evidence`,
  `prepare-fedora-source`, `prepare-rocky-source`, `prepare-rhel-source`,
  `prepare-opensuse-source`, `prepare-ubuntu-source`, `prepare-initramfs`, `install-fedora`,
  `install-rocky`, `install-ubuntu` or `validate-external-source`. See
  [JSON reports](../../../docs/guides/verification.md#json-reports-for-validation-and-verification)
  and [ADR 0030](../../../docs/adr/0030-report-validation-as-json.md).
- `iso-chain-media-v1`, keyed by `format` (it has no `version` field): printed by `build` and
  `container-build` for one-profile media, and by `inspect --result` for unbound one-profile
  media. A multi-profile build prints no result. See
  [Target-bound media](../../../docs/guides/target-bound-media.md) and
  [ADR 0015](../../../docs/adr/0015-emit-a-target-bound-producer-result.md).

## Privacy

- Set `umask 077` and use a fresh private output path for every run.
- Manifests, media, source trees, console and access logs, packet captures and disk hashes
  can identify machines and networks. Never paste them, or values read from them, into tool
  output, issues, pull requests or commit messages.
- Never commit them. Errors and summaries name the failed check, not the private value.
- `inspect`, `build` and `container-build` print the embedded manifest or the media result,
  which carry source URLs, MAC and network values. Redirect their stdout to a file under the
  private path and read only the fields the next step needs, such as `format` or `version`.

## Proof

- Unit tests and CI build and boot no media. Report which proof arms ran and their limits.
- QEMU results establish only their recorded QEMU boundary; they are not native PowerVM proof.
- Claim success only from the canonical evidence records the verifiers check, using the
  commit that built the media. Existing [experiments](../../../docs/experiments/) state their
  boundaries; do not broaden them.

## LPAR installation

hmcpctl owns LPAR installation. It creates the partition, reads its adapter's MAC and then
builds target-bound media with this repository's `build` or `container-build`. Prepare the
base manifest and the fixed build command as the
[target-bound media guide](../../../docs/guides/target-bound-media.md) describes, then hand
off to hmcpctl. This skill does not cover HMC, VIOS or partition operations.
