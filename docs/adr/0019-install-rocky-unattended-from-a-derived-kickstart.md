# ADR 0019: Install Rocky Unattended From a Build-Derived Kickstart

## Status

Accepted

## Context

hmcpctl's built mode forwards SSH public keys and a login user (ADR 0017) and needs Rocky Linux
9.8 to install unattended onto the partition's one blank disk, reboot, and boot that disk through
the launcher's installed-disk entry (ADR 0018, hmc-mcp ADR 0191). The Rocky profile hands off to
an interactive Anaconda with no Kickstart (ADR 0013), and `build` refuses manifests carrying the
login values. The keys are untrusted, printable, single-line strings of up to 8,192 characters.
pykickstart splits each command line with `shlex.split(line, comments=True)`, treats a line
starting with `%` as a section boundary, and then hands the tokens to `argparse`, which reads any
token starting with `-` as an option. The launcher already copies a media Kickstart, checks its
size and SHA-256 against the command line, and passes `inst.ks=cdrom:LABEL=...` (ADR 0011).

## Decision

- **Trigger.** A `rocky` profile in a manifest that carries `ssh_authorized_keys` and `login_user`
  installs unattended; without them it stays ADR 0013's interactive handoff. The profile grammar
  does not change. `build` refuses login values unless every profile in the manifest is `rocky`.
- **Derivation.** `build` renders the Kickstart from the parsed manifest: the fixed template
  `assets/kickstart/rocky-9.8-unattended.ks`, then generated lines. It stages the result as
  `/profiles/<profile>/ks.cfg`, and its path, size, and SHA-256 ride the command line as
  `iso_chain.profile_kickstart_*`, so `verify_launcher_log` recomputes them from the manifest.
- **Login.** One `user --name=<login_user>` line with no password and no group, then one `sshkey`
  line per key, each value written with `shlex.quote`, which `shlex.split` inverts exactly. `build`
  refuses a key starting with `-`, which no quoting keeps from `argparse`, and an `lpar` ending in
  `-`, which Anaconda rejects as a host name. The root account stays locked (`rootpw --lock`).
- **Disk.** The template names no device. Its `%pre` counts non-optical disks as ADR 0018 does,
  refuses unless exactly one is present with zero first and last MiB, and writes the partitioning
  for that disk into the `%include` file. This repeats the launcher guard inside the installer.
  The `bootloader` line carries `--leavebootorder`, so Anaconda does not rewrite a PowerVM
  partition's firmware boot list to the disk, and appends `ipv6.disable=1` as every earlier
  kernel in the chain does.
- **Network.** A generated `%post` replaces every NetworkManager and `ifcfg` connection on the
  installed system with one keyfile matching the manifest MAC: the manifest address, default
  gateway, other routes, and DNS servers, with IPv6 disabled. `network --hostname` sets the
  manifest `lpar`.
- **End.** The Kickstart ends with `reboot`, leaving the ISO attached and first in the boot
  order, so ADR 0018's menu boots the installed disk. The `installed disk` entry echoes
  `ISO_CHAIN: GRUB installed-disk handoff`.
- **Harness.** `install-rocky` installs in QEMU with `-no-reboot`, so the Kickstart's reboot ends
  the first run, then boots the same disk, ISO, and NIC until the console shows `<lpar> login:`.
  `verify-rocky-install-evidence` re-derives the result from those records, including the
  kernel's `reboot: Restarting system` line that tells the reboot from a power-off.

Specification: [Rocky unattended install](../workflow/specs/2026-10-02-rocky-unattended-install-design.md).

## Consequences

- Built-mode Rocky media installs over a blank disk with no prompt. A second disk, a non-blank
  disk, or a Fedora, Ubuntu, or openSUSE profile beside the keys is refused before anything runs.
- The login user has no password and no sudo rule, so the installed system has key-based login
  but no administrative account. Granting one needs its own decision.
- A manifest that changes keys, user, or network changes the Kickstart and so the ISO digest.
- Prepared keyless Rocky media keeps ADR 0013's interactive handoff and kernel command line;
  every ISO's `grub.cfg` gains the installed-disk echo line, so every ISO digest changes.
- QEMU's SLOF cannot show whether firmware keeps the boot list; `--leavebootorder` is the
  native guarantee, and its proof belongs to hmc-mcp#1230.
- ADR 0013's unpinned stage2 and AppStream residual now covers the installed packages too.

## Considered & rejected

- **An operator-supplied Kickstart in the Rocky profile, as Fedora has.** judgment: fit; the keys
  and network arrive per request (ADR 0017), so a shared profile file would need host-side
  rewriting, and its manifest digest would no longer describe the media.
- **Double-quote each key.** judgment: complexity; `shlex` handles backslash inside double quotes,
  so escaping has two cases where `shlex.quote` has one tested inverse.
- **Name the disk in the template (`vda`, `sda`).** verified: the Fedora fixtures differ only in
  that name (`diff assets/kickstart/fedora-44-power9.ks assets/kickstart/fedora-44-powervm.ks`,
  d0f4153), so one fixed name cannot serve both QEMU virtio and PowerVM vSCSI.
- **Keep the connection Anaconda carries over from the `ip=` boot arguments.** judgment: fit; it
  binds to the interface name `iso0` that the launcher's `ifname=` chose, not to the MAC, and it
  is not this design's artifact to bound.
- **Kickstart `network --device=<mac>` instead of a keyfile.** judgment: fit; it has no option for
  routes other than the default, which manifest v4 allows.
- **Grant the login user `wheel` or passwordless sudo.** judgment: fit; the issue asks for the
  user and keys only, and `wheel` without a password grants nothing.
- **Power off, as the Fedora fixture does.** judgment: fit; hmcpctl leaves the media mounted and
  waits for boot, so a power-off would strand the partition.
- **Do nothing.** judgment: fit; hmcpctl's built mode stays refused for Rocky.
