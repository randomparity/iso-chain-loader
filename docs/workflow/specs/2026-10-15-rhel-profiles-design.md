# RHEL Installer Profiles

## Problem

Manifest v4 accepts `fedora`, `opensuse`, `rocky`, and `ubuntu` profiles only. Issue #78 asks for
RHEL 9 and RHEL 10 profiles, installed from an authenticated FTP mirror that publishes no signed
checksum. The operator decided on 2026-10-15: every release the mirror offers for ppc64le (9.0 to
9.8, 10.0 to 10.2) is supported, the profile is interactive, AppStream is added, 10.x ships whatever
a POWER9 boot shows, and the mirror's name never appears in the repository.

Decision record: [ADR 0028](../../adr/0028-add-rhel-installer-profiles.md).

## Contract

### Manifest v4

- **`rhel`**: exactly `distribution`, `release`, `kernel`, `initramfs`, `repository`, and
  `minimum_memory_mib`, with Rocky's grammar and no `kickstart`. `repository.path` must end in
  `/BaseOS/ppc64le/os`, or loading fails with
  `profiles.<name>.repository.path: must end in /BaseOS/ppc64le/os`.
- **Releases.** `PROFILE_RELEASES` maps each distribution to a tuple of releases. `rhel` allows
  9.0, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 10.0, 10.1, and 10.2. The other four keep their one
  release. A pair outside the table fails with
  `profiles.<name>.distribution/release: must be fedora/44, opensuse/15.6, rhel/9.0 to 9.8 or
  10.0 to 10.2, rocky/9.8, or ubuntu/26.04.1`.
- **Login values** (`ssh_authorized_keys`, `login_user`) are still refused unless every profile is
  Rocky or every profile is Ubuntu, so a `rhel` profile cannot carry them.
- For `rhel`, `_kernel_arguments` emits Rocky's repository, `.treeinfo`, and `repomd` arguments and
  no Kickstart. `build` stages nothing for it.

### Preparation

```text
prepare-rhel-source --iso ISO --iso-sha256 HEX --digest-source mirror-sha256sum --tree TREE
    --repository-path PATH --release REL --minimum-memory-mib N --output OUT
```

1. Validate the arguments. `PATH` must end in `/BaseOS/ppc64le/os`, `REL` must be in the `rhel`
   table, `--digest-source` must be `mirror-sha256sum`, `HEX` must be a SHA-256, and the memory
   must be in range, or the function fails before touching any path or running any tool. The
   parser requires `--digest-source`, so omitting it is an argparse exit, not a `ValidationError`.
2. Read `TREE/.treeinfo` through the shared treeinfo helper with identity `Red Hat Enterprise
   Linux`/`REL`/`ppc64le` and variant `BaseOS`. Unlike Rocky, no `[variant-AppStream]` section is
   required or checked. `images/boot.iso` must equal `HEX`. Every failure reads
   `RHEL treeinfo: <reason>`.
3. Copy and hash the ISO, extract the kernel and initrd with `xorriso`, and match them to
   `.treeinfo`, all through the shared helper.
4. Publish `OUT` with no-replace publication, holding only `profile.json`: a `rhel` profile pinning
   `PATH/ppc/ppc64/vmlinuz`, `PATH/ppc/ppc64/initrd.img`, `.treeinfo`, and `repomd.xml`. The same
   parser validates it before publication. Then print `digest-source: mirror-sha256sum`.

### Launcher

- **Arguments.** `parse_arguments` accepts `rhel:<release>` for the twelve releases with
  `valid_rhel_arguments`: Rocky's checks with no Kickstart argument allowed. Any other mix prints
  `configuration: failed`.
- **Launch.** `launch_anaconda` runs unchanged except that `anaconda_command_line` appends
  `inst.addrepo=AppStream,$source<path>` for `rhel`, where `<path>` is `repository_path` with
  `/BaseOS/ppc64le/os` replaced by `/AppStream/ppc64le/os`. There is no media search and no
  `media:` marker. The launcher's kernel command line is unchanged. The installer's line carries
  `source` and the path twice each, and `build` bounds only the launcher's line; a source near the
  128-byte userinfo limit with a long path could pass `build` and exceed the limit at `kexec`.

### Evidence

- **`verify-launcher-log`.** The installer arguments, after quote stripping, carry no `inst.ks`/`ks`
  key and exactly one `inst.repo=<source><repository.path>` and exactly one
  `inst.addrepo=AppStream,<source><AppStream path>`.
- **HTTP rules.** `rhel` takes the Anaconda probe 404s (`images/updates.img`, `images/product.img`)
  and the repository prefixes BaseOS and the AppStream sibling. Any other path fails.
- **Other commands.** `validate-external-source` checks the four pins. There is no `install-rhel`
  and no `verify-rhel-install-evidence`.

### Proof

Build the RHEL 9.8 and RHEL 10.2 ISOs with `container-prepare-initramfs` and `container-build`,
then, with the operator's explicit go-ahead, boot each on the operator's POWER9 managed system with
the operator's `hmcpctl`. The operator's `hmcpctl` accepting `rhel-9.8` and `rhel-10.2` as profile
names is a precondition; a refusal is recorded and filed in that project. Record the launcher
markers, whether the installer's Installation Source screen lists AppStream, the installer hub or
the failure, and the redacted identifiers in `docs/experiments/2026-10-15-rhel-installer.md`. A
RHEL 10 failure on POWER9 is a recorded result.

## Failure model

1. **Actors and deployments.**
   - A local operator on macOS arm64 or x86_64 Linux prepares and builds.
   - A PowerVM POWER9 partition boots the ISO once per proof release. QEMU is not used.
   - `source` is the operator's authenticated FTP mirror, whose name is private.
2. **Invariants and assets.**
   - Only kernel and initrd bytes bound in the manifest digest reach `kexec`.
   - No DHCP, no IPv6, no alternate adapter, and no silent change of profile.
   - The launcher never writes a disk, and the mirror's name and credential stay out of the repository.
   - Fedora, Rocky, openSUSE, and Ubuntu manifests, command lines, and evidence are unchanged.
3. **Accepted failure classes.**
   - **Unsigned digest anchor**: accepted by operator decision; the flag makes it explicit.
   - **Unpinned stage2, BaseOS metadata beyond `repomd.xml`, and AppStream** (ADR 0011 class).
   - **Releases other than the two proof releases are covered by tests only.**
   - **`inst.addrepo` ignored by an older Anaconda**: the install sees BaseOS only; accepted.
4. **Covered elsewhere.**

   | Concern | Owner |
   |---|---|
   | Unattended RHEL install and Kickstart | follow-up issue filed by this change |
   | HMC and VIOS orchestration | #6 |
   | FTP credential handling | ADR 0016 and ADR 0027 |

### Threat model

- **Boundaries.**
  - Added: the operator-supplied RHEL ISO and mirror `.treeinfo`, read by `xorriso` and
    `configparser`; the `--release` and `--digest-source` arguments.
  - Widened: the manifest parser, the launcher argument parser, and the verifiers accept one more
    profile shape.
- **Actors.** A compromised or on-path mirror and a mistaken operator. Trust sits with the operator's
  own check of the digest.
- **Controls.**
  - The ISO digest must match before extraction; extracted images must equal `.treeinfo`.
  - `--release` and `--digest-source` are closed sets validated before any file read.
  - Parsers enforce exact field sets, and the URL-path grammar keeps shell metacharacters out of
    the AppStream argument.
  - Messages name fields, never values.
- **Out of scope.** A compromised mirror serving a matching forged digest, Secure Boot (ADR 0003).

## Testing

- **Unit.** Every accepted release and a thirteenth rejected, noncanonical releases, the field
  set, a stray `kickstart`, the path suffix, kernel arguments, `build`, the login-value refusal, and
  `prepare-rhel-source` with `xorriso` faked: success, digest mismatch, wrong identity or release,
  missing `--digest-source`, bad suffix, existing output, with `run.assert_not_called()` on every
  validation failure. Launcher-log handoff: a stray `inst.ks`, a missing or wrong `inst.repo` or
  `inst.addrepo`. HTTP rules and the `ftp://` source variants.
- **Shell.** A RHEL command line yields four downloads, no mount, and exact kexec arguments with
  the `inst.addrepo`. Each of the twelve listed releases passes configuration; `9.9`, `10.3`,
  `9.80`, `09.8`, `10.10`, `9`, and `10` fail it, as do a Kickstart argument, a live-ISO argument,
  and a bad suffix.
- **Live.** The proof above.
