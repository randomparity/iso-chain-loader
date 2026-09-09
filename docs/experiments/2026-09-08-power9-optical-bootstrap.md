# POWER9 Optical Bootstrap Experiment

Date: 2026-09-08

## Result

The `vm-ppc64le` Fedora 43 artifacts booted the generated optical image through QEMU pSeries/SLOF
in POWER9 mode. The guest had only `lo`, Linux `kexec` entered a fresh second kernel, and distinct
kernel boot IDs reached the console evidence service. `verify-log` returned:

```text
optical-boot: passed
network: passed
kexec: passed
```

This accepts [ADR 0003](../adr/0003-use-grub-linux-and-kexec-for-bootstrap.md): use GRUB for the
IEEE1275 optical handoff, Linux for the constrained runtime, and `kexec` for the selected kernel.
Petitboot already combines Linux and kexec, but bundling it would add a second selection runtime
without strengthening the PowerVM optical proof. GRUB alone is not the future network/runtime layer.

## Reproduction

Resolve these private paths from the `vm-ppc64le` `fedora-43` selector: `$MODULES`, `$KERNEL`,
`$INITRAMFS`, `$DISK`, and the disk's `$ROOT_ARGS`. Then run:

```sh
umask 077
PRIVATE=$(mktemp -d)
chmod 700 "$PRIVATE"
scripts/iso_chain.py build --grub-modules "$MODULES" --kernel "$KERNEL" \
  --initramfs "$INITRAMFS" --kernel-args "$ROOT_ARGS" --output "$PRIVATE/experiment.iso"
set -o pipefail
scripts/iso_chain.py smoke --iso "$PRIVATE/experiment.iso" --disk "$DISK" 2>&1 | \
  tee "$PRIVATE/console.log"
```

Preflight must confirm a little-endian ppc64 ELF kernel, matching initramfs/config with
`CONFIG_KEXEC=y` or `CONFIG_KEXEC_FILE=y`, console login and sudo, readable `/boot` inputs, and
`kexec`. This image lacked `kexec-tools`; a Fedora 43 ppc64le RPM was digest-checked on the host,
copied into a private qcow2 derivative, and installed only inside QEMU snapshot state. No guest
network device or VM-repository file was added or changed.

At first-stage login, use one fail-fast shell action to check the optical command line, read
`/proc/sys/kernel/random/boot_id`, and require this interface inventory before printing markers:

```sh
set -eu
interfaces=$(find /sys/class/net -mindepth 1 -maxdepth 1 -type l -printf '%f\n' | LC_ALL=C sort)
test "$interfaces" = lo
printf 'ISO_CHAIN_EVIDENCE: first-kernel boot_id=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
printf 'ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo\n'
```

Install and enable a snapshot-only systemd oneshot that checks `iso_chain_stage=kexec` in
`/proc/cmdline`, then prints the second boot ID as
`ISO_CHAIN_EVIDENCE: second-kernel boot_id=<ID> cmdline=iso_chain_stage=kexec`. Verify its label,
executable bit, unit syntax, enablement, and console output before loading the same kernel:

```sh
printf '%s\n' '#!/bin/sh' 'set -eu' 'grep -qw iso_chain_stage=kexec /proc/cmdline' 'boot_id=$(cat /proc/sys/kernel/random/boot_id)' "printf 'ISO_CHAIN_EVIDENCE: second-kernel boot_id=%s cmdline=iso_chain_stage=kexec\\n' \"\$boot_id\"" | sudo tee /usr/local/sbin/iso-chain-second-stage >/dev/null
printf '%s\n' '[Unit]' 'Description=ISO chain second-kernel evidence' '[Service]' 'Type=oneshot' 'ExecStart=/usr/local/sbin/iso-chain-second-stage' 'StandardOutput=journal+console' 'StandardError=journal+console' '[Install]' 'WantedBy=multi-user.target' | sudo tee /etc/systemd/system/iso-chain-evidence.service >/dev/null
sudo chmod 0755 /usr/local/sbin/iso-chain-second-stage
sudo restorecon -F /usr/local/sbin/iso-chain-second-stage /etc/systemd/system/iso-chain-evidence.service
sudo systemd-analyze verify /etc/systemd/system/iso-chain-evidence.service
sudo systemctl enable iso-chain-evidence.service
next=$(sed 's/iso_chain_stage=optical/iso_chain_stage=kexec/' /proc/cmdline)
sudo kexec -l /boot/vmlinuz-<VERSION> --initrd=/boot/initramfs-<VERSION>.img --append="$next"
sudo kexec -e
```

Stop after 20 minutes if the service marker does not appear, record the last milestone, and run
`scripts/iso_chain.py verify-log "$PRIVATE/console.log"`. Raw logs contain machine identifiers; keep
the restrictive umask and private directory for their full retention period.

## Evidence boundary

| Arm | Observation |
| --- | --- |
| QEMU optical | SLOF loaded the CD, GRUB emitted its handoff marker, and Linux received the optical-stage argument. |
| No network | QEMU used `-nic none`; the interface-symlink inventory was exactly `lo`; no DHCP lease marker appeared. |
| Second kernel | `kexec_core` handed off, kernel time restarted, the kexec-stage command line appeared, and the boot IDs differed. |
| Native POWER9 | Not run: no native LPAR or exclusive VIOS mapping window was available. |

The native gap includes PowerVM optical behavior, VIOS mapping, Secure Boot compatibility, and
firmware-policy preservation. A native run must first reserve the VIOS window, capture mappings and
security mode, assign cleanup ownership, and restore the mapping afterward.

One earlier exploratory run was invalid because QEMU's default NIC was not disabled and the guest
obtained DHCP. That transcript was discarded. The implemented runner fixes the cause with an
unconditional `-nic none`; the successful run used it. The second kernel also emitted a pSeries IOMMU
UBSAN warning; it did not prevent the observed handoff and is not treated as native-hardware proof.
