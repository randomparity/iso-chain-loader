# POWER9 Optical Bootstrap Feasibility Design

Issue: [#3](https://github.com/randomparity/iso-chain-loader/issues/3)
Decision: [ADR 0003](../../adr/0003-use-grub-linux-and-kexec-for-bootstrap.md)

## Goal and evidence boundary

Build a minimal ppc64le optical image, boot it through a POWER9-mode pSeries Open Firmware path,
and verify a Linux-to-Linux `kexec` transition without network hardware. The result selects GRUB →
Linux initramfs → `kexec` as the bootstrap stack. Emulator evidence must remain distinct from native
POWER9 PowerVM evidence: this change records native optical boot, VIOS behavior, and firmware
security policy as unproven because no authorized LPAR is available.

Success requires an ISO produced from explicit ppc64le inputs, a smoke command whose constructed
QEMU argument vector contains `-nic none` and `-snapshot`, and an ordered console record containing
the optical firmware load, GRUB marker, first-stage kernel marker, a kernel-generated first boot ID,
a mechanically gated loopback-only marker, kexec switchover, and a second-stage service marker with
a different kernel boot ID. Raw console evidence stays private; the verifier emits only fixed
pass/fail labels.

## Interface and components

`scripts/iso_chain.py` exposes three subcommands:

- `build --grub-modules DIR --kernel FILE --initramfs FILE --kernel-args TEXT --output FILE` validates
  the inputs, stages a fixed `/boot/grub/grub.cfg`, and invokes `grub2-mkrescue -d DIR -o TEMP STAGE`.
  The fixed command line begins `console=hvc0 rd.neednet=0 ip=off iso_chain_stage=optical`.
- `smoke --iso FILE --disk FILE` validates both images and replaces itself with one fixed
  `qemu-system-ppc64` command: pSeries/TCG, POWER9, 4 GiB, two CPUs, no graphics, `-nic none`, a
  snapshot disk, and a boot-first SCSI CD-ROM. It has no general QEMU-argument escape hatch.
- `verify-log LOG` reads a private console log, rejects known network-device/DHCP evidence, requires
  the six markers above in order, and prints only `optical-boot: passed`, `network: passed`, and
  `kexec: passed`.

All paths must resolve to existing regular files/directories of the required kind. The GRUB module
directory must carry `modinfo.sh` declaring `powerpc` and `ieee1275`. Kernel arguments are
space-separated tokens limited to letters, digits, and `_./:=,@+-`; carriage returns, newlines,
NUL, `ip=`, and `rd.neednet=` are rejected. The output parent must exist and the output must not.
The builder creates private temporary state beside the output, invokes the external tool without a
shell, and publishes the completed ISO with an atomic no-replace hard link. A failed build leaves no
output. Generated ISOs and raw logs remain ignored and uncommitted.

The evidence verifier requires, in order: `Successfully loaded`, `ISO_CHAIN: GRUB optical handoff`,
`iso_chain_stage=optical`, `ISO_CHAIN_EVIDENCE: first-kernel boot_id=<UUID>`,
`ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo`, `kexec_core: Starting new kernel`, and
`ISO_CHAIN_EVIDENCE: second-kernel boot_id=<different UUID> cmdline=iso_chain_stage=kexec`. It rejects
a SLOF logical-LAN node, a non-loopback guest link marker, or a DHCP lease marker anywhere in the
log. It also rejects equal or malformed boot IDs. A missing, reordered, or forbidden marker fails
with one actionable diagnostic and no copied log content. This validates the shape and provenance
of an operator-captured transcript; it does not cryptographically authenticate the transcript.

## Error and safety behavior

Usage and validation errors exit 2. External build or QEMU startup failure preserves the external
command's diagnostic and exits nonzero. The builder never downloads inputs, mutates its inputs, or
overwrites an output. The smoke runner never attaches a NIC and uses QEMU snapshot mode, so neither
the source disk nor any DHCP service is touched. Operators stop before any HMC or VIOS mapping
mutation unless an exclusive VIOS window is explicitly coordinated and recorded.

## Threat model

### Boundary inventory

- Added: local operator paths and kernel arguments enter the builder; controls are kind checks,
  platform metadata checks, restricted single-line tokens, no shell, a private staging directory,
  and no-replace publication.
- Added: local ISO and disk paths enter QEMU; controls are regular-file checks, a fixed argument
  vector, `-snapshot`, `-nic none`, and no arbitrary extra arguments.
- Added: a console log enters the verifier; controls are bounded marker matching, fixed diagnostics,
  and no raw-content echo.
- Existing: GRUB, xorriso, QEMU, kernel, and initramfs artifacts execute with operator privilege.
  The operator supplies and trusts them; this change neither downloads nor verifies their origin.

### Actors and exclusions

The actor is a local operator running trusted artifacts. Untrusted artifact suppliers and a user
able to replace executables on `PATH` are outside this local experiment's threat model. The design
does not provide artifact signatures, Secure Boot enablement, HMC/VIOS authorization, isolation from
a malicious disk image, or a production sandbox. Those are not reachable claims without native
hardware and a separately authorized mapping window.

## Verification

Python unit tests run each CLI boundary with temporary fixtures and fake external executables. They
prove platform-metadata validation, kernel-argument rejection, no-overwrite output, exact fixed QEMU
network/snapshot arguments, ordered evidence acceptance, forbidden-network rejection, and concise
diagnostics. The aggregate `just check` command includes the unit suite.

The end-to-end arm uses the operator-provided Fedora disk as the root userspace. Its preflight must
establish an ELF 64-bit little-endian PowerPC kernel, its matching initramfs, the exact root argument,
`console=hvc0`, a working local console login with `sudo`, `/usr/sbin/kexec`, readable second-stage
kernel/initramfs paths under `/boot`, and `CONFIG_KEXEC=y` or `CONFIG_KEXEC_FILE=y` in the matching
kernel config. The disk remains attached for both stages; no custom initramfs is added.

Before accepting evidence, the operator records tool/firmware/kernel/CPU/RAM/storage facts
privately. In the first stage, one `sh -eu` action verifies `iso_chain_stage=optical` in
`/proc/cmdline`, reads `/proc/sys/kernel/random/boot_id`, compares the newline-sorted basenames under
`/sys/class/net` with exactly `lo`, and only then prints the two fixed first-stage evidence lines.
Every operation is joined by the shell's fail-fast behavior, so a failed predicate cannot emit the
network marker.

Before `kexec -e`, the operator installs `/usr/local/sbin/iso-chain-second-stage` and a systemd
oneshot under `/etc/systemd/system` on the QEMU snapshot. The script uses `sh -eu`, requires
`iso_chain_stage=kexec` in `/proc/cmdline`, reads the new kernel boot ID, and prints exactly the fixed
second-stage evidence line. The unit is enabled for `multi-user.target` with
`StandardOutput=journal+console` and `StandardError=journal+console`. These snapshot-only writes do
not reach the source disk. The operator then invokes `kexec -l` with the same relocatable ELF
kernel, initramfs, root argument, and changed stage marker, followed by `kexec -e`. `verify-log` must
pass. The published report redacts boot IDs and machine identifiers and states that native POWER9
PowerVM and firmware-security validation did not run.

## Native LPAR gate

A future native run must record the exclusive VIOS mapping window before any mapping change, retain
the pre-run mapping snapshot, preserve the existing firmware security mode, record HMC/VIOS/firmware
versions and CPU/RAM/console/NIC/storage classes privately, and define cleanup ownership. Without
that window, the run stops before mapping mutation and reports pending cleanup. This change creates
no locking system and makes no hmc-mcp change.
