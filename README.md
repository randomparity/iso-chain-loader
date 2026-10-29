ISO Chain Loader
================

A ppc64le optical launcher for POWER9 partitions. A GRUB profile menu selects an installer profile;
the launcher applies the partition's static IPv4 settings, downloads the profile's pinned kernel
and initrd from the manifest's `source`, checks their sizes and SHA-256 digests, and kexecs the
installer. Fedora 44 installs from a Kickstart carried on the ISO. Red Hat Enterprise Linux 9.0
through 10.2, Rocky Linux 9.8 and Ubuntu 26.04.1 install interactively or, with SSH keys and a login
user in the manifest, unattended. openSUSE Leap 15.6 hands off to the linuxrc and YaST installer.
Development runs on macOS arm64 or x86_64 Linux; the media targets ppc64le.

Support matrix
--------------

Source schemes follow the shared [source URL rules](docs/guides/sources.md#source-url-rules).
Whether each installer decodes an FTP escape and resolves its path against the login directory
stays unproven until #70. Memory floors are the `--minimum-memory-mib` values the guides use. Proof
status links the principal records and names their environment; each distribution guide's Proof
status section lists all of its records. Read each record's result and boundary before relying on
it.

| Distribution | Releases | Modes | Source schemes | Memory floor (MiB) | Trust anchor | Example | Proof status | Guide |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fedora | 44 | Kickstart carried on the ISO (unattended fixture) | `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo | not stated | Signed `CHECKSUM` (Fedora release key) | [fedora.json](examples/fedora.json) | QEMU: [installer readiness](docs/experiments/2026-09-09-fedora-installer.md), [unattended install](docs/experiments/2026-10-03-fedora-v4-qemu-install.md), [FTP install](docs/experiments/2026-10-27-ftp-installs-and-residue.md); PowerVM: [Kickstart install](docs/experiments/2026-10-01-powervm-iso-carried-kickstart.md), console evidence only (no capture) | [Fedora](docs/guides/fedora.md) |
| Rocky Linux | 9.8 | Interactive; keyed unattended; operator Kickstart; preset `rocky-9.8-minimal` r1 | `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo | 6400 | Signed `CHECKSUM` (Rocky 2022 release key) | [rocky-interactive.json](examples/rocky-interactive.json), [rocky-unattended.json](examples/rocky-unattended.json), [rocky-operator.json](examples/rocky-operator.json), [target.json](examples/target.json) + [base.json](examples/base.json), [preset-block.json](examples/preset-block.json) + [A](examples/rocky-system-a.json)/[B](examples/rocky-system-b.json), London settings [block](examples/rocky-london-block.json) + [A](examples/rocky-london-system-a.json)/[B](examples/rocky-london-system-b.json) | QEMU: [interactive readiness](docs/experiments/2026-10-02-rocky-installer.md), [unattended](docs/experiments/2026-10-02-rocky-unattended-install.md), [preset](docs/experiments/2026-10-26-rocky-preset-install.md) and [FTP](docs/experiments/2026-10-27-ftp-installs-and-residue.md) installs; no PowerVM record | [Rocky](docs/guides/rocky.md) |
| RHEL | 9.0-9.8, 10.0-10.2 | Interactive; keyed unattended; operator Kickstart | `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo | 6400 (Rocky's, until measured) | Unsigned mirror `SHA256SUM` | [rhel-interactive.json](examples/rhel-interactive.json), [rhel-unattended.json](examples/rhel-unattended.json), [rhel-operator.json](examples/rhel-operator.json) | PowerVM: [interactive hub](docs/experiments/2026-10-15-rhel-installer.md), 9.8 and 10.2 only; unattended not exercised (#97) | [RHEL](docs/guides/rhel.md) |
| Ubuntu | 26.04.1 | Interactive; keyed unattended; preset `ubuntu-26.04.1-server` r1 | `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo | 5888 | Signed `SHA256SUMS` (Ubuntu CD image key) | [ubuntu-interactive.json](examples/ubuntu-interactive.json), [ubuntu-unattended.json](examples/ubuntu-unattended.json), [ubuntu-block.json](examples/ubuntu-block.json) + [A](examples/ubuntu-system-a.json)/[B](examples/ubuntu-system-b.json) | QEMU: [interactive readiness](docs/experiments/2026-10-02-ubuntu-installer.md), [unattended](docs/experiments/2026-10-03-ubuntu-unattended-install.md), [preset](docs/experiments/2026-10-26-ubuntu-preset-install.md) and [FTP](docs/experiments/2026-10-27-ftp-installs-and-residue.md) installs; no PowerVM record | [Ubuntu](docs/guides/ubuntu.md) |
| openSUSE Leap | 15.6 | Interactive | `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo | 6400 | Signed `CHECKSUMS` (openSUSE key, expired 2026-06-19) | [opensuse-interactive.json](examples/opensuse-interactive.json) | QEMU: [interactive readiness](docs/experiments/2026-10-02-opensuse-installer.md), [installed-disk boot](docs/experiments/2026-10-04-opensuse-btrfs-installed-disk.md), [FTP readiness](docs/experiments/2026-10-27-ftp-installs-and-residue.md); no PowerVM record | [openSUSE](docs/guides/opensuse.md) |

Choose a task
-------------

| Task | Start here | Inputs and result |
| --- | --- | --- |
| Build launcher media | [Prepare the launcher payload](docs/guides/building-media.md#building-the-launcher-initramfs-on-macos), then [prepare a source](docs/guides/fedora.md#prepare-the-profile) and [build](docs/guides/building-media.md#build-the-iso) | Manifest, matching launcher kernel/initramfs, and profile files → launcher ISO. [Container builds](docs/guides/building-media.md#building-the-launcher-iso-on-macos) supply the ISO tools on macOS. |
| Check a manifest offline | [Validate configuration offline](docs/guides/building-media.md#validate-configuration-offline) | Manifest or target/base pair → content and renderability checks; no artifacts, network or build. |
| Check an existing source | [Validate source pins](docs/guides/sources.md#validate-source-pins) | Manifest and reachable source → size/digest checks of the selected profile's pinned files. This downloads data; it does not prove an install. |
| Exercise QEMU proofs | [Installer smoke proof](docs/guides/verification.md#installer-smoke-proof) or [unattended installation proof](docs/guides/verification.md#unattended-installation-proof) | Prepared media, manifest, source, and test storage → console, traffic, and disk evidence checked by the existing verifiers. |
| Reuse settings across systems | [Presets](docs/guides/presets.md) | Prepared base, shared block and per-system definitions → one validated manifest per system. |
| Publish media for hmcpctl | [Target-bound media](docs/guides/target-bound-media.md) | Target request and base manifest → published ISO and `iso-chain-media-v1` result. |
| Contribute | [Development](#development) | Checkout → isolated tool environment, Git hook, and local checks matching CI. |

For profile-specific source preparation and limitations, use [Fedora](docs/guides/fedora.md),
[Rocky](docs/guides/rocky.md), [RHEL](docs/guides/rhel.md), [Ubuntu](docs/guides/ubuntu.md), or
[openSUSE](docs/guides/opensuse.md). For authenticated FTP sources, follow the
[operator runbook](docs/ftp-operator-runbook.md) before adapting those sequences.

Host and task prerequisites
---------------------------

The development host and output target are separate: development supports macOS arm64 and
x86_64 Linux; the launcher media targets ppc64le POWER9 with `powerpc-ieee1275` GRUB.
Start with [development setup](#development) for Python 3.14 and the pinned tools. `just setup`
does not install the additional tools below.

| Task | Additional prerequisites and boundary |
| --- | --- |
| Build an ISO | `grub2-mkrescue`, `xorriso`, ppc64le-capable GNU binutils and GRUB modules; on macOS use Podman or Docker with `just build-image` and `container-build`. Supply the prepared kernel, initramfs, manifest, and profile directory. |
| Prepare the launcher payload | Direct `prepare-initramfs` needs a ppc64le Linux host, installed matching kernel/modules, dracut, systemd, iproute, and curl. On macOS use the emulated `linux/ppc64le` container path; [its section](docs/guides/building-media.md#building-the-launcher-initramfs-on-macos) records engine requirements and unverified alternatives. |
| Prepare installer sources | Download the profile's release inputs and verify its signing key/signature as described in its distribution guide's [Verify the release](docs/guides/fedora.md#verify-the-release) section (`curl`, `gpg`/`gpgv`, checksum tools). Fedora, Rocky, RHEL, and Ubuntu ISO extraction needs `xorriso`; openSUSE uses signed tree checksums. Preparation produces profile pins, not a complete mirror. |
| Validate source pins | Python 3.14, a private manifest, and access to its declared source (including system CA trust for HTTPS). `validate-external-source` uses the Python standard library. |
| Run QEMU proofs | A Linux host with `qemu-system-ppc64` and `qemu-img`, prepared media/source, private capture storage, and enough guest RAM and disk for the chosen profile. The documented run commands do not run on macOS. Packet verification needs `tcpdump`; follow each sequence's capture/filter and disk-hash steps in [verification](docs/guides/verification.md). |
| Contribute and check docs/code | Python 3.14, `just` ≥1.57, uv 0.12.12 or a compatible release, and Git; `just setup` installs hash-locked development tools and the hook. No ISO build tools are needed for these checks. |

Keep manifests, media, source trees, and evidence in private storage (`umask 077`), using fresh
output paths. The [worked sequences](docs/guides/) retain their signature checks, unpinned-runtime qualifications,
and profile-specific resource limits. Local checks and CI do not build or boot media; emulator
results establish only their recorded QEMU boundary, and native PowerVM requires separate proof.

Quickstart
----------

1. Run `just setup`, then install the [task prerequisites](#host-and-task-prerequisites) for the
   tasks you will run.
2. Prepare the launcher kernel and initramfs with
   [`container-prepare-initramfs`](docs/guides/building-media.md#building-the-launcher-initramfs-on-macos).
3. Verify the release signature and run the profile's `prepare-*` command, following its
   distribution guide from the [support matrix](#support-matrix).
4. Copy a [synthetic example](docs/guides/building-media.md#synthetic-configuration-examples) (all
   are [indexed](examples/README.md)) into private
   storage, replace its values with the prepared profile and your network, and check it with
   [`validate-config`](docs/guides/building-media.md#validate-configuration-offline).
5. [Build the ISO](docs/guides/building-media.md#build-the-iso), then prove it with the
   [smoke or installation proof](docs/guides/verification.md).

Development
-----------

Development is supported on macOS arm64 and on x86_64 Linux, with Python 3.14,
just 1.57 or newer, and uv 0.12.12 or a compatible release. uv provides Python
3.14 when the host does not already have it. Set up the isolated Python
environment and install the Git hook:

```sh
just setup
```

Run the same aggregate checks used by continuous integration:

```sh
just check
```

The check command, local hooks, and continuous integration do not modify repository files. Apply
safe Python and Markdown fixes explicitly, then run the full checks, with:

```sh
just fix
```

The installed pre-commit hooks run the focused checks when committing. To run
all configured hooks directly, use:

```sh
.venv/bin/pre-commit run --all-files
```

For a focused parser test and the source/test map, see [agent guidance](AGENTS.md).
Inspect the existing CLI without artifact inputs or external tools:

```sh
.venv/bin/python scripts/iso_chain.py --help
.venv/bin/python scripts/iso_chain.py build --help
```

`just check-tests` discovers the contributor-command checks in `CLIHelpTests`: the documented
focused unittest command must run a nonzero number of tests, and these fixed help examples must
succeed without creating files in their temporary working directory. These bounded checks do not
execute other documentation blocks or prove a build, boot, or installation. Local commit hooks
omit tests; run `just check-tests` before shipping. CI runs it through `just check`.

Secret checks compare current tracked content with the reviewed `.secrets.baseline`; updating that
baseline is a separate review action. Python type checking will be added when the repository has
explicit Python source paths.

The ISO output targets ppc64le. Building bootable media additionally requires
ppc64le-capable GNU binutils, GRUB image tooling, and `xorriso`; `just setup`
does not install these target build tools.

End-to-end validation requires either a ppc64le emulator or a real ppc64le
system. The local checks and continuous integration workflow do not build or
validate bootable media.

Fedora installer launcher
-------------------------

The Fedora preparation, build and verification sequence is in the [Fedora guide](docs/guides/fedora.md).

Documentation
-------------

- Task guides: [building media](docs/guides/building-media.md), [sources and pin
  validation](docs/guides/sources.md), [verification and evidence](docs/guides/verification.md),
  [presets](docs/guides/presets.md), [target-bound media](docs/guides/target-bound-media.md), and one guide per
  distribution in the [support matrix](#support-matrix).
- [FTP operator runbook](docs/ftp-operator-runbook.md) for authenticated FTP sources.
- [Architecture decision records](docs/adr/), [design specifications](docs/workflow/specs/) and
  [experiment records](docs/experiments/).
- [Agent guidance](AGENTS.md) for the source and test map.
