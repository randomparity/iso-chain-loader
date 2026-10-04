# Unbound Storage Controller Guard Design

Issue: #46. Decision: [ADR 0022](../../adr/0022-refuse-a-storage-controller-without-a-driver.md),
which extends ADR 0018's blank-disk guard.

## Problem

The launcher's guard (ADR 0018) counts `/sys/block` disks, so a disk on a controller the initramfs
has no driver for is invisible, and the guard can pass on one blank disk while another disk is
attached. Under QEMU, a `megasas` adapter's disk was absent from `/sys/block` with the current
launcher initramfs.

## Scope

In scope:

- `assets/dracut/iso-chain-launch.sh`: a `check_controllers` function, called by `check_disk`
  after `udevadm settle` and before the disk count, and an injectable `ISO_CHAIN_SYS_BUS`
  (default `/sys/bus`).
- `tests/test_iso_chain_launch.sh`: a fake `$workspace/sys/bus` tree and refusal cases.
- `scripts/iso_chain.py`: the `DRACUT_DRIVERS` comment only.
- ADR 0022, README's guard paragraph, AGENTS.md's harness and launcher descriptions, and a QEMU
  experiment record under `docs/experiments/`.

Out of scope (owners): multipath de-duplication (ADR 0018); adding drivers to the initramfs (not
owned); native PowerVM proof (#28, hmc-mcp#1230); non-Fedora installed-disk boot (#49).

No ownership transition: the guard stays in `check_disk`, `verify-launcher-log` is unchanged, and
no caller migrates.

### Rule

`check_controllers` counts, under `$sys_bus`:

- each existing `pci/devices/*` entry with no `driver` entry whose `class` content matches
  `0x01????` or `0x0c04??`, or does not match `0x??????` (unreadable or malformed);
- each `vio/devices/*` entry with no `driver` entry whose `modalias` starts `vio:Tvscsi` or
  `vio:Tfcp`; an unreadable `modalias` is not a storage controller (the VIO bus root has none).

A non-zero count prints `disk-controller: failed unbound=<n>` to stderr and returns 1; `main` then
prints `disk: failed` and exits 1. The function uses only `[`, `cat`, and shell arithmetic, all
available to the initramfs (`DRACUT_TOOLS`). A missing `pci` or `vio` directory counts nothing.

## Failure model

1. Actors and deployments: an operator booting the launcher ISO on a QEMU pSeries guest or a
   PowerVM POWER9 partition; the kernel writes sysfs.
2. Invariants and assets: no installer handoff while a PCI or VIO storage controller is present
   with no bound driver; existing passing configurations (QEMU `smoke`/`install-*` command
   shapes, one virtio or vSCSI disk) keep passing.
3. Accepted failure classes:
   - a storage device below a bus with a bound driver (USB mass storage behind a driven host
     controller; a virtio function behind bound `virtio-pci`) — ADR 0022 consequence; virtio
     drivers are forced, and USB install targets are not a named deployment;
   - network-attached storage — the launcher configures no initiator;
   - a controller whose driver binds after `udevadm settle` times out — the settle failure already
     refuses with `disk-settle: failed`;
   - a disk a bound controller discovers after the guard counted — ADR 0018's residual, unchanged.
4. Covered elsewhere: multipath (ADR 0018); real PowerVM adapter behavior (#28, hmc-mcp#1230).

### Threat model

- Boundary: sysfs content, produced by the kernel, read by the launcher; no new untrusted input.
- Actor: an operator who attached a data disk by mistake; no remote party reaches this code.
- Control: count-only output, no device names echoed; unreadable PCI class fails closed.
- Out of scope: a hostile kernel or initramfs, which already controls the launcher.

## Success

1. With an unbound PCI mass-storage, PCI Fibre Channel, VIO vSCSI, or VIO NPIV controller, or an
   unbound PCI device with an unreadable class, the launcher prints
   `disk-controller: failed unbound=<n>` and `disk: failed`, exits nonzero, and runs no `mount`,
   `curl`, or `kexec`, for every profile distribution (`fedora`, `rocky`, `ubuntu`, `opensuse`).
2. Bound storage controllers, unbound non-storage PCI or VIO devices, and an empty or absent bus
   directory do not refuse; the existing disk cases keep their results.
3. Under QEMU with the changed launcher, one blank virtio disk plus an attached `megasas` adapter
   refuses with `unbound=1`, and the same guest without `megasas` prints `disk: passed`.

## Validation

- Mode: focused-test. Contract: Success 1 and 2. `tests/test_iso_chain_launch.sh` cases; red: the
  current launcher passes the unbound cases; green: `bash tests/test_iso_chain_launch.sh` prints
  `launcher shell tests: passed`.
- Mode: task-test-not-applicable. Contract: Success 3. Surface: real kernel sysfs under QEMU;
  reason: the shell harness fakes sysfs, so only a guest boot observes the kernel's layout; the
  experiment record carries the console evidence.
- Mode: task-test-not-applicable. Contract: `DRACUT_DRIVERS` comment, README, AGENTS.md. Reason:
  prose with no executable consumer; `just check-markdown` covers form.
