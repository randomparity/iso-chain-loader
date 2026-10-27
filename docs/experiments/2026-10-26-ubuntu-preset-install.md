# Ubuntu Preset Customization VM Experiment

Date: 2026-10-26

## Result

Three launcher ISOs, each built from a target-v2 system, a block-v1 shared block and a prepared
base, selected the `ubuntu-26.04.1-server` revision 1 preset. Under QEMU pSeries/POWER9, each
installed Ubuntu 26.04.1 LTS unattended from the ISO-carried user data onto one blank 20 GiB
virtio disk, offline from the live ISO's packages, and rebooted. With the ISO still first, its
GRUB printed `ISO_CHAIN: GRUB installed-disk handoff` and Ubuntu booted to
`ubuntu-preset-b login:`. `verify-ubuntu-install-evidence` passed for every run at the commit
that built its ISO.

- **Run 1**, at commit `8520a67`, selected London time, British English and a British keyboard.
  The installed disk held keyboard layout `gb`, but kept `Etc/UTC` and no system locale.
  Subiquity leaves the timezone and locale to cloud-init on the installed system's first boot,
  and the harness stops that boot at the login prompt. It stopped while cloud-init's `locale`
  module was running and before its `timezone` module started. A later boot applied the
  timezone, but cloud-init had already recorded the locale as done and skipped it.
- **Run 2**, at commit `4ea9035`, came from an interim change that refused nondefault Ubuntu
  timezone and locale values. It selected the British keyboard with the defaults. The installed
  disk held keyboard layout `gb` and `Etc/UTC`, and again no system locale.
- **Run 3**, at commit `df6be78`, is the acceptance run. It removed that interim refusal and
  added [ADR 0033](../adr/0033-apply-ubuntu-timezone-and-locale-before-the-completion-marker.md)'s
  fixed in-target step before the completion marker, and used run 1's inputs. Read without
  booting it again, the published disk held `Europe/London`, `LANG=en_GB.UTF-8` and keyboard
  layout `gb`, with the login user locked and unprivileged.

This is emulator evidence only: native PowerVM was not run.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs and 8,192 MiB, through `install-ubuntu`. The guest used QEMU's user-mode network with
  its documented default addresses (`10.0.2.15/24`, gateway `10.0.2.2`, DNS `10.0.2.3`) and the
  MAC `52:54:00:12:34:56`.
- **Source.** `SHA256SUMS` passed `gpgv` with the Ubuntu CD image signing key
  (`843938DF228D22F7B3742BC0D94AA3F0EFE21092`), and the live-server ISO matched its signed
  SHA-256 `3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826`. A fresh
  `prepare-ubuntu-source` run produced the same netboot `linux`, `initrd` and profile as the
  [Ubuntu installer experiment](2026-10-02-ubuntu-installer.md). `serve-source` served the three
  files on loopback, and `validate-external-source` passed against them.
- **Inputs.** The base held only version, source and the prepared profile. The block held the
  default route, one DNS server, a test login user and one fresh Ed25519 key. For runs 1 and 3
  its install object was
  `{"timezone": "Europe/London", "locale": "en_GB.UTF-8", "packages": []}`; for run 2 it was
  `{"packages": []}`, because `4ea9035` refused run 1's inputs with
  `manifest install.timezone: ubuntu revision 1 requires the default`. System B supplied the
  preset, `lpar` `ubuntu-preset-b`, MAC, address and `"install": {"keyboard": "gb"}`. System A,
  which inherits the default `us` keyboard, passed `validate-config` with each base and block; it
  was not built or installed.
- **Launcher builds.** Each commit, with a clean tree, rebuilt the launcher initramfs in the
  `iso-chain-initramfs:44` image and then ran `container-build` with the three inputs. As in the
  earlier records, both container commands ran with `--security-opt label=disable` and the asset
  copies carried no extended attributes. Each ISO was 109,858,816 bytes, and each `/user-data`
  equalled the rendering from the embedded manifest, beside an empty `/meta-data`:

| Run | Manifest SHA-256 | ISO SHA-256 | `/user-data` bytes, SHA-256 | Autoinstall settings |
| --- | --- | --- | --- | --- |
| 1 | `3e4a4cdafb8b691c21c39c6434f3792a0582a066040453bbe51e8c1129f68646` | `042c3e93592b0d5e41d0cfcfd8f3e67a648da1a4095be8b14d3233fa9ab7a342` | 2,603, `5fe5cc003de82ea593e1284c6d72314c7e2773ed29c9b099647bd0d0f31dbf03` | `Europe/London`, `en_GB.UTF-8`, `gb` |
| 2 | `39b1a3069da89af256479fc90696636e8a0a00e9571eb5f00809e7c7a3095690` | `ae2ec39aab3020a5ee23940a8c97194f08b2c1f3c2bbca77986ceea3db6d3fbe` | 2,597, `ee3e4d3dd3ae144757763ab1f93819e90c08e23a5ad12b678dfcd1dbf18a596c` | `Etc/UTC`, `en_US.UTF-8`, `gb` |
| 3 | `3e4a4cdafb8b691c21c39c6434f3792a0582a066040453bbe51e8c1129f68646` | `1500e1a9b577638dbbf752747e5c02aa3a5321a8609f3e44c54408f102d1bcec` | 2,980, `285c7ff5ec7c20b06d502182123164167b4f449f7b153210355b30c62d921867` | `Europe/London`, `en_GB.UTF-8`, `gb`, plus the in-target step |

Runs 1 and 3 composed the same manifest, so both used volume ID `ISO_CHAIN_3E4A4CDAFB8B691C`;
run 2 used `ISO_CHAIN_39B1A3069DA89AF2`. Each keyboard renders as
`{"layout": "gb", "variant": ""}`. Run 3's `late-commands` holds the settings step, with
`Europe/London` and `en_GB.UTF-8` as its positional arguments, before the `grub-editenv` marker
command.

Raw inputs, keys, console logs, access logs, captures, disks and session transcripts remain in
private storage.

## Runs

Each run used a fresh server, access log, disk and output directory; no scratch run preceded
any of them.

- **Install phase.** The launcher printed `memory: passed memtotal_mib=8065`, `disk: passed` and
  `media: passed`, then kexecd casper with the unattended command line. The `early-commands`
  guard printed `autoinstall-disk: passed vda` once. Subiquity installed from the live ISO,
  configured the keyboard in the target, ran the late commands, and the kernel printed
  `reboot: Restarting system` 1,127, 1,227 and 1,287 seconds after the installer kernel started
  in runs 1, 2 and 3. Each first QEMU run exited 0. In run 3 the installer log shows the settings
  command succeed, with `en_GB.UTF-8... done` from `locale-gen`, before the marker command
  started.
- **Boot phase.** Each second run attached the same ISO, disk and NIC. The console showed one
  `ISO_CHAIN: GRUB installed-disk handoff`, no launcher output, Ubuntu's 7.0.0-30-generic kernel
  and the `ubuntu-preset-b login:` prompt, at which the harness stopped QEMU.

## Evidence

- **Access logs.** Exactly three requests per run, in order and each once: the kernel, the initrd
  and the live ISO, at their pinned sizes.
- **Captures.** Derivatives of the install and boot captures keeping only IPv6, DHCP and BOOTP
  packets were empty. During each install the guest resolved `geoip.ubuntu.com`,
  `api.snapcraft.io` and the `ntp.ubuntu.com` NTS servers over the static default route and
  reached them; it resolved no archive host and fetched no package from the network. During the
  boots of runs 1 and 2 it resolved only `ntp.ubuntu.com` servers before the harness stopped; run
  3's boot made no DNS query.
- **Disks.** Each fresh disk's digest changed during the install phase; each `result.json`
  records `install_exit_status` 0 and `boot_stop: login-prompt`.
- **Verifier.** For each run, a canonical version-1 record bound the manifest, both consoles, the
  access log, `result.json`, both filtered captures and both disk digests.
  `verify-ubuntu-install-evidence`, run from the commit that built that ISO, returned the same
  result:

```text
manifest: passed
user-data: passed
network-config: passed
http-evidence: passed
installation: passed
reboot: passed
disk-mutation: passed
installed-disk-boot: passed
install-dhcp-ipv6-filter: absent
boot-dhcp-ipv6-filter: absent
same-run: operator-reviewed
```

## Installed settings

After each run, `guestfish --ro` read the published disk, after the harness boot and before any
inspection boot. Then a qcow2 overlay backed by it booted with the same ISO first and a QEMU host
forward to port 22. Each published disk's digest was the same before and after these reads and
boots.

**Run 1.** The published disk's `/etc/default/keyboard` held `XKBLAYOUT="gb"`, its
`/etc/localtime` linked to `/usr/share/zoneinfo/Etc/UTC`, `/etc/timezone` was absent, and
`/etc/default/locale` held only its generated header. On the overlay boot, logging in with the
injected key showed `/etc/timezone` holding `Europe/London`, written by cloud-init during that
boot, and still no `LANG`, with `locale -a` listing only `C`, `C.utf8` and `POSIX`. The installed
system's `99-installer.cfg` carries `locale: en_GB.UTF-8` and `timezone: Europe/London`. Its
cloud-init log shows that on the harness boot the `locale` module wrote its once-per-instance
semaphore and started `locale-gen en_GB.UTF-8`, and the log ends there. On the overlay boot,
cloud-init reported `config-locale already ran` and then ran the `timezone` module.

For a diagnostic only, a second overlay of run 1's disk had that semaphore removed with
`guestfish` and booted the same way. After `cloud-init status --wait` returned,
`/etc/default/locale` held `LANG=en_GB.UTF-8`, `locale -a` listed `en_GB.utf8`, and
`/etc/timezone` held `Europe/London`. That boot is not canonical evidence. It shows that the
settings can be applied offline once cloud-init finishes, not that an interrupted first boot
recovers.

**Run 2.** The published disk held `XKBLAYOUT="gb"` with an empty `XKBVARIANT`, `/etc/localtime`
linked to `Etc/UTC`, `/etc/default/locale` held only its header, and `/boot/grub/grubenv` held
`iso_chain_installed=1`. Logging in on the overlay showed:

- host name `ubuntu-preset-b`, and the login user with no supplementary group and an empty `sudo`
  group; `sudo -n true` refused and `passwd -S` reported the password locked;
- `localectl` reporting X11 layout `gb` and no system locale, and `/etc/timezone` holding
  `Etc/UTC`;
- one authorized key; `enp0s3` at `10.0.2.15/24` with the default route via `10.0.2.2`;
  `/etc/netplan/00-installer-config.yaml` as the only netplan file; and `console=hvc0`,
  `ipv6.disable=1` and both `rd.systemd.mask` arguments on the installed kernel command line.

**Run 3.** The published disk held:

- `/etc/localtime` linking to `/usr/share/zoneinfo/Europe/London`, a regular file, and
  `/etc/timezone` holding `Europe/London`;
- `/etc/default/locale` holding `LANG=en_GB.UTF-8`, and a `locale-archive` in `/usr/lib/locale`;
- `/etc/default/keyboard` holding `XKBLAYOUT="gb"` and an empty `XKBVARIANT`;
- `iso_chain_installed=1` in `/boot/grub/grubenv`.

Its cloud-init log ends at the start of the harness boot's `modules:config` stage, before the
`locale` and `timezone` modules, so the settings above came from the in-target step. On the overlay
boot, `locale -a` listed `en_GB.utf8`, `localectl` reported `LANG=en_GB.UTF-8` and X11 layout
`gb`, and `timedatectl` reported `Europe/London`. The host name, login user, groups, locked
password, single authorized key, network, netplan file and kernel command line matched run 2.

In every run, an SSH login as root with the same key was refused.

## Boundary

- No native LPAR, HMC, VIOS or physical storage was used. Native PowerVM proof belongs to the
  operator's native validation workflow and #6.
- Run 3 proves the in-target step for one allowed timezone and one allowed locale. The other
  allowed values rely on the same step and are proven by rendering tests, not by installation.
  Manifests without `install` keep their legacy user data and still leave both settings to
  cloud-init's first boot.
- Only system B was installed in each run. System A's inherited `us` keyboard was proven by
  rendering tests and offline validation, not by installation.
- The source was a loopback HTTP server. casper over a public HTTPS mirror was not tested.
