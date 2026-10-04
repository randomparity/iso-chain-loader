# Ubuntu Unattended Install Design

Issue: #24. Decision: [ADR 0020](../../adr/0020-install-ubuntu-unattended-from-iso-carried-user-data.md).
Reuses ADR 0017 (login values), ADR 0018 (installed-disk menu and launcher disk guard), and the
ADR 0019 harness and evidence shape.

## Problem

hmcpctl's built mode sends SSH keys and a login user, but `build` refuses them for Ubuntu
profiles, and the Ubuntu 26.04.1 profile only reaches an interactive subiquity whose handoff never
reads the launcher media. Built-mode media must install Ubuntu unattended onto the one blank disk,
reboot, and boot that disk through the ISO's installed-disk entry with the ISO attached.

## Scope

In scope:

- `_build_manifest` refuses login values unless every profile is `rocky` or every profile is
  `ubuntu`, and renders the media before any external command runs.
- `_ubuntu_user_data(manifest) -> bytes` renders ADR 0020's user data; it refuses an `lpar` ending
  in `-`, as `_rocky_kickstart` does, and a rendering over 1 MiB.
  `_profile_user_data(manifest, name) -> bytes | None` returns it for an Ubuntu profile with login
  values and `None` otherwise.
- `_kernel_arguments` adds `iso_chain.profile_user_data_size` and `_sha256` after the live ISO path
  for such a profile; `_stage_profile_artifacts` writes `/user-data` and an empty `/meta-data` once;
  `_grub_config` adds the completion-marker check to `INSTALLED_DISK_MENU` when the manifest
  carries login values and its profiles are Ubuntu.
- `_ubuntu_handoff(manifest, profile, label)` returns the whole casper argument list, with the
  unattended tokens when `label` is given; `verify_launcher_log` compares the whole installer
  command line with it for every Ubuntu profile, and requires `media: passed` for unattended ones.
- Launcher: parse the two user-data arguments; `valid_ubuntu_arguments` accepts both or neither,
  with a size of at most 1 MiB; any other distribution with either is invalid; `check_capacity`
  counts the size; `launch_ubuntu` with user data runs `find_media`, refuses any block device that
  `blkid` reports under the lower-case label or `LABEL_FATBOOT=<label>`, copies and checks
  `/user-data`, requires `/meta-data` to be an empty regular non-symlink file, unmounts, then
  downloads and kexecs with `ubuntu_command_line`'s unattended form.
- `assets/autoinstall/ubuntu-26.04.1.json`, the fixed autoinstall keys.
- `install-ubuntu` and `verify-ubuntu-install-evidence`, sharing `install-rocky`'s code.
- ADR 0012 consequence line, README, AGENTS.md, `.secrets.baseline` line numbers, and a QEMU
  experiment record.

No ownership transition: media staging and command-line binding stay in `build`, the handoff stays
in the launcher, and `install-rocky` keeps its name and behavior on the shared helper.

### Rendered user data

`#cloud-config\n` then `json.dumps({"autoinstall": doc}, ensure_ascii=False, indent=2,
sort_keys=True)` and `\n`. `doc` is the template plus:

```text
network: {version: 2, ethernets: {iso0: {match: {macaddress: <mac>},
          addresses: [<address>], routes: [{to: default, via: <gateway>}],
          nameservers: {addresses: [<dns>...]},       # omitted when the manifest has no DNS
          dhcp4: false, dhcp6: false, accept-ra: false, link-local: []}}}
user-data: {hostname: <lpar>, disable_root: true,
            users: [{name: <login_user>, lock_passwd: true, shell: /bin/bash,
                     ssh_authorized_keys: [<key>...]}]}  # manifest order
```

The template holds `version: 1`; `early-commands` with one `sh -c` script that counts
`/sys/block` entries with a `device` link and a name not starting `sr`, requires one, requires its
first and last 1 MiB to hash as zeros, and otherwise prints `autoinstall-disk: failed ...` and
exits 1, else prints `autoinstall-disk: passed <disk>`; `late-commands` with one entry,
`curtin in-target --target=/target -- grub-editenv /boot/grub/grubenv set iso_chain_installed=1`;
`refresh-installer: {update: false}`; `apt: {geoip: false, fallback: offline-install,
mirror-selection: {primary: []}}`; `storage: {layout: {name: direct}}`;
`ssh: {install-server: true, allow-pw: false}`; `timezone: Etc/UTC`; and `shutdown: reboot`. No
template text contains `iso-chain`, because subiquity echoes the script to the console that
`verify_launcher_log` scans for `iso-chain` failure lines.

### Handoff

The unattended casper command line is `ip=<...> BOOTIF=01-<mac> iso-url=<source><live_iso.path>
autoinstall ds=nocloud cc:datasource:%20{NoCloud:%20{fs_label:%20<label>}}%20end_cc console=hvc0
--- ipv6.disable=1 rd.systemd.mask=systemd-networkd.service
rd.systemd.mask=systemd-networkd.socket`, where `<label>` is the ISO volume ID. curtin carries the
arguments after `---` to the installed kernel, where the masks stop the dracut initrd's default
DHCP on every interface. Keyless Ubuntu keeps `ip=... BOOTIF=... iso-url=... console=hvc0
ipv6.disable=1`.

### Completion marker

For a keyed all-Ubuntu manifest, `INSTALLED_DISK_MENU` also records the found directory's
`grubenv` path and, when a disk was found, runs `load_env --file <that grubenv>
iso_chain_installed` and clears the found disk unless the variable is `1`. Other manifests keep
today's menu text.

### Harness and evidence

`install-ubuntu` takes `install-rocky`'s arguments and requires a selected Ubuntu profile with
login values; both commands run one shared function. `verify-ubuntu-install-evidence` takes
`verify-rocky-install-evidence`'s arguments and runs the same checks, except that its access log
must be exactly the kernel, initrd, and live ISO requests at their pinned sizes, all 200, and its
install console must hold at least one line matching
`autoinstall-disk: passed [a-z][a-z0-9]*`, every one after `kexec-exec: started` and naming the
same disk. The result's second line is `user-data: passed`.

## Failure model

1. Actors and deployments
   - hmcpctl or an operator building media from a manifest whose keys and user come from a caller.
   - The built ISO booting on QEMU pSeries/POWER9 or a PowerVM LPAR (native run: hmc-mcp#1230).
   - A developer running the unit and shell suites on Linux or macOS.
2. Invariants and assets at stake
   - Data on any disk that is not the one blank non-optical disk: never written.
   - An install interrupted before its completion marker never becomes the default boot entry.
   - The user data's YAML structure: no key or user value adds, removes, or changes a key.
   - The installed system's interface with the manifest MAC: exactly the manifest's static IPv4
     configuration.
   - Install content: only the pinned kernel and initrd and the live ISO casper fetched.
   - Keyless Ubuntu media: the same kernel command line and launcher handoff as before.
3. Accepted failure classes
   - A printable key that is not a valid OpenSSH key installs and does not work, and a
     `login_user` naming another account the base system already has gives that account the
     keys: hmcpctl owns both grammars (ADR 0017). `build` refuses `root`.
   - A disk appearing after the `early-commands` count is not counted: ADR 0018 accepts this.
   - Network contacts that supply no install content: geoip, snapd's store, NTS time (ADR 0020).
   - The installed system's own updates and time service after `boot_started` (ADR 0020).
   - An interface other than the manifest MAC's gets DHCP from the installed system's networkd
     after `boot_started`, through the initrd's default network file (ADR 0020).
   - The live ISO is unverified in the guest (ADR 0012).
   - A volume attached after the launcher's media check and before cloud-init reads it is not
     checked: whoever attaches media to the partition already chooses what it boots (ADR 0020).
   - cloud-init not reading the user data leaves subiquity's interactive installer waiting; the
     stall and the missing `autoinstall-disk: passed` line show it, and the harness times out.
   - An install interrupted after the late command and before the reboot boots as installed:
     only log copying and the reboot follow that command.
   - A Fedora or openSUSE `grub.cfg` the ISO's GRUB cannot load stops at GRUB (ADR 0018); an
     Ubuntu 26.04.1 one that does not load fails Success 7.
4. Covered elsewhere
   - Native PowerVM proof, CAS replay, firmware boot order, and media detach: hmc-mcp#1230.
   - Lifting Ubuntu's one-route and two-DNS limits: an operator decision, out of scope.
   - Producer result format: hmcpctl, `iso-chain-media-v1` unchanged.

### Threat model

- Boundaries widened: manifest `ssh_authorized_keys`, `login_user`, and `lpar` (caller-controlled,
  bounded by ADR 0017 and manifest validation) now enter YAML read by cloud-init and subiquity; the
  guest disk set enters `early-commands`. Boundary added: the launcher reads `/user-data` and
  `/meta-data` from the media, controlled by the size and digest grammar, the digest check, the
  empty-file check, and the label-uniqueness check in `find_media`. Guest console output reaches
  the harness's marker watch and the verifiers, controlled by byte bounds and ordered re-derivation.
- Actors: the hmcpctl caller who supplies keys and user; whoever attaches disks or optical media
  to the partition.
- Controls: ADR 0017 validation, then JSON serialisation of every caller value as one quoted
  scalar, tested by parsing the rendering with `json` after the header, with the QEMU record
  showing cloud-init and subiquity read the same keys; network values pass manifest validation;
  the `early-commands` checks fail closed; a second volume carrying the launcher's label in any
  form NoCloud matches (upper case, lower case, FAT boot label) fails the launcher before
  cloud-init can choose between them; errors name the field, never its value.
- Out of scope: a caller who controls the operator's base manifest or source mirror (trusted per
  ADR 0011); administrative access on the installed system (ADR 0019 Consequences).

## Success

1. `build` accepts login values when every profile is `rocky` or every profile is `ubuntu`, and
   refuses them, before any external command, for any other mix.
2. For an Ubuntu profile with login values, the ISO carries `/user-data` equal to
   `_ubuntu_user_data(manifest)` and an empty `/meta-data`, and the command line binds the user
   data's size and digest; its `grub.cfg` carries the completion-marker check; keyless Ubuntu
   command lines and ISOs, and every other ISO's `grub.cfg`, are unchanged.
3. For keys holding `'`, `"`, `\`, `#`, `:`, `{`, `-`, `%`, and non-ASCII characters, the
   rendering parses as JSON after its header line to the exact keys, user, host name, and
   network; its top level is only `autoinstall`; it carries no `iso-chain` text; an `lpar`
   ending in `-` is refused.
4. The launcher accepts Ubuntu arguments with or without valid user data, rejects partial or
   oversized user data and user data on another distribution, refuses a mismatched digest, a
   non-empty `meta-data`, or a second volume under the lower-case or FAT boot label, and passes the
   unattended casper line only when user data is present.
5. `verify_launcher_log` requires `media: passed` and the exact unattended casper line for an
   unattended Ubuntu profile, and the exact keyless line otherwise.
6. `verify-ubuntu-install-evidence` accepts a consistent record set and rejects each broken input.
7. A QEMU pSeries/POWER9 record: unattended install to one blank disk, reboot, installed-disk boot
   through the ISO's entry with the ISO attached, an operator SSH login with the injected key on a
   disposable overlay of the evidence disk, and an install stopped before its late command whose
   next boot stays on the installer entry and fails the launcher's blank-disk guard, labelled as
   emulator evidence.

## Validation

- Success 1, 2, 3: focused-test, `BuildTests` (including the menu text) and a new
  `UbuntuUserDataTests` in `tests/test_iso_chain.py`.
- Success 4: focused-test, Ubuntu cases in `tests/test_iso_chain_launch.sh`.
- Success 5: focused-test, `UbuntuEvidenceTests` launcher-log cases.
- Success 6 and `install-ubuntu` command shape: focused-test, `UbuntuInstallEvidenceTests` and
  `InstallTests`.
- Success 7: task-test-not-applicable; a QEMU install with emulated firmware that the unit suites
  cannot run, recorded in `docs/experiments/2026-10-03-ubuntu-unattended-install.md`.
- ADR 0012 line, README, AGENTS.md: task-test-not-applicable; prose with no executable consumer.
