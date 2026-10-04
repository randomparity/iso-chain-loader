# Unbound Storage Controller Guard Implementation Plan

Goal: the launcher refuses an install while a storage controller has no bound driver. Spec:
`docs/workflow/specs/2026-10-04-unbound-storage-guard-design.md`; ADR 0022.

Architecture: `iso-chain-launch.sh` gains `check_controllers`, called first in `check_disk` after
`udevadm settle`; it reads `$sys_bus/pci/devices/*` and `$sys_bus/vio/devices/*`. The shell
harness models that tree under `$workspace/sys/bus`.

Tech stack: POSIX `sh` in the dracut launcher, Bash test harness, QEMU pSeries for the proof.

Expected implementation size: 150–200 changed lines (M) — about 25 launcher, 45 test, 15 README
and AGENTS.md, and 80 experiment-record lines across the two tasks below.

## Global Constraints

- The launcher stays POSIX `sh` using only `[`, `cat`, `printf`, and shell arithmetic here; tools
  must be in `DRACUT_TOOLS` (`scripts/iso_chain.py`), which has no `readlink` or `basename`.
- The harness runs on Linux and macOS with `LC_ALL=C`; fixtures use `mkdir` and `printf` only.
- No private data in committed evidence: no PCI or VIO unit addresses beyond QEMU defaults, no
  hostnames or IP addresses other than QEMU user-network defaults; raw logs stay in private storage.
- `.secrets.baseline` covers only `Justfile`, which this change does not touch.

## File map

- `assets/dracut/iso-chain-launch.sh` — owns the guard; gains `sys_bus` and `check_controllers`.
- `tests/test_iso_chain_launch.sh` — owns launcher black-box tests; gains the bus fixture and cases.
- `scripts/iso_chain.py` — the `DRACUT_DRIVERS` comment only, pointing at ADR 0022.
- `README.md`, `AGENTS.md` — guard description and harness variable list.
- `docs/experiments/2026-10-04-unbound-storage-guard.md` — QEMU evidence record.

## Task 1: Refuse unbound storage controllers

Interfaces: consumes `stage_failure`-style stderr reporting and `check_disk`'s return contract
(`main` prints `disk: failed` on nonzero). Provides `ISO_CHAIN_SYS_BUS` and the reason line
`disk-controller: failed unbound=<n>` used by Task 2.

Verification:

- Mode: focused-test. Contract: spec Success 1 and 2. Cases in `tests/test_iso_chain_launch.sh`.
  Red: before the launcher change, `bash tests/test_iso_chain_launch.sh` prints
  `test failure: controller-pci-storage missed fixed marker`. Green: the same command prints
  `launcher shell tests: passed`.
- Mode: task-test-not-applicable. Contract: `DRACUT_DRIVERS` comment, README, AGENTS.md. Reason:
  prose with no executable consumer; `just check-markdown` and `just check-python-lint` cover form.

Steps:

1. In `run_launcher`, after the disk `case` blocks, build the baseline bus tree (bound storage,
   unbound VGA and nvram, a VIO root without `modalias`), apply faults, and export
   `ISO_CHAIN_SYS_BUS="$workspace/sys/bus"` beside `ISO_CHAIN_SYS_BLOCK`:

   ```bash
   local bus="$workspace/sys/bus"
   mkdir -p "$bus/pci/devices/0000:00:00.0" "$bus/pci/devices/0000:00:01.0/driver" \
       "$bus/vio/devices/71000001" "$bus/vio/devices/71000002/driver" "$bus/vio/devices/vio"
   printf '0x030000\n' >"$bus/pci/devices/0000:00:00.0/class"
   printf '0x010000\n' >"$bus/pci/devices/0000:00:01.0/class"
   printf 'vio:TnvramSqemu,spapr-nvram\n' >"$bus/vio/devices/71000001/modalias"
   printf 'vio:TvscsiSIBM,v-scsi\n' >"$bus/vio/devices/71000002/modalias"
   case "$fault" in
   controller-pci-storage) make_pci 0000:00:02.0 0x010400 ;;
   controller-pci-fc) make_pci 0000:00:02.0 0x0c0400 ;;
   controller-pci-unreadable) mkdir -p "$bus/pci/devices/0000:00:02.0" ;;
   controller-two) make_pci 0000:00:02.0 0x010400 && make_pci 0000:00:03.0 0x0c0400 ;;
   controller-vio-vscsi) rm -r "$bus/vio/devices/71000002/driver" ;;
   controller-vio-fcp) mkdir -p "$bus/vio/devices/30000003" &&
       printf 'vio:TfcpSIBM,vfc-client\n' >"$bus/vio/devices/30000003/modalias" ;;
   controller-bus-empty) rm -r "$bus/pci/devices"/* "$bus/vio" ;;
   esac
   ```

   and, beside `make_disk`:

   ```bash
   make_pci() {
       mkdir -p "$workspace/sys/bus/pci/devices/$1"
       printf '%s\n' "$2" >"$workspace/sys/bus/pci/devices/$1/class"
   }
   ```

2. After the existing `disk-*` fault loop, add a loop over `controller-pci-storage`,
   `controller-pci-fc`, `controller-pci-unreadable`, `controller-vio-vscsi`, `controller-vio-fcp`
   (reason `disk-controller: failed unbound=1`) and `controller-two` (`unbound=2`), asserting
   nonzero status, `disk: failed`, the reason, no `mount`/`curl`/`kexec` call, and unchanged disks.
   Then `run_launcher "eth0" controller-bus-empty` must print `disk: passed`. Extend the final
   non-Fedora loop to also run `controller-pci-storage` per distribution and assert its reason.
3. Run `bash tests/test_iso_chain_launch.sh`; expect the red line above.
4. In the launcher, add `sys_bus=${ISO_CHAIN_SYS_BUS:-/sys/bus}` after `sys_block`, add
   `check_controllers` before `check_disk`, and call `check_controllers || return 1` right after
   `check_disk`'s settle line:

   ```sh
   check_controllers() {
       # ADR 0022: a storage controller without a driver hides its disks from the count.
       unbound=0
       hex='[0-9a-f]'
       for device in "$sys_bus"/pci/devices/*; do
           [ -e "$device" ] && [ ! -e "$device/driver" ] || continue
           class=$(cat "$device/class" 2>/dev/null) || class=
           # An unreadable or malformed class refuses rather than passes.
           case "$class" in
           0x01* | 0x0c04*) unbound=$((unbound + 1)) ;;
           0x$hex$hex$hex$hex$hex$hex) ;;
           *) unbound=$((unbound + 1)) ;;
           esac
       done
       for device in "$sys_bus"/vio/devices/*; do
           [ ! -e "$device/driver" ] || continue
           case "$(cat "$device/modalias" 2>/dev/null)" in
           vio:Tvscsi* | vio:Tfcp*) unbound=$((unbound + 1)) ;;
           esac
       done
       [ "$unbound" -eq 0 ] || {
           printf 'disk-controller: failed unbound=%s\n' "$unbound" >&2
           return 1
       }
   }
   ```

5. Run `bash tests/test_iso_chain_launch.sh`; expect `launcher shell tests: passed`.
6. Update the `DRACUT_DRIVERS` comment to say the guard refuses a storage controller left without
   a driver (ADR 0022); update README's guard paragraph (the reason line, the operator mitigation)
   and AGENTS.md (`ISO_CHAIN_SYS_BUS` in the harness list; the launcher description; the ADR count
   under Key Directories and a one-line ADR 0022 entry under Important Files).
7. Run `just check`; expect exit 0. Commit.

## Task 2: QEMU proof

Interfaces: consumes Task 1's launcher and reason line.

Verification:

- Mode: task-test-not-applicable. Contract: spec Success 3. Reason: only a guest kernel produces
  real sysfs; the record carries console lines and the private run's digests.

Steps:

1. On the Linux x86_64 host with `qemu-system-ppc64`, `zstd`, GNU `cpio`, and `xorriso`, take a
   private launcher ISO, its `vmlinuz`, and its zstd `initramfs.img`. Recover the kernel arguments
   with `xorriso -osirrox on -indev <iso> -extract /boot/grub/grub.cfg <dir>/grub.cfg`, expanding
   the selected entry's `iso_chain_args_<n>` variable by hand. Build the overlay:

   ```bash
   mkdir -p overlay/usr/libexec
   git show HEAD:assets/dracut/iso-chain-launch.sh >overlay/usr/libexec/iso-chain-launch.sh
   chmod 755 overlay/usr/libexec/iso-chain-launch.sh
   (cd overlay && find usr | cpio -o -H newc --quiet) >overlay.cpio
   zstd -dq -c initramfs.img >initrd.img   # appending after the zstd stream failed to unpack
   truncate -s %4 initrd.img && cat overlay.cpio >>initrd.img
   ```

   Boot QEMU pSeries with `-kernel vmlinuz -initrd initrd.img -append '<arguments>'`,
   `-device virtio-scsi-pci`, one blank virtio qcow2, the ISO on `scsi-cd`, and the user-network
   `virtio-net-pci` with the manifest's MAC.
2. Run twice: with `-device megasas` plus a `scsi-hd` on it (expect `disk-controller: failed
   unbound=1`, `disk: failed`), and without it (expect `disk: passed`).
3. Write `docs/experiments/2026-10-04-unbound-storage-guard.md`: host and tool versions, commit,
   command shapes, console lines, disk digests unchanged, boundaries (QEMU only; PowerVM adapters
   unproven). Run `just check-markdown`; commit.
