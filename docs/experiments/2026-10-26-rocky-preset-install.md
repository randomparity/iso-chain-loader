# Rocky Preset Customization VM Experiment

Date: 2026-10-26

## Result

A launcher ISO built from a target-v2 system, a block-v1 shared block and a prepared base selected
the `rocky-9.8-minimal` revision 1 preset with London settings and one extra package. Under QEMU
pSeries/POWER9, Rocky Linux 9.8 installed unattended from the media Kickstart onto one blank
20 GiB virtio disk and rebooted. With the ISO still first, its GRUB printed
`ISO_CHAIN: GRUB installed-disk handoff` and Rocky booted to `rocky-preset-b login:`.
`verify-rocky-install-evidence` passed at the commit that built the media. An SSH session on a
disposable overlay showed timezone `Europe/London`, locale `en_GB.UTF-8`, keymap `gb` and the
`tmux` package installed, with the login user unprivileged. This is emulator evidence only:
native PowerVM was not run.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs and 8,192 MiB, through `install-rocky`. The guest used QEMU's user-mode network with
  its documented default addresses (`10.0.2.15/24`, gateway `10.0.2.2`, DNS `10.0.2.3`) and the
  MAC `52:54:00:12:34:56`.
- **Source.** The boot ISO's `CHECKSUM` passed `gpgv` with the Rocky 2022 release key
  (`21CB256AE16FC54C6E652949702D426D350D275D`), and the ISO matched its digest.
  `prepare-rocky-source` produced the same four pins as the
  [Rocky unattended experiment](2026-10-02-rocky-unattended-install.md). The served tree held that
  experiment's BaseOS and AppStream metadata and 401 packages. Of these, 398 were copied from
  that experiment's private tree, and three were fetched from `download.rockylinux.org` by their
  repository metadata paths: `tmux`, `langpacks-en_GB` and `langpacks-core-en_GB`. Every package
  matched the size and SHA-256 listed in the `primary.xml` that the repository's `repomd.xml`
  binds, and passed `rpm -K` with the release key. `serve-source` served the tree on loopback,
  and `validate-external-source` passed against it.
- **Inputs.** The base held only version, source and the prepared profile. The block held the
  route, DNS, a test login user, one fresh Ed25519 key and
  `"install": {"timezone": "Europe/London", "locale": "en_GB.UTF-8", "keyboard": "gb",
  "packages": ["tmux"]}`. System B supplied only preset, `lpar` `rocky-preset-b`, MAC and address.
  A second system with `"install": {"packages": []}` passed `validate-config` with the same base
  and block; it was not built or installed. The composed canonical manifest digest was
  `3fd19ef946418fe936b8f5c819fa4843ace44987e04e8a1c17e89441d6294150`.
- **Launcher build.** Commit `ec6c21e`, with a clean tree, rebuilt the launcher initramfs in the
  `iso-chain-initramfs:44` image and then ran `container-build` with the three inputs. As in the
  earlier Rocky records, both container commands ran with `--security-opt label=disable` and the
  asset copies carried no extended attributes. The ISO was 109,862,912 bytes, SHA-256
  `e590d21703bb787c04ec55a45279f8449bdebd12206b4ce2232f0bbbe3096d21`, volume ID
  `ISO_CHAIN_3FD19EF946418FE9`. Its `/profiles/rocky/ks.cfg` was 2,708 bytes, SHA-256
  `65188c6ee243b2eff64faeb545b49d20fb0a5b6dd309120fae3aef9be5e17873`, equal to the rendering
  from the embedded manifest. It holds `lang en_GB.UTF-8`, `keyboard gb`,
  `timezone Europe/London --utc`, and `tmux` after `@^minimal-environment`.

Raw inputs, keys, console logs, access logs, captures, disks and the session transcript remain in
private storage.

## Run

The single acceptance run used a fresh server, access log, disk and output directory; no scratch
or caching-server run preceded it.

- **Install phase.** The launcher printed `memory: passed memtotal_mib=8065`, `disk: passed` and
  `media: passed`. Anaconda's command line carried
  `inst.ks=cdrom:LABEL=ISO_CHAIN_3FD19EF946418FE9:/profiles/rocky/ks.cfg`. Anaconda downloaded
  340 packages and printed `Installing boot loader`, `Creating users`,
  `Running post-installation scripts` and `Installation complete`, in that order. The kernel
  printed `reboot: Restarting system` 2,357 seconds after the installer kernel started, and the
  first QEMU run exited 0.
- **Boot phase.** The second run attached the same ISO, disk and NIC. The console showed one
  `ISO_CHAIN: GRUB installed-disk handoff`, Rocky's 5.14.0-687.53.1.el9_8 kernel and the
  `rocky-preset-b login:` prompt, at which the harness stopped QEMU.

## Evidence

- **Access log.** 364 requests: the four pins first, in order, then only BaseOS and AppStream
  paths, including the three fetched packages. The only failures were one 404 each for
  `images/updates.img` and `images/product.img`.
- **Captures.** Derivatives of the install and boot captures keeping only IPv6, DHCP and BOOTP
  packets held only their headers.
- **Disk.** The fresh disk's digest changed during the install phase; `result.json` records
  `install_exit_status` 0 and `boot_stop: login-prompt`.
- **Verifier.** A canonical version-1 record bound the manifest, both consoles, the access log,
  `result.json`, both filtered captures and both disk digests. `verify-rocky-install-evidence`,
  run from the commit that built the ISO, returned:

```text
manifest: passed
kickstart: passed
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

After the run, a qcow2 overlay backed by the published disk booted with the same ISO first and a
QEMU host forward to port 22. Logging in with the injected key showed:

- host name `rocky-preset-b`, and the login user with no supplementary group; `sudo -n true`
  refused for want of a password;
- `/etc/localtime` linking to `../usr/share/zoneinfo/Europe/London`, and `timedatectl` reporting
  `Timezone=Europe/London`;
- `/etc/locale.conf` holding `LANG="en_GB.UTF-8"`, `/etc/vconsole.conf` holding `KEYMAP="gb"`,
  and `localectl` reporting that locale, VC keymap `gb` and X11 layout `gb`;
- `rpm -q` reporting `tmux-3.2a-5.el9`, `langpacks-en_GB`, `langpacks-core-en_GB` and
  `glibc-langpack-en` installed, and `/usr/bin/tmux` present;
- `iso-chain.nmconnection` as the only NetworkManager connection, `iso0` at `10.0.2.15/24`, and
  `ipv6.disable=1` and `console=hvc0` on the installed kernel command line.

An SSH login as root with the same key was refused. After QEMU stopped, `guestfish --ro` read the
published disk's `/boot/grub2/grubenv`, which held `iso_chain_installed=1`. The published disk's
digest was the same before and after the overlay boot.

## Boundary

- No native LPAR, HMC, VIOS or physical storage was used. Native PowerVM proof belongs to the
  operator's native validation workflow and #6.
- Only one customized system was installed. The second system's empty package list and the other
  allowed timezone, locale and keyboard values were proven by rendering tests and offline
  validation, not by installation.
- The source was a loopback HTTP server holding a partial mirror. A public HTTPS mirror was not
  tested, and the installed packages keep the existing unpinned repository-content limitation.
