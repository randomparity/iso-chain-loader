# Repository Guidelines

## Purpose and authoritative references

This stdlib-only Python CLI builds and exercises an optical bootstrap chain targeting **ppc64le
POWER9**, with `powerpc-ieee1275` GRUB, a dracut/systemd launcher and `kexec` installer handoff.
Development hosts are **macOS arm64 or x86_64 Linux**; host and target architectures are separate.
Supported profiles are Fedora 44, Rocky 9.8, RHEL 9.0 to 10.2 (interactive or
unattended, [ADR 0028](docs/adr/0028-add-rhel-installer-profiles.md),
[ADR 0031](docs/adr/0031-install-rhel-unattended-from-a-derived-kickstart.md)), Ubuntu 26.04.1 and openSUSE Leap 15.6.

Start with the README's [task chooser](README.md#choose-a-task) and
[host/task prerequisites](README.md#host-and-task-prerequisites). Use the guides' worked sequences
for preparation, construction and evidence collection; do not duplicate that operator manual here.
The [manifest/media design](docs/workflow/specs/2026-10-01-iso-carried-artifacts-design.md) and
accepted [ADRs](docs/adr/) govern the contracts; ADR 0011 withdraws the old verified-bundle path.
HMC/VIOS orchestration belongs to #6; firmware security and native PowerVM proof are separate.

## Binding safety and data contracts

- **No fallbacks:** no DHCP, IPv6, alternate profile/source, redirects, or credentials outside an
  authenticated `ftp://` source's userinfo. Select the exact MAC and configure static IPv4.
- Public sources require HTTPS. Plain HTTP admits only loopback/RFC 1918 IPv4; plain FTP admits
  bounded userinfo for any host. Reject FTPS, other credentials, queries and fragments. Keep build
  and launcher validation aligned ([HTTP](docs/adr/0026-restrict-plain-http-to-private-ipv4-sources.md),
  [FTP](docs/adr/0027-accept-plain-ftp-sources-with-userinfo.md),
  [credential exposure](docs/adr/0016-assess-authenticated-ftp-sources.md)).
- Manifest v4 is the single source of truth; reject v3 with a regeneration hint. Reject duplicate
  keys, unknown fields, wrong types, noncanonical MAC/IPv4/URL paths and invalid profile lookups.
  Preserve exact profile field sets and supported release/network restrictions; see the
  [profile sequences](docs/guides/fedora.md) and `ManifestV4Tests`.
- Canonical JSON is UTF-8, `ensure_ascii=False`, sorted keys, separators `(',', ':')`, plus one
  newline. Bind its SHA-256 into the media and kernel arguments. Bound manifests and target
  requests to 2 MiB; reject oversized input rather than truncating it. Retain the other `MAX_*`
  limits for artifacts, metadata, Kickstart, logs and captures.
- Verify exact artifact sizes and SHA-256 values before use. Preserve signed source anchors,
  digest-checked ISO-carried installer content and profile-specific handoff restrictions.
  Keep kernel arguments under 2,048 bytes and GRUB entries under 1,024 bytes, using top-level
  argument variables for PowerVM CAS replay.
- Preserve no-replace/no-symlink publication: real regular inputs, exclusive output creation,
  no existing destination, hard-link media publication and portable no-replace directory rename
  ([ADR 0010](docs/adr/0010-portable-no-replace-publication.md)).
- Refuse an unbound storage controller and require exactly one non-optical disk with zero first
  and last MiB before installer handoff. Preserve repeated unattended installer guards
  ([blank disk](docs/adr/0018-boot-installed-disk-and-require-blank-target.md),
  [drivers](docs/adr/0022-refuse-a-storage-controller-without-a-driver.md)).
- Keep installed-disk search and btrfs default-subvolume behavior. Keyed media requires the final
  `iso_chain_installed=1` completion marker; unkeyed media keeps the `grubenv`-only rule
  ([keyed](docs/adr/0021-require-a-completion-marker-on-keyed-media.md),
  [btrfs](docs/adr/0024-resolve-installed-disk-paths-in-the-btrfs-default-subvolume.md),
  [unkeyed](docs/adr/0025-keep-the-grubenv-only-rule-on-unkeyed-media.md)).
- Login values travel only in the digest-bound manifest; build refuses them unless every carried
  profile applies them. Preserve derived Rocky/RHEL Kickstart and Ubuntu user data and grant the
  login user no administrative access ([login](docs/adr/0017-carry-login-values-in-the-manifest.md),
  [Rocky](docs/adr/0019-install-rocky-unattended-from-a-derived-kickstart.md),
  [RHEL](docs/adr/0031-install-rhel-unattended-from-a-derived-kickstart.md),
  [Ubuntu](docs/adr/0020-install-ubuntu-unattended-from-iso-carried-user-data.md),
  [privileges](docs/adr/0023-grant-the-login-user-no-administrative-access.md)).
- Keep manifests, media, source trees, logs, access logs, disk hashes and packet captures private:
  `umask 077`, fresh paths per run, never commit them. Errors must not echo private/untrusted data.
- Claim success only from canonical evidence records binding console, access-log, capture and
  disk-image SHA-256 digests. Verify with the commit that built the media. Existing
  [experiments](docs/experiments/) state their QEMU/PowerVM boundaries; do not broaden them.

The [FTP installation and residue experiment](docs/experiments/2026-10-27-ftp-installs-and-residue.md)
records the four QEMU pSeries/POWER9 FTP-source proof arms and installed credential findings.

## Development and verification

Require Python **3.14** (`.python-version`), `just` >=1.57, and uv 0.12.12 or compatible.
`just setup` supplies Python when necessary, installs hash-locked development tools from
`requirements-dev.lock` and installs the tracked Git hook. The lock and `requirements-dev.in`
own tool versions; regenerating the lock is a separate review action. No runtime dependencies.

```sh
just setup
just check
just fix
just check-tests
.venv/bin/pre-commit run --all-files
.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests
bash tests/test_iso_chain_launch.sh
```

`Justfile` owns the commands. `just check` runs Justfile formatting, whitespace, Python lint and
format, tests, Markdown and secrets checks. Local commit hooks delegate to six focused recipes
and **omit tests**; run `just check-tests` before shipping. CI runs `just setup` and `just check`
on Linux and macOS. Do not duplicate recipe command strings in hooks/workflows.

Checks are read-only, deterministic and uncached. Only `just fix` applies lint/format fixes and
then checks again. `.secrets.baseline` stores finding line numbers: refresh shifted numbers when
moving covered content; adding/removing findings requires separate review. Never bypass a red gate.

Setup does not install target tools. ISO construction needs GRUB/xorriso; macOS uses the pinned
builder container (`just build-image`). Initramfs preparation needs ppc64le Linux, dracut and
matching kernel/modules; the emulated container path uses `just build-initramfs-image`.
Follow the README prerequisite map for source extraction/signatures and QEMU/capture tools.

Unit tests and CI do not build or boot media. Run relevant end-to-end proof when runtime/media
behavior changes and the environment can exercise it; confirm the deployed build matches HEAD.
Report which arms ran and their limits. QEMU results are not native PowerVM proof. Do not run
full suites or remote/media operations for prose-only changes.

## Code and test conventions

- Standard library only in `scripts/`; annotate functions, use snake_case/PascalCase/UPPER_CASE
  and frozen dataclasses for domain values. Keep `parser()`/`main()` as the dispatch boundary.
- Use strict small validators and explicit `Path`, `Manifest`, `Namespace` or byte seams;
  no schema library or DI framework. Validate invalid inputs before spawning external commands.
- Raise actionable `ValidationError`; `main()` prints `error: ...` on stderr and returns 2.
  Translate malformed inputs and filesystem/network/subprocess failures; preserve OSError exit 1
  and failed-child exit codes. Results use stdout `print()` and fixed evidence markers, no logger.
- Ruff and rumdl own formatting: 100 columns, Python `py314`, no Black/type checker/coverage tool.
  Keep canonical ordering, reproducible dracut generation and no-cache checks.
- Use stdlib unittest and the Bash black-box harness, not pytest. Extend the matching behavior
  class; use existing manifest factories and `valid_log()` in `tests/test_iso_chain.py`.
- Isolate temporary state with `self.enterContext(tempfile.TemporaryDirectory())`; mock external
  tool boundaries and narrow race/limit seams, not logic. Existing server tests use real loopback
  servers with timeouts; FTP patches stdlib `ftpwrapper` rather than adding a server dependency.
- Cover reachable edges, bounds/canonical rejection and privacy-safe errors. Assert external
  commands were not called for invalid input. Prove new/suspect tests bite with a controlled fault.
- `ExternalMirrorOptInTests` runs only with both `ISO_CHAIN_EXTERNAL_MIRROR` and
  `ISO_CHAIN_EXTERNAL_MANIFEST`; never select an implicit mirror.
- The launcher harness uses `LC_ALL=C`, fake commands/devices and injected `ISO_CHAIN_*` paths.
  Keep both dracut scripts executable; success is exactly `launcher shell tests: passed`.
  Asset changes must keep the coupled Python/shell tests green.

## Source, test and document map

| Responsibility | Source | Verification/reference |
| --- | --- | --- |
| Manifest/target parsing, render/build, source preparation, execution and evidence | `scripts/iso_chain.py` | Matching classes in `tests/test_iso_chain.py`; [README tasks](README.md#choose-a-task) |
| Guest argument parsing, static network, disk/media guards, downloads and kexec | `assets/dracut/iso-chain-launch.sh`, service/target and module setup | `tests/test_iso_chain_launch.sh`, `PrepareTests`; [launcher ADR](docs/adr/0004-use-grub-and-dracut-for-launcher.md) |
| Fedora unattended fixtures, `/dev/vda` versus PowerVM `/dev/sda` | `assets/kickstart/fedora-44-power9.ks`, `fedora-44-powervm.ks` | `InstallTests` holds the fixtures identical except disk; [ISO-carried artifacts](docs/adr/0011-carry-installer-artifacts-on-the-launcher-iso.md) |
| Rocky derived unattended content | `assets/kickstart/rocky-9.8-unattended.ks` | `RockyKickstartTests` and install evidence tests; ADR 0019 above |
| RHEL derived unattended content | `assets/kickstart/rhel-unattended.ks` | `RhelKickstartTests`, `RHELEvidenceTests`; ADR 0031 above |
| Ubuntu fixed autoinstall keys, early guard and late completion | `assets/autoinstall/ubuntu-26.04.1.json` | `UbuntuUserDataTests` and install evidence tests; ADR 0020 above |
| CLI and bounded contributor commands | `parser()`/`main()`, README Development and this file | `CLIHelpTests`; [Development](README.md#development) |
| Guardrails and tool pins | `Justfile`, `pyproject.toml`, requirements files | `.githooks/pre-commit`, `.pre-commit-config.yaml`, `.github/workflows/checks.yml` |
| Binding decisions and design contracts | `docs/adr/`, `docs/workflow/specs/` | Read applicable accepted records; full designs may have transient plans in `docs/workflow/plans/` |
| Recorded proof and durable fixes | `docs/experiments/`, `docs/solutions/` | Preserve proof limits; follow the [solution format](docs/solutions/2026-09-10-stream-subprocess-evidence-before-eof.md) |
