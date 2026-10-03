# Rocky Unattended Install Design

Issue: #25. Decision: [ADR 0019](../../adr/0019-install-rocky-unattended-from-a-derived-kickstart.md).
Reuses ADR 0017 (login values) and ADR 0018 (installed-disk menu and launcher disk guard).

## Problem

hmcpctl's built mode sends SSH keys and a login user, but `build` refuses them because no profile
applies them, and the Rocky 9.8 profile only reaches an interactive Anaconda. Built-mode media must
install Rocky unattended onto the one blank disk, reboot, and boot that disk with the ISO attached.

## Scope

In scope:

- `_build_manifest` refuses login values unless every profile is `rocky`.
- `_rocky_kickstart(manifest) -> bytes` renders ADR 0019's Kickstart; `_profile_kickstart(manifest,
  name) -> tuple[Artifact, bytes | None] | None` returns a Fedora profile's declared Kickstart
  (bytes `None`), a Rocky profile's derived one when login values are present, or `None`.
- `_kernel_arguments`, `_stage_profile_artifacts`, and `verify_launcher_log` use
  `_profile_kickstart` instead of `profile.kickstart`.
- `valid_rocky_arguments` in the launcher accepts either no Kickstart arguments or a valid
  Kickstart path, size of at most 1 MiB, and digest; `launch_anaconda` is unchanged.
- `assets/kickstart/rocky-9.8-unattended.ks`, the fixed template.
- The `installed disk` GRUB entry echoes `ISO_CHAIN: GRUB installed-disk handoff`.
- `install-rocky` and `verify-rocky-install-evidence`, sharing `install-fedora`'s helpers.
- ADR 0013 consequence line, README, AGENTS.md, and a QEMU experiment record.

No ownership transition: Kickstart staging and command-line binding stay in `build`; the Fedora
commands keep their names and behavior.

### Rendered Kickstart

The template, then, in order:

```text
network --hostname=<lpar>
user --name=<shlex.quote(login_user)>
sshkey --username=<shlex.quote(login_user)> <shlex.quote(key)>     # one per key, manifest order
%post --erroronfail --interpreter=/bin/sh
<remove /etc/NetworkManager/system-connections/* and /etc/sysconfig/network-scripts/ifcfg-*>
<write iso-chain.nmconnection, mode 0600, then restorecon>
%end
```

The keyfile holds `type=ethernet`, `mac-address=<mac>`, `method=manual`, `address1=<address>`,
`gateway=<default gateway>`, `route<n>=<destination>,<gateway>` for each other route, `dns=<a>;...;`
when DNS is present, and `[ipv6] method=disabled`. Every network value has passed manifest
validation, so only keys and the user are quoted. The template carries `text`, `lang`, `keyboard`,
`timezone`, `rootpw --lock`, `firstboot --disable`, `selinux --enforcing`,
`firewall --enabled --service=ssh`, `%include /tmp/iso-chain-disk.ks`, `@^minimal-environment`,
`reboot`, and a `%pre` that counts `/sys/block` entries with a `device` link and a name not
starting `sr`, requires one, requires its first and last 1 MiB to hash as zeros, prints
`iso-chain-disk: failed ...` and exits 1 otherwise, and writes `ignoredisk --only-use`, `zerombr`,
`clearpart`, `bootloader --boot-drive ... --append="console=hvc0"`, PReP, `/boot`, and LVM root
lines for that disk.

### Harness and evidence

`install-rocky --iso --config --output [--disk-size-gib 20] [--memory-mib 8192]
[--install-timeout-seconds 14400] [--boot-timeout-seconds 3600]` requires a selected Rocky profile
with login values. It creates a fresh qcow2, runs `install_qemu_commands`' install command plus
`-no-reboot` until QEMU exits 0, hashes the disk, then runs the same command with a second capture
until the console shows `<lpar> login:` and stops QEMU. It publishes both console logs, both
captures, `disk.qcow2`, and `result.json`, whose `boot_stop` is `login-prompt` in place of
`boot_exit_status`.

`verify-rocky-install-evidence` takes `install-fedora`'s evidence arguments minus `--kickstart`,
plus `--boot-pcap`. It checks the record and digest map as the Fedora verifier does; a Rocky profile
with login values; a changed disk hash; the result; the access log, in which launcher pins come
first and once, later requests stay under BaseOS or AppStream, and only `images/updates.img` and
`images/product.img` may 404, once each; `verify_launcher_log` on the install console; both captures
through `verify_pcap`; and a boot console with one installed-disk handoff line, no optical handoff
or launcher line, and a later `<lpar> login:` line.

## Failure model

1. Actors and deployments
   - hmcpctl or an operator building media from a manifest whose keys and user come from a caller.
   - The built ISO booting on QEMU pSeries/POWER9 or a PowerVM LPAR (native run: hmc-mcp#1230).
   - A developer running the unit and shell suites on Linux or macOS.
2. Invariants and assets at stake
   - Data on any disk that is not the one blank non-optical disk: never written.
   - The Kickstart's command and section structure: no key or user value changes it.
   - The installed system's network: exactly the manifest's static IPv4 configuration.
   - Keyless Rocky media: byte-identical to before this change.
3. Accepted failure classes
   - A key that is printable but not a valid OpenSSH key installs and does not work: hmcpctl owns
     key grammar (ADR 0017).
   - A disk appearing after the `%pre` count is not counted: as ADR 0018 accepts for settle.
   - An installed `grub.cfg` the ISO's GRUB cannot load stops at GRUB (ADR 0018).
   - Unpinned stage2, AppStream, and package downloads (ADR 0013).
4. Covered elsewhere
   - Native PowerVM proof and CAS replay: hmc-mcp#1230. Media detach: hmc-mcp#1228.
   - Ubuntu login values: #24. Producer result format: hmcpctl, `iso-chain-media-v1` unchanged.

### Threat model

- Boundaries widened: manifest `ssh_authorized_keys` and `login_user` (caller-controlled, already
  bounded by ADR 0017) now enter a Kickstart; the guest disk set enters the installer's `%pre`.
- Actors: the hmcpctl caller who supplies keys and user; whoever attaches disks to the partition.
- Controls: ADR 0017 validation (one printable line, bounded length and count, user regex), then
  `shlex.quote` per value on a line that starts with a fixed command, tested against `shlex.split`
  with quote, backslash, `#`, `%`, and non-ASCII keys; the rendered size stays under
  `MAX_KICKSTART_BYTES`; the `%pre` disk count and zero checks fail closed; errors name the field,
  never its value.
- Out of scope: a caller who controls the operator's base manifest or source mirror (trusted per
  ADR 0011); administrative access on the installed system (ADR 0019 Consequences).

## Success

1. `build` accepts login values when every profile is `rocky` and refuses them, before any external
   command, when any profile is `fedora`, `ubuntu`, or `opensuse`.
2. For a Rocky profile with login values, the ISO carries `/profiles/<profile>/ks.cfg` equal to
   `_rocky_kickstart(manifest)`, and the command line binds its path, size, and digest; keyless
   Rocky ISOs and command lines are unchanged.
3. For keys holding `'`, `"`, `\`, `#`, `%`, leading `%`, and non-ASCII characters, every `sshkey`
   line splits under `shlex.split(line, comments=True)` into `sshkey`, `--username=<user>`, and the
   exact key, and the rendered file has exactly one `%pre`, one `%post`, and one `%packages`.
4. The launcher accepts Rocky arguments with or without a valid Kickstart, rejects a partial or
   oversized one, and passes `inst.ks=cdrom:LABEL=...` and `inst.repo` when one is present.
5. `verify_launcher_log` requires the media and Kickstart evidence for an unattended Rocky profile.
6. `verify-rocky-install-evidence` accepts a consistent record set and rejects each broken input.
7. A QEMU pSeries/POWER9 record: unattended install to one blank disk, reboot, installed-disk boot
   through the ISO's entry with the ISO attached, and an operator SSH login with the injected key,
   labelled as emulator evidence.

## Validation

- Success 1, 2, 3: focused-test, `BuildTests` and a new `RockyKickstartTests` in
  `tests/test_iso_chain.py`.
- Success 4: focused-test, Rocky cases in `tests/test_iso_chain_launch.sh`.
- Success 5: focused-test, `RockyEvidenceTests` launcher-log cases.
- Success 6 and `install-rocky` command shape: focused-test, `RockyInstallEvidenceTests` and
  `InstallTests`.
- GRUB echo line: focused-test, `BuildTests` menu case.
- Success 7: task-test-not-applicable; a QEMU install with emulated firmware that the unit suites
  cannot run, recorded in `docs/experiments/2026-10-02-rocky-unattended-install.md`.
- ADR 0013 line, README, AGENTS.md: task-test-not-applicable; prose with no executable consumer.
