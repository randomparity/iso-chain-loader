# Rocky Unattended Install VM Experiment

Date: 2026-10-02

## Result

A QEMU pSeries/POWER9 guest booted a launcher ISO built from a manifest carrying two SSH public
keys and a login user. The launcher verified the media Kickstart that `build` derived from that
manifest, then handed it to Anaconda 34.25.7.14-1.el9.rocky.0.6. Rocky Linux 9.8 installed with no
prompt onto the one blank 20 GiB virtio disk, and the installer rebooted. With the launcher ISO
still first in the boot order, the ISO's GRUB found the installed disk's `grubenv`, printed
`ISO_CHAIN: GRUB installed-disk handoff`, and loaded the disk's own `grub.cfg`. Rocky then booted
to `rocky-qemu login:` on the console. An operator logged in over SSH with the injected key on a
disposable overlay of that disk, and saw the manifest's static network, host name, and keys.
`verify-rocky-install-evidence` passed. This is emulator evidence only: native PowerVM was not
run, and SLOF cannot show whether firmware honours the Kickstart's `--leavebootorder`.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 8,192 MiB, through `install-rocky`. The guest used QEMU's user-mode network with
  its documented default addresses (`10.0.2.15/24`, gateway `10.0.2.2`, DNS `10.0.2.3`) and the MAC
  `52:54:00:12:34:56`.
- **Source.** The pins, `install.img`, and repository metadata were those of the
  [Rocky installer experiment](2026-10-02-rocky-installer.md), prepared with
  `prepare-rocky-source` from the `gpgv`-checked boot ISO. The served tree added the 339 packages
  of the minimal environment: 327 from BaseOS `Packages/` and 12 from AppStream `Packages/`, each
  fetched from `download.rockylinux.org` by its repository metadata path. `serve-source` served the
  tree on loopback.
- **Manifest.** One `rocky` profile, `lpar` `rocky-qemu`, a test login user, and two keys: a fresh
  Ed25519 test key, and the same key with a comment holding a single quote, a double quote, a
  backslash, `#`, `%pre`, and Cyrillic text. The canonical manifest digest was
  `ea505e1f6a057774c9f04ee0188ddc65b341c19ab75d5b623853b7370ffd8eac`.
- **Launcher build.** Commit `5502273`, whose ISO-affecting code matches `8a97112`. The launcher
  kernel was Fedora 7.2.8-200.fc44 with an initramfs from the `iso-chain-initramfs:44` image. The
  ISO was 109,862,912 bytes, SHA-256
  `336dbd771e97010d868b042e516d864bee3bdddce7e99ab0b19a6d785bb2b420`, volume ID
  `ISO_CHAIN_EA505E1F6A057774`. Its `/profiles/rocky/ks.cfg` was 2,645 bytes, SHA-256
  `2d8ebdf7dc51b6c0f9d231ac46e048fc487bcbc0517627f86e1e4825fa32d674`, equal to the rendering from
  the manifest. The host's pykickstart 3.69 RHEL9 handler parsed both `sshkey` values exactly.
- **Build-host deviations.** As in the Rocky installer record, both container commands ran with
  `--security-opt label=disable`, and the initramfs build copied `scripts/` and `assets/` without
  extended attributes.

Raw manifests, keys, console logs, access logs, captures, and disks remain in private storage.

## Run

A scratch run first exercised the same Kickstart against a caching server that fetched missing
files from upstream. It showed that no package was missing, and it is not part of the evidence.
The acceptance run used a fresh `serve-source` server, access log, disk, and output directory.

- **Install phase.** The launcher printed `memory: passed memtotal_mib=8065 memavailable_mib=7666
  run_available_bytes=1677459456`, then `disk: passed` and `media: passed`. Anaconda's kernel
  command line carried `inst.ks=cdrom:LABEL=ISO_CHAIN_EA505E1F6A057774:/profiles/rocky/ks.cfg` and
  the BaseOS `inst.repo=`. The `%pre` guard passed, Anaconda partitioned `vda` as PReP, `/boot`, and
  an LVM root, installed 339 packages, and the kernel printed `reboot: Restarting system` about 25
  minutes after the handoff. QEMU's `-no-reboot` turned that into the first run's exit 0.
- **Boot phase.** The second run attached the same ISO, disk, and NIC. The console showed one
  `ISO_CHAIN: GRUB installed-disk handoff`, no optical handoff, no launcher output, then Rocky's
  kernel 5.14.0-687.53.1.el9_8 and the `rocky-qemu login:` prompt, at which the harness stopped
  QEMU.
- **Kickstart warning.** pykickstart, in both Anaconda and the host, warned `An ssh user with the
  name ... has already been defined.` for the second `sshkey` line. The warning did not stop the
  install, and both keys were installed.

## Evidence

- **Access log.** 361 requests: the four pins in order at their pinned sizes, then only BaseOS and
  AppStream paths. The only failures were one 404 each for `images/updates.img` and
  `images/product.img`, which Anaconda probes and Rocky does not publish.
- **Captures.** Derivatives of the install and boot captures keeping only IPv6, DHCP, and BOOTP
  packets held only their headers.
- **Disk.** The fresh disk's digest changed during the install phase; `result.json` records the
  installer's digest and `boot_stop: login-prompt`.
- **Verifier.** `verify-rocky-install-evidence` returned:

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

## SSH session

After the run, a qcow2 overlay backed by the published disk booted with the same ISO first and a
QEMU host forward to port 22; the published disk's digest was unchanged afterwards. The console
again showed the installed-disk handoff. Logging in with the injected private key showed:

- the login user, with no supplementary group, and `sudo` refusing for want of a password;
- host name `rocky-qemu`;
- `~/.ssh/authorized_keys` equal, line for line, to the manifest's two keys, mode 0600;
- `iso0` at `10.0.2.15/24`, the default route via `10.0.2.2`, and DNS `10.0.2.3`;
- `iso-chain.nmconnection` as the only NetworkManager connection file, active on `iso0`;
- `ipv6.disable=1` and `console=hvc0` on the installed kernel command line, and no IPv6 stack;
- `/boot` on `vda2` and the LVM root on `vda3`.

An SSH login as root with no key was refused.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. Whether PowerVM firmware keeps the
  ISO first after Anaconda's bootloader step, and whether the installed-disk entry survives a CAS
  reboot replay, belong to hmc-mcp#1230.
- The source was a loopback HTTP server holding a partial mirror. A public HTTPS mirror was not
  tested.
- The guest saw one virtio disk. The `%pre` refusals for zero, two, or non-blank disks were not run
  under QEMU; the launcher's guard, which runs first with the same rule, was proven for those cases
  in the [installed-disk experiment](2026-10-02-installed-disk-boot.md).
