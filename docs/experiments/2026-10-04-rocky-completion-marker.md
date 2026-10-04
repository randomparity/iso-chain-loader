# Rocky Completion Marker VM Experiment

Date: 2026-10-04

## Result

A keyed Rocky Linux 9.8 launcher ISO built with ADR 0021's completion marker was run twice under
QEMU pSeries/POWER9. In the completed run, the unattended install's last `%post` set
`iso_chain_installed=1` in the installed `/boot/grub2/grubenv`. On the next boot, with the ISO still
first, the ISO's GRUB printed `ISO_CHAIN: GRUB installed-disk handoff` and Rocky booted to
`rocky-qemu login:`. `verify-rocky-install-evidence` passed. In the interrupted run, QEMU was killed
after Anaconda printed `Creating users`, after it had installed the bootloader. The disk's
`grubenv` existed without the marker, and the disk held neither the login user nor the network
keyfile. The next boot with the same ISO took the default `rocky` entry with no installed-disk
handoff. The launcher then printed `disk-blank: failed` and `disk: failed`. This is emulator
evidence only; native PowerVM was not run.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 8,192 MiB. The guest used QEMU's user-mode network, with the documented default
  addresses and the MAC `52:54:00:12:34:56`, as in the
  [Rocky unattended experiment](2026-10-02-rocky-unattended-install.md).
- **Source and manifest.** The same private BaseOS and AppStream tree and the same manifest as that
  experiment: one `rocky` profile, `lpar` `rocky-qemu`, a test login user, and two keys. The
  canonical manifest digest was
  `ea505e1f6a057774c9f04ee0188ddc65b341c19ab75d5b623853b7370ffd8eac`. Each run used a fresh
  `serve-source` server on loopback, a fresh access log, and a fresh 20 GiB disk.
- **Launcher build.** This change's code commit before its rebase onto the #46 storage
  controller guard, with a clean tree. The rebased branch renders a byte-identical `grub.cfg`
  and Kickstart for this manifest; its launcher adds that guard, which this run predates.
  The launcher kernel was Fedora 7.2.8-200.fc44, with an initramfs from the
  `iso-chain-initramfs:44` image. Both container commands ran with
  `--security-opt label=disable`, and the asset copies carried no extended attributes, as in the
  earlier Rocky records. The ISO was 109,862,912 bytes, SHA-256
  `fc3725e296e524b0d3ef8ab07075d21721318c9b4a269fe8e17cfd6765910100`, volume ID
  `ISO_CHAIN_EA505E1F6A057774`. Its `/profiles/rocky/ks.cfg` was 2,847 bytes, SHA-256
  `dbaba54386843777de7e18ff3026e4e935562e35c314a5df998a2a56210852cf`, which matches the
  rendering from the manifest. It ends with the marker `%post` and `reboot`. The ISO's `grub.cfg`
  holds one `load_env`.

Raw manifests, keys, console logs, access logs, captures, and disks remain in private storage.

## Completed run

`install-rocky` ran the install with `-no-reboot`. The launcher printed `memory: passed`,
`disk: passed`, and `media: passed`, and Anaconda's command line carried
`inst.ks=cdrom:LABEL=ISO_CHAIN_EA505E1F6A057774:/profiles/rocky/ks.cfg`. The install console
printed `Installing boot loader`, `Creating users`, `Running post-installation scripts`, and
`Installation complete`, in that order, and the first QEMU run exited 0. The second run attached
the same ISO, disk, and NIC. Its console showed one `ISO_CHAIN: GRUB installed-disk handoff`, no
launcher output, the 5.14.0-687.53.1.el9_8 kernel, and `rocky-qemu login:`, at which the harness
stopped QEMU.

The access log held 361 requests. The first four were the kernel, initrd, `.treeinfo`, and
`repomd.xml` pins, in that order. The only failures were 404s for `images/updates.img` and
`images/product.img`, as in the earlier record. `guestfish --ro` (libguestfs 1.60.1) then read
the disk's `/boot` partition. Its `grub2/grubenv` held `saved_entry`, `menu_auto_hide=1`,
`boot_success=1`, and `iso_chain_installed=1`. The interrupted disk below also held
`boot_success=1`, so the install wrote it; this run does not show a later boot-success write
keeping the marker.

`verify-rocky-install-evidence` returned:

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

## Interrupted run

A private Python driver imported `scripts.iso_chain`. It took the install command from
`install_qemu_commands(iso, disk, manifest, pcap, 8192)[0]` and added `-no-reboot`, with the
serial console written to a file. It polled that file every 5 seconds and killed QEMU on the
first `Creating users`. The last console line before the kill was `Creating users`, and
`Running post-installation scripts` never appeared. `guestfish --ro` then read the disk:

- `/boot` held `grub2/grubenv`, with `saved_entry`, `menu_auto_hide=1`, and `boot_success=1`,
  and no `iso_chain_installed`;
- the root logical volume's `/etc/passwd` had no entry for the login user;
- the root volume had no `iso-chain.nmconnection`.

The driver then booted the same ISO, disk, and NIC with the same command. The console showed
`ISO_CHAIN: GRUB optical handoff` and no installed-disk handoff, then `disk-blank: failed` and
`disk: failed`. The driver stopped QEMU there. The interrupted run's access log held 361 requests,
all from the install phase.

That `grubenv` lies on one of ADR 0018's four searched paths, and the plain menu that keyed Rocky
media used before this change treats any such file as an installed disk. No run booted this disk
with that menu. The earlier
[Ubuntu interruption run](2026-10-03-ubuntu-unattended-install.md) showed the same refusal under
the completion-checking menu.

## Boundary

- No native LPAR, HMC, VIOS, or physical storage was used. The native PowerVM proof belongs to
  #28 and #6.
- The interruption point was one place between `Installing boot loader` and the marker `%post`,
  chosen from the console. Kills at other points in that window were not run.
- The source was a loopback HTTP server holding a partial mirror. A public HTTPS mirror was not
  tested.
- A disk installed from keyed Rocky media built before this change was not booted with this ISO;
  ADR 0021 records that such a disk needs the marker set by hand.
