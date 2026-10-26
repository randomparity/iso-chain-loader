# Ubuntu Preset Customization VM Experiment

Date: 2026-10-26

## Result

A launcher ISO built from a target-v2 system, a block-v1 shared block and a prepared base selected
the `ubuntu-26.04.1-server` revision 1 preset with London time, British English and a British
keyboard. Under QEMU pSeries/POWER9, Ubuntu 26.04.1 LTS installed unattended from the ISO-carried
user data onto one blank 20 GiB virtio disk, offline from the live ISO's packages, and rebooted.
With the ISO still first, its GRUB printed `ISO_CHAIN: GRUB installed-disk handoff` and Ubuntu
booted to `ubuntu-preset-b login:`. `verify-ubuntu-install-evidence` passed at the commit that
built the media. The installed disk held keyboard layout `gb`, and the login user was locked and
unprivileged.

The selected timezone and locale were **not** applied by the installation. Subiquity leaves both
to cloud-init on the installed system's first boot, and the harness stops that boot at the login
prompt. It stopped while cloud-init's `locale` module was running and before its `timezone`
module started. The published disk kept `Etc/UTC` and no system locale. A later inspection boot of
a disposable overlay applied `Europe/London`, but skipped the locale, which cloud-init had already
recorded as done. A diagnostic boot of a second overlay, with that record removed, applied
`LANG=en_GB.UTF-8` offline. Applying the timezone and locale before the completion marker, or on
an interrupted first boot, is therefore outstanding. This is emulator evidence only: native
PowerVM was not run.

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
  default route, one DNS server, a test login user, one fresh Ed25519 key and
  `"install": {"timezone": "Europe/London", "locale": "en_GB.UTF-8", "packages": []}`. System B
  supplied the preset, `lpar` `ubuntu-preset-b`, MAC, address and
  `"install": {"keyboard": "gb"}`. System A, which inherits the default `us` keyboard, passed
  `validate-config` with the same base and block; it was not built or installed. The composed
  canonical manifest digest was
  `3e4a4cdafb8b691c21c39c6434f3792a0582a066040453bbe51e8c1129f68646`.
- **Launcher build.** Commit `8520a67`, with a clean tree, rebuilt the launcher initramfs in the
  `iso-chain-initramfs:44` image and then ran `container-build` with the three inputs. As in the
  earlier records, both container commands ran with `--security-opt label=disable` and the asset
  copies carried no extended attributes. The ISO was 109,858,816 bytes, SHA-256
  `042c3e93592b0d5e41d0cfcfd8f3e67a648da1a4095be8b14d3233fa9ab7a342`, volume ID
  `ISO_CHAIN_3E4A4CDAFB8B691C`. Its `/user-data` was 2,603 bytes, SHA-256
  `5fe5cc003de82ea593e1284c6d72314c7e2773ed29c9b099647bd0d0f31dbf03`, equal to the rendering from
  the embedded manifest, and its `/meta-data` was empty. The autoinstall holds
  `"timezone": "Europe/London"`, `"locale": "en_GB.UTF-8"` and
  `"keyboard": {"layout": "gb", "variant": ""}`.

Raw inputs, keys, console logs, access logs, captures, disks and session transcripts remain in
private storage.

## Run

The single acceptance run used a fresh server, access log, disk and output directory; no scratch
run preceded it.

- **Install phase.** The launcher printed `memory: passed memtotal_mib=8065`, `disk: passed` and
  `media: passed`, then kexecd casper with the unattended command line. The `early-commands`
  guard printed `autoinstall-disk: passed vda` once. Subiquity installed from the live ISO,
  configured the keyboard in the target, ran the late command, and the kernel printed
  `reboot: Restarting system` 1,127 seconds after the installer kernel started. The first QEMU
  run exited 0.
- **Boot phase.** The second run attached the same ISO, disk and NIC. The console showed one
  `ISO_CHAIN: GRUB installed-disk handoff`, no launcher output, Ubuntu's 7.0.0-30-generic kernel
  and the `ubuntu-preset-b login:` prompt, at which the harness stopped QEMU.

## Evidence

- **Access log.** Exactly three requests, in order and each once: the kernel, the initrd and the
  live ISO, at their pinned sizes.
- **Captures.** Derivatives of the install and boot captures keeping only IPv6, DHCP and BOOTP
  packets were empty. During the install the guest resolved `geoip.ubuntu.com`,
  `api.snapcraft.io` and the `ntp.ubuntu.com` NTS servers over the static default route and
  reached them; it resolved no archive host and fetched no package from the network. During the
  boot it resolved only `ntp.ubuntu.com` servers before the harness stopped.
- **Disk.** The fresh disk's digest changed during the install phase; `result.json` records
  `install_exit_status` 0 and `boot_stop: login-prompt`.
- **Verifier.** A canonical version-1 record bound the manifest, both consoles, the access log,
  `result.json`, both filtered captures and both disk digests.
  `verify-ubuntu-install-evidence`, run from the commit that built the ISO, returned:

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

After the run, `guestfish --ro` read the published disk. `/etc/default/keyboard` held
`XKBLAYOUT="gb"`, `/etc/localtime` linked to `/usr/share/zoneinfo/Etc/UTC`, `/etc/timezone` was
absent, and `/etc/default/locale` held only its generated header.

Then a qcow2 overlay backed by the published disk booted with the same ISO first and a
QEMU host forward to port 22. Logging in with the injected key showed:

- host name `ubuntu-preset-b`, and the login user with no supplementary group and an empty `sudo`
  group; `sudo -n true` refused and `passwd -S` reported the password locked;
- `/etc/timezone` holding `Europe/London`, `/etc/localtime` linking to
  `/usr/share/zoneinfo/Europe/London`, and `timedatectl` reporting that timezone, all written by
  cloud-init during this inspection boot;
- `/etc/default/keyboard` holding `XKBLAYOUT="gb"` and an empty `XKBVARIANT`, and `localectl`
  reporting X11 layout `gb`;
- `/etc/default/locale` holding only its generated header, no `LANG`, and `locale -a` listing only
  `C`, `C.utf8` and `POSIX`;
- `enp0s3` at `10.0.2.15/24`, the default route via `10.0.2.2`, `/etc/netplan/00-installer-config.yaml`
  as the only netplan file, and `console=hvc0`, `ipv6.disable=1` and both `rd.systemd.mask`
  arguments on the installed kernel command line.

An SSH login as root with the same key was refused. After QEMU stopped, `guestfish --ro` read the
overlay's `/boot/grub/grubenv`, which held `iso_chain_installed=1`. The published disk's digest
was the same before and after the overlay boot.

The installed system's cloud-init log explains both settings. Its `99-installer.cfg` carries
`locale: en_GB.UTF-8` and `timezone: Europe/London`. On the harness boot, the `locale` module
wrote its once-per-instance semaphore and started `locale-gen en_GB.UTF-8`; the log ends there,
when the harness stopped QEMU. On the overlay boot, cloud-init reported `config-locale already
ran`, then ran the `timezone` module and wrote `/etc/timezone`.

For a diagnostic only, a second overlay of the published disk had that semaphore removed with
`guestfish` and booted the same way. After `cloud-init status --wait` returned,
`/etc/default/locale` held `LANG=en_GB.UTF-8`, `locale -a` listed `en_GB.utf8`, `localectl`
reported that locale, and the timezone and keyboard were unchanged. That boot is not part of the
canonical evidence, and it shows the module completes offline, not that an interrupted first boot
recovers.

## Boundary

- No native LPAR, HMC, VIOS or physical storage was used. Native PowerVM proof belongs to the
  operator's native validation workflow and #6.
- Only the keyboard is applied by the installation. The timezone and locale wait for cloud-init
  on the installed system's first boot, after the completion marker is set. The canonical harness
  stops that boot early: the timezone arrived on the next boot and the locale never did. Applying
  both during installation, or a harness stop that waits for cloud-init, is not implemented here.
- Only one customized system was installed. System A's inherited `us` keyboard and the other
  allowed timezone, locale and keyboard values were proven by rendering tests and offline
  validation, not by installation.
- The source was a loopback HTTP server. casper over a public HTTPS mirror was not tested.
