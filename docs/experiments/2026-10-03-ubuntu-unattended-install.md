# Ubuntu Unattended Install VM Experiment

Date: 2026-10-03

## Result

A QEMU pSeries/POWER9 guest booted a launcher ISO built from a manifest carrying two SSH public
keys and a login user. The launcher checked the ISO-root user data that `build` derived from that
manifest, then kexecd casper with `autoinstall`, `ds=nocloud`, and the `cc:` token naming the
ISO's label. cloud-init's NoCloud datasource read the user data from the launcher ISO, and
subiquity installed Ubuntu 26.04.1 LTS with no prompt onto the one blank 20 GiB virtio disk,
offline from the live ISO's packages, then rebooted. With the launcher ISO still first in the boot
order, the ISO's GRUB found the installed disk's `grubenv` with `iso_chain_installed=1`, printed
`ISO_CHAIN: GRUB installed-disk handoff`, and loaded Ubuntu's own `grub.cfg`. Ubuntu booted to
`ubuntu-qemu login:` on the console. An operator logged in over SSH with the injected key on a
disposable overlay of that disk. `verify-ubuntu-install-evidence` passed. A second install,
stopped after GRUB was installed but before the completion marker, booted the launcher's installer
entry again, and the launcher refused the non-blank disk. This is emulator evidence only: native
PowerVM was not run.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 8,192 MiB, through `install-ubuntu`. The guest used QEMU's user-mode network with
  its documented default addresses (`10.0.2.15/24`, gateway `10.0.2.2`, DNS `10.0.2.3`) and the MAC
  `52:54:00:12:34:56`.
- **Source.** The pins and the `gpgv`-checked live-server ISO of the
  [Ubuntu installer experiment](2026-10-02-ubuntu-installer.md): ISO SHA-256
  `3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826`, netboot `linux` and `initrd`
  pinned by `prepare-ubuntu-source`. `serve-source` served them on loopback.
- **Manifest.** One `ubuntu` profile with `minimum_memory_mib` 5888, `lpar` `ubuntu-qemu`, a test
  login user, and two keys: a fresh Ed25519 test key, and the same key with a comment holding a
  single quote, a double quote, a backslash, `#`, `%pre`, Cyrillic text, and the YAML indicators
  `:`, `{}`, `-`, `[]`, `&`, `*`, `!`, `|`, and `>`. The canonical manifest digest was
  `35af0a04ddf304a7249babf644487f9e14c24979f9579ca020520fe48429b57e`.
- **Launcher build.** Commit `c0e883d`. The launcher kernel was Fedora 7.2.8-200.fc44 with an
  initramfs from the `iso-chain-initramfs:44` image. The ISO was 109,858,816 bytes, SHA-256
  `b793a9e712592a433baa97290437a878e35f4e105531edd7cf7e939da56ce0b2`, volume ID
  `ISO_CHAIN_35AF0A04DDF304A7`. Its `/user-data` was 2,679 bytes, SHA-256
  `6a69bcdb602013d1e3c568d2dc109b22dfc519d27b2a4b0943f5de7d0dc3007c`, equal to the rendering from
  the manifest, and its `/meta-data` was empty.
- **Build-host deviations.** As in the earlier records, both container commands ran with
  `--security-opt label=disable`, and the initramfs build copied `scripts/` and `assets/` without
  extended attributes.

Raw manifests, keys, console logs, access logs, captures, and disks remain in private storage.

## Spikes

Before the build, two direct kernel boots of the netboot kernel and initrd with a hand-built seed
ISO tested the channel. Both installed and rebooted in about 15 minutes with four CPUs. The first
renamed the interface with netplan `set-name: iso0`; the installer journal then showed
`iso0: Reconfiguring with /run/systemd/network/10-netplan-zz-all-en.network` and a DHCPv4 lease
while the rename applied. The second, without `set-name`, made no DHCP request. ADR 0020 records
the choice. The spikes are not part of the evidence.

## Run

The first acceptance run, at commit `55dc75d`, installed and booted, but its boot capture held a
DHCP exchange. The installed system boots a dracut initrd whose networkd, with no `ip=` argument,
copies a default network file with `DHCP=yes` for every non-loopback interface. A direct boot of
that installed kernel and initrd with `rd.systemd.mask=systemd-networkd.service
rd.systemd.mask=systemd-networkd.socket` made no DHCP request and reached the login prompt, so
`c0e883d` carries those arguments to the installed kernel after `---`. With the commit that built
its ISO, `verify-ubuntu-install-evidence` rejected the first run with `packet capture contains DHCP
or IPv6`. The acceptance run below used `c0e883d` with a fresh server, access log, disk, and output
directory.

- **Install phase.** The launcher printed `memory: passed memtotal_mib=8065 memavailable_mib=7673`,
  then `disk: passed` and `media: passed`. casper's kernel printed the whole unattended command
  line; it reported `autoinstall`, the `cc:` token, and `---` as unknown kernel parameters and
  passed them to user space. The `early-commands` guard printed `autoinstall-disk: passed vda` once.
  Subiquity partitioned `vda` as an 8 MiB PReP partition and an ext4 root, installed from the live
  ISO, ran the late command, and the kernel printed `reboot: Restarting system` about 16 minutes
  after the handoff. QEMU's `-no-reboot` turned that into the first run's exit 0.
- **Boot phase.** The second run attached the same ISO, disk, and NIC. The console showed one
  `ISO_CHAIN: GRUB installed-disk handoff`, no optical handoff, no launcher output, then Ubuntu's
  kernel 7.0.0-30-generic and the `ubuntu-qemu login:` prompt, at which the harness stopped QEMU.

## Evidence

- **Access log.** Exactly three requests, in order and each once: the kernel, the initrd, and the
  live ISO, at their pinned sizes.
- **Captures.** Derivatives of the install and boot captures keeping only IPv6, DHCP, and BOOTP
  packets held only their headers. During the install the guest resolved and reached
  `geoip.ubuntu.com`, `api.snapcraft.io`, and the `ntp.ubuntu.com` NTS servers over the static
  default route; it resolved no archive host and fetched no package from the network. During the
  boot the installed system resolved only the `ntp.ubuntu.com` servers before the harness stopped.
- **Disk.** The fresh disk's digest changed during the install phase; `result.json` records the
  installer's digest and `boot_stop: login-prompt`. The installed `grubenv` held
  `iso_chain_installed=1`.
- **Verifier.** `verify-ubuntu-install-evidence` returned:

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

## SSH session

After the run, a qcow2 overlay backed by the published disk booted with the same ISO first and a
QEMU host forward to port 22; the published disk's digest was unchanged afterwards, and the
session's capture held no DHCP or IPv6 packet. The console again showed the installed-disk handoff.
Logging in with the injected private key showed:

- the login user, with no supplementary group, an empty `sudo` group, and `sudo` refusing;
  `passwd -S` reported the account's password locked;
- host name `ubuntu-qemu`;
- `~/.ssh/authorized_keys` holding exactly the manifest's two keys, byte for byte, in reverse
  order, mode 0600;
- the virtio interface, keeping its kernel name `enp0s3`, at `10.0.2.15/24`, the default route via
  `10.0.2.2`, DNS `10.0.2.3`, and no IPv6 stack;
- `console=hvc0`, `ipv6.disable=1`, and both `rd.systemd.mask` arguments on the installed kernel
  command line;
- `/etc/netplan/00-installer-config.yaml` as the only netplan file, and in `/run/systemd/network`
  the netplan unit and the initrd's default `zzzz-dracut-default.network`, which networkd uses
  only for an interface that no earlier file matches;
- the root file system on `vda2`, and apt sources naming `ports.ubuntu.com`.

The SSH server offered only public-key authentication, so neither root nor the login user could
log in with a password.

## Interrupted install

A fresh disk, the same ISO, and a fresh server ran the install phase again until the console
showed subiquity's `postinstall` step, after curtin had installed GRUB and before the late command,
and the driver then killed QEMU. The disk's `grubenv` held no `iso_chain_installed` variable. The
next boot attached the same ISO, disk, and NIC: the ISO's GRUB found the `grubenv`, defined no
installed-disk entry, and took the default `ubuntu` entry. The launcher printed
`disk-blank: failed` and `disk: failed`, and downloaded nothing more.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. Whether PowerVM firmware keeps the ISO
  first after Ubuntu's GRUB installation, whether the installed-disk entry survives a CAS reboot
  replay, and whether PowerVM's optical device presents the label NoCloud reads belong to
  hmc-mcp#1230; media detach belongs to hmc-mcp#1230.
- The source was a loopback HTTP server. casper over a public HTTPS mirror was not tested.
- The guest saw one virtio disk and one NIC. The `early-commands` refusals for zero, two, or
  non-blank disks were not run under QEMU; the launcher's guard, which runs first with the same
  rule, was proven for those cases in the
  [installed-disk experiment](2026-10-02-installed-disk-boot.md).
