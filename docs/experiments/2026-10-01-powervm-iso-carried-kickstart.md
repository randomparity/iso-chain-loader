# PowerVM ISO-Carried Kickstart Installation Experiment

Date: 2026-10-01 (runs ended 2026-10-02 UTC)

## Inputs and environment

The target was a POWER9 PowerVM partition (`lpar-R1` on `sys-R1`, firmware FW950) managed by an
HMC (`hmc-R1`), with 32 GiB memory, 4 virtual processors, one virtual Ethernet adapter, and a vSCSI
server adapter on `vios-R1` carrying a 100 GiB logical volume (`sda`) and a virtual optical device.
The volume held stale partitions from earlier use. The partition had a static IPv4 address, route,
and resolver supplied through the manifest; no DHCP service was configured for it.

ISOs were uploaded into the VIOS media repository with `hmcpctl storage upload-iso`, loaded and
unloaded on the virtual optical device with `loadopt`/`unloadopt -release`, and the partition was
powered on and off with `hmcpctl`. Console evidence came from bounded, output-only `hmcpctl lpars
capture-console` windows. Raw manifests, network values, console logs, HMC records, and the ISOs
remain in mode-0700 private storage.

The profile pinned Fedora 44 compose 1.7's `Everything` ppc64le netinst `vmlinuz`
(66,211,760 bytes, `daf5a8fd71682cc8724b4c26369ab4041e18631235134c70b3b804789b84a454`) and
`initrd.img` (224,712,048 bytes,
`f9adcc0c6f19f19636446ea60dd4b051f0011738bcde1247a964bcc7f657617a`), `.treeinfo`, and
`repodata/repomd.xml`. The Kickstart was `assets/kickstart/fedora-44-powervm.ks`
(`a5545effaba65ce889fd6a845b7fb10f7f5f218ffc13f5802ad10918956f9ab2`). The launcher kernel was
Fedora 7.2.8-200.fc44 and its initramfs came from `container-prepare-initramfs`.

## Procedure

Attempts 4 and 5 were built from implementation commit `2e74427` with `container-build`, using the same
launcher initramfs and the same prepared profile tree, and checked by `validate-external-source`
against the manifest's `source` before upload. Each attempt swapped the optical media, powered the
partition on, and captured the console until the partition powered itself off.

## Result

**Attempt 4** (`source` `https://dl.fedoraproject.org`): every launcher gate passed, including
`media`, and `artifacts`, `kexec-load: passed`, and `kexec-exec: started` followed. Fedora's kernel
booted, Anaconda 44.30-2 read the Kickstart from `cdrom:/profiles/fedora-44/ks.cfg`, and Network
configuration reported `Connected: iso0`. Installation Source then reported
`Error setting up repositories`, and Anaconda waited at its interactive prompt. Probes from the lab
showed one of the mirror name's three address records returning HTTP 404 for every path under
`/pub/fedora-secondary/`, while the other two returned 200. The partition was powered off.

**Attempt 5** (`source` `https://download-ib01.fedoraproject.org`, the only change; ISO 109,832,192
bytes, `e2c93f5a2ea8258303311c208b67b66d5de44829881e1c27fb2f1cb0f32c9ddf`): the launcher passed every
gate and kexeced the 290,923,808-byte payload. Anaconda reported Installation Source, Software
Selection, Installation Destination, and Network configuration complete, installed 742 packages,
installed the boot loader, ran `%post`, and powered off (`reboot: Power down`) 23 minutes after
activation. The installer set the firmware boot list to the installed disk.

**Installed boot**: with the optical media unloaded, the partition booted Fedora 44 kernel
6.19.10-300.fc44 from `sda` with `root=/dev/mapper/fedora-root`, printed
`installed-boot: passed boot_id=<REDACTED-BOOT-ID>`, and powered off.

**Attempt 6** (commit `7401c4b`, which adds the volume-label Kickstart binding; ISO
109,832,192 bytes, `34beb1562f2baf809728409f5ce440fdac95950fb00fb559cda603c3b9fa6425`): Anaconda
read the Kickstart through `inst.ks=cdrom:LABEL=ISO_CHAIN_75D59B57DED04D33:/profiles/fedora-44/ks.cfg`,
installed 742 packages, and powered off. With the media unloaded, the installed system booted, printed
`installed-boot: passed boot_id=<REDACTED-BOOT-ID>`, and powered off. The commits between `7401c4b`
and this record change only tests and documentation. Commit `fdeea6b`, made after this record,
adds a `blkid` check that no other block device carries the volume ID, and adds `blkid` to the
launcher initramfs. That check has not run on PowerVM.

The installer kernel command line carried `ip=<address>::<gateway>:<netmask>:<host>:iso0:none` and
`ipv6.disable=1`; no console window from activation to power-off contained a DHCP line. This is a
console observation only: no packet capture was taken on the PowerVM network.

Retained private evidence, by SHA-256: attempt 4 console
`7d507d1d168af765166bc6f19c73247478607d194b79d4dd323fb14b63f3ca86`, attempt 5 console
`02cabaaa628b73700393edd2380779665dd5f3946045d58fe09c8e13c8aba255`, installed-boot console
`2ed228982ec6d83db9d10ad474684000f9577ee347aadb7f31ace10f6fc23642`, attempt 6 console
`e14637ae94efc9000405b62b6058f4f44a466b5c5fe8f145a8e9b76252101a0f`, attempt 6 installed-boot console
`3b72d7e6f8ece5f092e033254f7b55984fc8845b4c2547d72ccb5d06a64c1239`.

## Earlier failures

- **Attempt 1:** after a firmware CAS reboot, Fedora's GRUB aborted with `double free` while
  replaying a 1.3 KB menu entry. Commit `c714143` moved the arguments into a variable. Later
  attempts did not take a CAS reboot, so that fix is not yet exercised live.
- **Attempts 2 and 3:** these carried ADR 0005's 1,068,556,772-byte bundle. `kexec_file_load` failed
  with `EADDRNOTAVAIL`, and `kexec -c` failed with `locate_hole failed`. ADR 0011 records why.
- **Media swaps:** after an immediate power-off, the VIOS refused to swap media while the client
  still held its reservation. `unloadopt -release` and `loadopt -release` cleared it.

## Boundary and cleanup

Mutations stayed within the authorized partition, its VIOS mappings, and the VIOS media repository.
The installed disk is a test artifact. The partition was left powered off with the optical device
empty. The uploaded test ISOs remain in the media repository pending operator cleanup.
