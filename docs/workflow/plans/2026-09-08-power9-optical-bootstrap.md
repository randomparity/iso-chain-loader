# POWER9 Optical Bootstrap Implementation Plan

Goal: provide a repeatable, network-disabled ppc64le optical and kexec feasibility experiment.

Architecture: one Python standard-library CLI builds the GRUB ISO, launches the fixed QEMU smoke
configuration, and verifies a private console log. Unit tests exercise local boundaries with fake
external processes; a redacted report records the real emulator result and native gap.

Tech stack: Python 3.14 standard library, GRUB `powerpc-ieee1275`, xorriso, QEMU pSeries/SLOF, Linux,
and kexec-tools.

Expected implementation size: 280–420 changed lines (M): 100–140 for the CLI, 100–160 for tests,
10–25 for check/ignore integration, and 70–95 for user documentation and the feasibility report.
If the work exceeds 420 lines or requires a custom initramfs, stop and re-scope before expanding it.

## Global Constraints

- Host architecture: x86_64. Target architecture: ppc64le. Relationship: different.
- The builder downloads nothing, modifies no input, refuses existing output, and invokes no shell.
- The smoke command always uses `-nic none` and `-snapshot`; it exposes no arbitrary QEMU arguments.
- Kernel arguments always include `console=hvc0 rd.neednet=0 ip=off` and cannot override network
  settings or inject multiline GRUB commands.
- Raw console logs, disk images, kernels, initramfs files, GRUB modules, and generated ISOs are not
  committed or printed by the verifier.
- Native POWER9, PowerVM firmware policy, HMC, and VIOS behavior remain unproven. No mapping mutation
  occurs without a recorded exclusive VIOS window.
- No full distribution launcher, hmc-mcp change, DHCP, dependency addition, or VM-tooling change.
- Guardrails: `just check`; `.venv/bin/pre-commit run --all-files` before delivery.

## Task 1: Implement the bounded experiment CLI

Files: create `scripts/iso_chain.py`; create `tests/test_iso_chain.py`; modify `.gitignore` and
`Justfile`.

### Interfaces

- Provides `build`, `smoke`, and `verify-log` subcommands with the exact arguments in the design.
- `build_iso(args)` consumes validated local paths and invokes `grub2-mkrescue` without a shell.
- `qemu_command(iso, disk)` returns the fixed argument vector consumed by `smoke`.
- `verify_log(path)` returns the three fixed pass lines or raises one concise validation error.
- The aggregate `just check` consumes `just check-tests`, which runs
  `.venv/bin/python -m unittest discover -s tests -v`.

### Verification

- Mode: focused-test — CLI validation; missing/wrong-kind inputs, wrong GRUB platform metadata,
  multiline or network-overriding kernel arguments, and existing output each fail before execution.
  Red observation: each new test fails because the module/subcommands do not exist. Green command:
  `.venv/bin/python -m unittest discover -s tests -v`, all cases report `ok`.
- Mode: focused-test — image publication; a fake `grub2-mkrescue` observes the expected directory,
  staged config, kernel, and initramfs and creates the temporary image; the final output appears
  once, while tool failure and a publication race leave the destination unchanged. Use the same red
  observation and green command.
- Mode: focused-test — smoke isolation; `qemu_command` contains one `-nic none`, `-snapshot`, POWER9
  pSeries/TCG, a read-only boot-first CD, and no user-supplied tail. Use the same red observation and
  green command.
- Mode: focused-test — evidence contract; ordered markers with distinct valid boot IDs pass;
  missing, reordered, equal/malformed-ID, first-stage-only synthetic, logical-LAN,
  non-loopback-link, and DHCP-lease fixtures fail without echoing fixture content. Use the same red
  observation and green command.

### Steps

1. Add failing `unittest` cases importing `scripts.iso_chain` and covering every verification item;
   run the focused command and retain its import failure.
2. Implement `argparse` subcommands, `ValidationError`, regular-path checks, GRUB `modinfo.sh`
   validation, token validation, private same-parent staging, `subprocess.run(..., check=True)`, and
   no-replace `os.link`; rerun the focused command and expect all cases `ok`.
3. Implement `qemu_command` as a pure list constructor and `smoke` with `os.execvp`; assert the exact
   vector in tests and rerun the focused command.
4. Implement ordered/forbidden log validation and fixed output; run all evidence cases.
5. Ignore `*.iso` and `*.log`, add `check-tests` to `just check`, run `just check`, and commit as
   `feat: add POWER9 optical feasibility harness`.

Acceptance: all CLI trust-boundary and behavior tests pass, `just check` passes, and generated/private
artifacts remain outside Git. Rollback removes the CLI/tests and the two integration edits.

## Task 2: Run and report the emulator proof

Files: modify `README.md`; create `docs/experiments/2026-09-08-power9-optical-bootstrap.md`.

### Interfaces

- Consumes Task 1's three CLI subcommands and the operator-provided ppc64le VM artifacts.
- Provides exact build/smoke/loopback-check/kexec/verify commands and a redacted result table.
- Later native operators consume the LPAR gate and unproven-evidence list.

### Verification

- Mode: focused-test — end-to-end emulator behavior; build an ISO, start the fixed smoke runner,
  emit the loopback-only marker, load/execute the second kernel, and run `verify-log`. Before the
  implementation, the command is unavailable; after it, expect the three fixed `passed` lines.
- Mode: task-test-not-applicable — native PowerVM optical/security behavior; no native LPAR or
  authorized VIOS mapping window exists, so no local executable observation can establish it. The
  report must state that exact gap and must not claim success.

### Steps

1. Extract trusted ppc64le kernel, initramfs, and GRUB modules into a private directory and record
   versions plus CPU/RAM/storage facts without publishing identifiers. Preflight the exact kernel
   format, kernel config, root argument, console login, `sudo`, `kexec`, and `/boot` paths required
   by the design; stop with the precise artifact gap if any check fails. Cleanly stop the preflight
   VM and confirm the selected image is not attached to another process before `smoke`; treat a QEMU
   image-lock failure as a prerequisite gap.
2. Run `build`, then `smoke` against a snapshot disk. At first-stage login use one fail-fast command
   to verify `iso_chain_stage=optical` in `/proc/cmdline`, print the kernel boot ID, compare the
   sorted set of interface symlinks with exactly `lo`, and emit the fixed network marker only on
   success. Confirm a regular `bonding_masters`-style control file is ignored and a real second
   interface prevents the marker before relying on this predicate.
3. In the snapshot guest, install the specified systemd oneshot that checks the second-stage
   `/proc/cmdline` and prints the second kernel boot ID and fixed marker to the console. Use
   `kexec -l` with the same relocatable ELF kernel/initramfs, exact root argument, and changed
   `iso_chain_stage=kexec` argument, then `kexec -e`; stop QEMU after the service marker.
4. Run `verify-log`; expect the three fixed pass lines. Preserve the raw log privately for this run.
5. Apply the ADR outcome table: a complete pass changes ADR 0003 to Accepted; an optical, kexec, or
   prerequisite failure records the precise gap and leaves or revises it. Document commands,
   redacted observations, the disposition, the earlier invalid DHCP run and its corrected root
   cause, and the native gap. Run `just check` and commit as
   `docs: record POWER9 optical feasibility result`.

Acceptance: the emulator proof passes without a guest NIC, the report distinguishes emulator from
native evidence, the native gate is actionable, and documentation references only implemented
commands. Rollback removes the report and README section; Task 1 remains independently testable.
