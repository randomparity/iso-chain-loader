# Installed-Disk Boot and Blank-Target Guard Implementation Plan

Goal: every launcher ISO boots an installed disk by default, and the launcher refuses any installer
handoff unless exactly one blank non-optical disk is present. Spec:
`docs/workflow/specs/2026-10-02-installed-disk-boot-design.md`; ADR 0018.

Architecture: `_grub_config` gains a top-level `search` loop and a conditional `installed disk`
entry; `iso-chain-launch.sh` gains `check_disk`, called from `main` after the memory check;
`verify_launcher_log` requires the new `disk: passed` marker.

Tech stack: Python 3.14 standard library, POSIX `sh` in the dracut launcher, `unittest`, Bash test
harness, QEMU pSeries for the proof.

Expected implementation size: 280–320 changed lines (M) — about 25 Python, 35 shell, 120 test, and
120 documentation and experiment lines across the four tasks below. Corrected after the build from
170–240: the experiment record, README guard text, and launcher-log fixture churn were larger than
first estimated; the scope is unchanged.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function.
- The launcher stays POSIX `sh` using only tools in `DRACUT_TOOLS`; the shell harness runs on Linux
  and macOS, so the test may rely only on `dd bs= skip= count= seek= conv=notrunc` and `printf`.
- Every GRUB menu entry stays under 1,024 bytes; `set timeout=5` is unchanged.
- No private data (MACs other than QEMU's documented default, hostnames, addresses) in committed
  evidence; raw logs and disks stay in private storage.
- `.secrets.baseline` covers only `Justfile`, which this change does not touch.

## File map

- `scripts/iso_chain.py` — `_grub_config` (menu policy), `DRACUT_TOOLS`, `verify_launcher_log`
  and `_launcher_results` (evidence). Extended in place.
- `assets/dracut/iso-chain-launch.sh` — `check_disk`, called from `main`. Extended in place.
- `tests/test_iso_chain.py` — `BuildTests`, `PrepareTests`, the six launcher-log fixtures and
  three expected-result tuples in `EvidenceTests`, `InstallerEvidenceTests`, `UbuntuEvidenceTests`,
  `RockyEvidenceTests`, `OpenSUSEEvidenceTests`, `FedoraInstallEvidenceTests`.
- `tests/test_iso_chain_launch.sh` — fake sysfs and device files, disk cases.
- `README.md`, `AGENTS.md`, `docs/experiments/2026-10-02-installed-disk-boot.md`.

## Task 1: Installed-disk menu entry

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: consumes `Manifest.profiles`, `Manifest.selected_profile`; produces the `grub.cfg`
text containing `menuentry 'installed disk' --id installed_disk`.

Verification:

- Mode: focused-test. Contract: search loop, conditional entry and default, profile default kept,
  every entry under 1,024 bytes. Test `BuildTests.test_menu_offers_an_installed_disk_by_default`
  plus the updated `test_menu_entries_fit_the_powervm_cas_reboot_buffer`, which now collects
  indented entries with `re.findall(r"^ *menuentry .*?^ *}$", ...)` and expects
  `len(profiles) + 1`; it checks the installed entry separately and zips the profiles with the
  remaining entries only. Red: `installed_disk` absent. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.

Steps: write the tests; run red; append to `_grub_config`, between the variables and the profile
entries, the exact block in the spec's "GRUB configuration shape"; run green; commit.

## Task 2: Launcher disk guard

Files: `assets/dracut/iso-chain-launch.sh`, `scripts/iso_chain.py` (`DRACUT_TOOLS` gains
`/usr/bin/dd`), `tests/test_iso_chain_launch.sh`, `tests/test_iso_chain.py` (`PrepareTests`
asserts `dd` in the `--install` list).

Interfaces: environment `ISO_CHAIN_SYS_BLOCK` (default `/sys/block`) and `ISO_CHAIN_DEV_DIR`
(default `/dev`); console lines `disk: passed`, `disk-settle: failed`, `disk-count: failed count=<n>`,
`disk-blank: failed`, `disk: failed`.

```sh
zero_mib_sha256=30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58

zero_mib() {
    # A failed read or digest yields a different value, so it refuses rather than passes.
    found=$(dd if="$dev_dir/$1" bs=512 skip="$2" count=2048 2>/dev/null | sha256sum)
    [ "${found%% *}" = "$zero_mib_sha256" ]
}

check_disk() {
    udevadm settle --timeout=60 || { stage_failure disk-settle; return 1; }
    disk_count=0
    for entry in "$sys_block"/*; do
        [ -e "$entry/device" ] || continue
        case "${entry##*/}" in sr*) continue ;; esac
        disk_count=$((disk_count + 1))
        disk=${entry##*/}
    done
    [ "$disk_count" -eq 1 ] || {
        printf 'disk-count: failed count=%s\n' "$disk_count" >&2
        return 1
    }
    sectors=$(cat "$sys_block/$disk/size") || sectors=
    case "$sectors" in '' | *[!0-9]*) stage_failure disk-blank; return 1 ;; esac
    [ "$sectors" -ge 2048 ] && zero_mib "$disk" 0 && zero_mib "$disk" $((sectors - 2048)) ||
        { stage_failure disk-blank; return 1; }
}
```

`main` calls `check_disk || fail 'disk: failed'` then prints `disk: passed`, after the memory line
and before the `case "$distribution"` dispatch.

Verification:

- Mode: focused-test. Contract: refusal for zero disks, two disks, nonzero first MiB, nonzero last
  MiB, and 1,024 sectors, each with `disk: failed`, its reason line, no `mount`/`curl`/`kexec`
  call, and an unchanged disk file; `sr0` and a link-less `loop0` not counted. Harness:
  `run_launcher` builds `$workspace/sys/block/<name>/{device/,size}` and a sparse
  `$workspace/dev/<name>` per `ISO_CHAIN_DISKS` (default `vda:4096`), with faults `disk-none`,
  `disk-two`, `disk-head`, `disk-tail`, `disk-small`. Red: the cases succeed. Green:
  `bash tests/test_iso_chain_launch.sh` prints `launcher shell tests: passed`.
- Mode: focused-test. Contract: one blank disk passes, `disk: passed` lies between the memory line
  and `media: passed`. Same harness, default run.
- Mode: focused-test. Contract: `dd` installed. `PrepareTests`; green
  `.venv/bin/python -m unittest -v tests.test_iso_chain.PrepareTests`.

## Task 3: Launcher-log evidence

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: `_launcher_results` returns `"disk: passed"` after `"memory: passed"`;
`verify_launcher_log` calls `_launcher_marker(visible, "disk: passed", position)` after the
memory evidence.

Verification:

- Mode: focused-test. Contract: missing or misordered `disk: passed` is rejected; accepted results
  include it. Test `EvidenceTests.test_rejects_missing_or_misordered_disk_marker`; the six
  fixtures gain `"disk: passed"` after the memory line and the three expected tuples gain it. Red:
  the missing-marker log verifies. Green: `.venv/bin/python -m unittest discover -s tests`.

## Task 4: Documentation and QEMU proof

Files: `README.md` (menu text, guard, marker list, and that `smoke` needs a fresh blank disk such
as `qemu-img create -f qcow2 DISK.qcow2 8G`, since an installed disk boots instead), `AGENTS.md`
(stage 4 menu text, launcher contract, marker list),
`docs/experiments/2026-10-02-installed-disk-boot.md`.

Verification:

- Mode: task-test-not-applicable. Surface: prose and the experiment record; no executable consumer
  reads them, and the QEMU boot needs emulated firmware the suites cannot run.

Proof arms, each with a launcher ISO built by `container-build` from this branch and an initramfs
from `container-prepare-initramfs`, raw evidence in private storage:

1. Fedora 44 Cloud ppc64le overlay with the ISO first: `installed disk` boots to login.
2. A blank 8 GiB disk: the profile is default and the launcher prints `disk: passed`.
3. A disk with nonzero bytes in its first MiB and no GRUB files: `disk-blank: failed`, no `kexec`.
4. Two blank disks and no disk: `disk-count: failed count=2` and `count=0`.

Final gate: `just check`, `.venv/bin/pre-commit run --all-files`, `git diff --check main...HEAD`.
