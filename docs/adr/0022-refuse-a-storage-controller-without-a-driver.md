# ADR 0022: Refuse a Storage Controller Without a Driver

## Status

Accepted

## Context

ADR 0018's guard counts `/sys/block` disks, so it sees only disks whose controller has a bound
driver in the launcher initramfs. Its consequences say a disk needing another driver "is not
counted and must be detached before an install", but nothing enforces that: with a blank disk on a
driven controller and a data disk on an undriven one, the guard passes, and the installer's own
initrd, which carries more drivers, can see and write the second disk. `build` forces the virtio,
vSCSI, NPIV, and NVMe drivers; dracut's `--no-hostonly` adds others, but `lsinitrd` of a
launcher initramfs from `dracut-108-8.fc44` lists no `megaraid_sas`, `mpt3sas`, `lpfc`, or
`qla2xxx`, and under QEMU a `megasas` adapter's disk was absent from `/sys/block`.
A PowerVM partition can own a physical SAS or Fibre Channel adapter. Issue #46 asks for a
visible refusal or a recorded gap.

## Decision

- **Storage controller.** A PCI device whose sysfs `class` is mass storage (`0x01....`) or Fibre
  Channel (`0x0c04..`), or a VIO device whose `modalias` starts `vio:Tvscsi` (vSCSI) or `vio:Tfcp`
  (NPIV).
- **Unbound.** A storage controller with no `driver` link after `udevadm settle`. A PCI device
  without a driver whose `class` cannot be read as `0x` and six hex digits also counts, so an
  unreadable class refuses rather than passes.
- **Refusal.** In `check_disk`, after the settle and before counting disks, the launcher counts
  unbound storage controllers under `/sys/bus` (`ISO_CHAIN_SYS_BUS` in tests). Unless the count
  is zero it prints `disk-controller: failed unbound=<n>`, then `disk: failed`, and exits nonzero
  before any disk read, media mount, download, or `kexec`. It names no device: the operator finds
  the adapter in the partition's own inventory. `disk: passed` and `verify-launcher-log` are
  unchanged.

## Consequences

- A partition owning a storage adapter the initramfs cannot drive stops at the guard. The operator
  removes that adapter from the partition, or uses vSCSI or NPIV, before an install; adding its
  driver to the initramfs is separate work.
- An adapter with a bound driver and no disks still passes; its disks, if any, are counted as
  before. Two paths to one LUN still count twice (ADR 0018).
- A storage device below a bus with a bound driver is not seen when its own driver is missing: a
  USB mass-storage device behind a driven USB host controller, or a virtio-scsi or virtio-blk
  function whose virtio driver is missing behind the bound `virtio-pci` function. `build` forces the
  virtio drivers; USB storage on the install partition is not covered.
- Network-attached storage (iSCSI, NVMe over fabrics) needs initiator configuration the launcher
  never performs, so no such disk is attached at the guard.
- Only QEMU devices prove the rule here; a real PowerVM physical adapter's class and binding are
  unproven and belong to the native PowerVM proof (#28, hmc-mcp#1230).

## Considered & rejected

- **Record the gap only, as an ADR 0018 follow-on.** judgment: fit; the guard exists to fail closed,
  and a gap an operator must remember fails open.
- **Refuse any PCI device without a driver.** verified: under QEMU pSeries with the launcher
  initramfs from `dracut-108-8.fc44` and kernel `7.2.8-200.fc44.ppc64le`, the VGA function (class
  `0x030000`) and the VIO `nvram` device have no `driver` link, so every default QEMU boot would
  refuse.
- **PCI mass-storage class only.** verified: `grep -n -A20 '^C 0c' /usr/share/hwdata/pci.ids`
  (`hwdata-0.411-1.fc44`) lists `04  Fibre Channel` under `C 0c  Serial bus controller`, not under
  `C 01  Mass storage controller`, so an FC HBA would pass.
- **Name the unbound devices on the console.** judgment: fit; a PCI address or VIO unit address
  identifies a machine slot, and the console log is evidence that may be shared.
- **Force more drivers into the initramfs.** judgment: cost; every added driver grows the image,
  and no list covers every adapter, so the guard still needs the refusal.
