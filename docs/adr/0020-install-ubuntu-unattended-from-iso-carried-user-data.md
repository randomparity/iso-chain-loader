# ADR 0020: Install Ubuntu Unattended From ISO-Carried User Data

## Status

Accepted

> **Administrative access decided** (2026-10-04): the login user's lack of administrative access,
> recorded in the Consequences below, is
> [0023](0023-grant-the-login-user-no-administrative-access.md)'s decision for both profiles.

## Context

hmcpctl's built mode forwards SSH public keys and a login user (ADR 0017) and needs Ubuntu 26.04.1
LTS to install unattended onto the partition's one blank disk, reboot, and boot that disk through
the launcher's installed-disk entry (ADR 0018, hmc-mcp ADR 0191). The Ubuntu profile kexecs casper
with `ip=`, `BOOTIF=`, and `iso-url=`, and never mounts the launcher media (ADR 0012), so nothing
carries the keys to subiquity. Subiquity reads autoinstall configuration from cloud-init's user
data. cloud-init's NoCloud datasource reads `user-data` and `meta-data` from the root of an
iso9660 or vfat volume whose label is its `fs_label`, `cidata` by default. The launcher ISO's label
is `ISO_CHAIN_<16 hex>` (ADR 0011), and the kernel command line is capped at 2,048 bytes. The keys
are untrusted, printable, single-line strings of up to 8,192 characters.

## Decision

- **Trigger.** An `ubuntu` profile in a manifest that carries `ssh_authorized_keys` and
  `login_user` installs unattended; without them it stays ADR 0012's interactive handoff. The
  profile grammar does not change. `build` refuses login values unless every profile in the
  manifest is `rocky`, or every profile is `ubuntu`.
- **Channel.** `build` renders `/user-data` and writes an empty `/meta-data` at the launcher ISO's
  root. The user data's size and SHA-256 ride the launcher command line as
  `iso_chain.profile_user_data_size` and `iso_chain.profile_user_data_sha256`. Before downloading,
  the launcher mounts the one optical device whose `config.json` matches, as it does for a
  Kickstart. It requires that no other block device carries the label in any form NoCloud matches:
  the upper-case label, its lower-case form, or a FAT boot-sector label. It checks the user data's
  size and digest and that `meta-data` is an empty regular file, and prints `media: passed`. It then
  adds `autoinstall ds=nocloud cc:datasource:%20{NoCloud:%20{fs_label:%20<label>}}%20end_cc` to
  casper's command line. `ds=nocloud` makes cloud-init's `ds-identify` select NoCloud; the `cc:`
  token is cloud-init's kernel-command-line configuration, which sets NoCloud's `fs_label` to the
  launcher ISO's label; `autoinstall` makes subiquity install without its confirmation prompt.
- **Encoding.** The user data is `#cloud-config` followed by one JSON document, which YAML reads
  as flow collections: `json.dumps(..., ensure_ascii=False)` writes each key as one double-quoted
  scalar in which only `"` and `\` are escaped, and every character Python calls printable is a
  YAML printable character. The fixed parts come from `assets/autoinstall/ubuntu-26.04.1.json`.
- **Login.** The autoinstall `user-data` section, which subiquity passes to the installed system's
  cloud-init, creates one user named `login_user` with `lock_passwd: true`, a Bash shell, and the
  manifest's keys in order, with no `sudo` entry and no groups; it lists no `default` user, sets
  `disable_root: true`, and sets the host name to `lpar`. There is no `identity` section, so no
  password exists. `ssh` installs the server with password authentication off. This matches
  ADR 0019. `build` refuses `root` as the login user, because cloud-init would skip creating it
  and could still give it the keys.
- **No alternate source.** `apt` sets `geoip: false`, `fallback: offline-install`, and an empty
  `mirror-selection.primary` list, so subiquity has no candidate mirror, marks the network
  unusable for installation, and installs only from the live ISO's own packages: it runs no
  archive check, no package download, and no unattended upgrade. `refresh-installer.update` is
  `false`, no snaps are listed, and `timezone` is fixed to `Etc/UTC`.
- **Network.** The autoinstall `network` section is netplan version 2: one ethernet matched by
  the manifest MAC, keeping its kernel name, with the manifest address, the default route, up to
  two DNS servers, and `dhcp4`, `dhcp6`, `accept-ra`, and link-local addresses off. Subiquity
  applies it in the installer and writes it to the installed system. The installer command line
  ends in `--- ipv6.disable=1 rd.systemd.mask=systemd-networkd.service
  rd.systemd.mask=systemd-networkd.socket`, and curtin carries those arguments and `console=hvc0`
  into the installed system's kernel command line. The installed 26.04.1 system boots a dracut
  initrd whose networkd, with no `ip=` argument, runs DHCP on every non-loopback interface; the
  masks stop networkd in the initrd only, and the installed system's own networkd then applies the
  netplan configuration. The installer's casper initrd ignores `rd.` arguments.
- **Disk.** `early-commands` repeats ADR 0018's count and blank checks, as ADR 0019's `%pre` does,
  prints `autoinstall-disk: passed <disk>`, and stops the install unless they pass. Storage uses
  the `direct` layout, which subiquity places on the largest disk, so the one disk the check
  counted.
- **Completion marker.** Subiquity runs curtin's `grub-install`, which creates
  `/boot/grub/grubenv`, before it creates the user, installs the SSH server, and configures
  cloud-init. So a `grubenv` alone does not show a finished install. The template's one
  `late-commands` entry, which subiquity runs after those steps, sets `iso_chain_installed=1` in
  the installed `grubenv`. This extends ADR 0018's Menu decision for an ISO whose profiles are all
  unattended Ubuntu: after the search finds a `grubenv`, the menu loads only that variable from it
  and defines the `installed disk` entry only when its value is `1`. An install interrupted
  before the late command leaves a non-blank disk without the marker, so the installer entry stays
  the default and the launcher's guard refuses the disk visibly.
- **End.** `shutdown: reboot`. The ISO stays attached and first, so ADR 0018's menu boots the
  installed disk; Ubuntu's `grubenv` is at `/boot/grub/grubenv`, one of the four searched paths.
- **Harness.** `install-ubuntu` and `verify-ubuntu-install-evidence` share `install-rocky`'s
  helpers and evidence shape. The verifier also requires exactly the kernel, initrd, and live ISO
  requests in the access log, the whole casper command line, and `autoinstall-disk: passed` lines
  after the handoff that all name one disk, which only a run that read the user data prints;
  subiquity's console client may repeat the line when it replays its journal.

Specification: [Ubuntu unattended install](../workflow/specs/2026-10-03-ubuntu-unattended-install-design.md).

## Consequences

- Built-mode Ubuntu media installs over a blank disk with no prompt. A second disk, a non-blank
  disk, or a Fedora or openSUSE profile beside the keys is refused before anything is written.
- The installer still makes network contacts that are not install sources: subiquity's geoip
  lookup, which has no autoinstall setting, snapd's store connection, whose refresh casper holds,
  and the live system's NTS time servers. The experiment records which hosts each run reached.
- The installed system keeps Ubuntu's defaults after `boot_started`: its apt sources name the
  ports archive, and its periodic updates and time service use the network. The initrd's default
  DHCP network file stays in `/run`, so an interface the netplan configuration does not match gets
  DHCP from the installed system's networkd, as an unconfigured interface would under Rocky's
  NetworkManager. The bootstrap's
  no-fallback rule ends where hmcpctl's proof does.
- The login user has key-based login and no administrative access, as ADR 0019 records.
- A manifest that changes keys, user, or network changes the user data and so the ISO digest.
  Keyless Ubuntu media is unchanged.
- casper's `iso-url` download of the live ISO stays unverified in the guest (ADR 0012); it now
  supplies every installed package.
- The rendered user data is read from the media twice, by the launcher and by cloud-init, as a
  Kickstart is read by the launcher and by Anaconda (ADR 0011). A volume attached between the two
  reads is not checked; whoever can attach media to the partition already chooses what it boots.
- If cloud-init does not read the user data, subiquity starts its interactive installer and waits;
  the stall, and the missing `autoinstall-disk` line, are what show the failure. A launcher
  initramfs prepared before this decision ignores the user-data arguments and starts that
  interactive installer too, so a keyed Ubuntu ISO needs a launcher prepared from this revision.
- A Rocky and an Ubuntu profile cannot share one keyed ISO, because the completion marker governs
  the whole menu and only the Ubuntu template writes it.

## Considered & rejected

- **Label the launcher ISO `CIDATA`.** judgment: fit; the `ISO_CHAIN_<hex>` label is how the
  launcher, Anaconda, and the evidence identify the media, and only Ubuntu would need another.
- **Append a cpio overlay holding `autoinstall.yaml` to the pinned initrd.** judgment: complexity;
  it reverses ADR 0012's rejection and needs a casper hook or preseed command to copy the file into
  the live root, where the `cc:` token needs neither.
- **Put the configuration on the kernel command line.** verified: one maximum-length key alone is
  8,192 bytes against `MAX_COMMAND_LINE_BYTES = 2048` (`scripts/iso_chain.py`, 8a00478).
- **Fetch user data from the source with `ds=nocloud;s=<url>`.** judgment: fit; the source is the
  operator's shared mirror, and per-request keys would need per-request files and a second fetch
  that nothing pins.
- **An autoinstall `identity` section.** verified: subiquity 26.04.1's identity schema requires a
  password hash, and `IdentityController.load_autoinstall_data` accepts a `user-data` section in
  its place (`subiquity/server/controllers/identity.py`, subiquity snap revision 7406).
- **Render YAML text from a template.** judgment: complexity; YAML has several quoting styles and
  indentation rules, while one JSON serialiser has one tested inverse.
- **Keep the default mirror with `fallback: offline-install`.** verified: subiquity checks each
  candidate mirror with `apt-get update` before falling back
  (`MirrorController.find_and_elect_candidate_mirror`, snap revision 7406), so the archive would
  be contacted.
- **Rename the interface with netplan `set-name`.** verified: a QEMU 10.2.2 pSeries run of the
  26.04.1 installer with `set-name: iso0` logged `iso0: Reconfiguring with
  /run/systemd/network/10-netplan-zz-all-en.network` and `iso0: DHCPv4 address 10.0.2.15/24 ...
  acquired` in the installer journal while the rename applied (2026-10-03).
- **Treat `grubenv` alone as the installed marker, as ADR 0018 does.** verified: subiquity's
  `InstallController.install` runs `curtin_install`, whose curthooks install GRUB, before
  `postinstall` creates users and configures cloud-init
  (`subiquity/server/controllers/install.py`, snap revision 7406), so an interrupted install
  would boot a disk with no login user.
- **Skip curtin's GRUB step and install GRUB in a late command.** judgment: complexity; it moves
  PReP and GRUB installation from curtin into launcher-owned shell.
- **Rebuild the installed initrd without dracut's networkd module.** judgment: complexity; it
  needs a late command that edits dracut configuration and regenerates the initrd in the target.
- **Carry a static `ip=` to the installed kernel.** judgment: fit; casper reads the last `ip=` on
  its own command line, so a carried one would replace the installer's, and dracut's form names
  an interface that the manifest does not know.
- **Use the live installer's `ip=` network for the installed system.** judgment: fit; casper names
  the interface `enp0s3`-style rather than by MAC, and the installed configuration is this ADR's
  artifact to bound.
- **Do nothing.** judgment: fit; hmcpctl's built mode stays refused for Ubuntu.
