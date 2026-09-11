# Fedora Kickstart Installation Implementation Plan

Goal: authenticate a Kickstart, install Fedora 44 ppc64le into a disposable qcow2 overlay, and
machine-verify a subsequent disk-only boot.

Architecture: the existing Python standard-library CLI owns strict manifests, source preparation,
QEMU orchestration, and evidence verification. The existing dracut launcher downloads the fifth
authenticated artifact and passes its embedded initramfs path to Anaconda. A Fedora-specific
Kickstart creates the durable boot proof; separate phase logs prevent installer output from
satisfying the disk-only boot check.

Tech stack: Python 3.14 standard library, POSIX shell plus existing dracut tools, Fedora 44
Kickstart/Anaconda, QEMU pSeries/POWER9 and qemu-img, qcow2, systemd, and existing repository
guardrails. No dependency is added.

Expected implementation size: 900–1,300 changed lines (L) — about 350 Python, 55 launcher shell, 45
Kickstart, 550 focused tests, and 150 operator and experiment documentation lines.

## Global Constraints

- Host architecture: x86_64. Target architecture: ppc64le. Relationship: different.
- Manifest version 2 is rejected; version 3 has exact fields and a required Kickstart artifact.
- Kickstart input is a non-symlink regular file from 1 through 1,048,576 bytes and publishes at
  `/profiles/fedora-44/ks.cfg` with exact size and SHA-256.
- The complete PowerPC command line remains limited to 2,048 bytes including its terminating byte.
- The reference storage contract names only `/dev/vda`; other storage layouts are out of scope.
- The backing qcow2 digest is unchanged and only a new output overlay receives guest writes.
- QEMU uses fixed argv, no shell, no monitor, explicit image formats, bounded phase logs, an
  install-only raw capture on a quota-limited private filesystem, no disk-only boot NIC, and
  declared timeouts.
- Raw logs, captures, disk images, manifests, Kickstarts, source trees, addresses, boot IDs, and
  digests remain private.
- No native PowerVM, physical POWER9, HMC, VIOS, generalized distro, DHCP, IPv6, or public-mirror
  behavior is added.
- Guardrails: `just check`; `.venv/bin/pre-commit run --all-files` before delivery.

## Task 1: Replace the profile contract and publish the Kickstart

Files: modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`.

### Interfaces

- `InstallerProfile.kickstart: Artifact` is required by `_installer_profile` and emitted by
  `_manifest_data`.
- `load_manifest_bytes(encoded)` accepts only version 3 and canonicalizes the exact profile shape.
- `_kernel_arguments(manifest, digest, profile)` emits the three
  `iso_chain.profile_kickstart_*` arguments before the memory argument.
- `prepare_fedora_source(args)` consumes required `args.kickstart: Path`, writes the fixed private
  copy, and emits the profile value consumed by the manifest parser.
- `prepare-fedora-source --kickstart FILE` is required by `parser()`.

### Verification

- Mode: focused-test — strict version-3 profile contract in `ManifestV3Tests`; version 2, absent or
  unknown fields, invalid paths, boolean/zero/oversized sizes, and malformed digests fail. Expected
  red: the current parser rejects version 3 or accepts no Kickstart field. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV3Tests -v`, all cases `ok`.
- Mode: focused-test — source publication in `FedoraSourceTests`; empty, oversized, symlinked,
  missing, or raced Kickstart inputs do not publish, while valid bytes appear once at the fixed path
  and match `profile.json`. Expected red: `--kickstart` and the output file are absent. Green
  command: `.venv/bin/python -m unittest tests.test_iso_chain.FedoraSourceTests -v`.
- Mode: focused-test — command-line binding in `ManifestV3Tests`; all three exact fields appear and
  an enlarged Kickstart path can trip the existing 2,048-byte guard before GRUB. Expected red: the
  arguments are absent. Green command: the ManifestV3Tests command above.

### Steps

1. Rename the version-focused test class and fixture values to version 3, add the valid Kickstart
   artifact, then add strict negative cases. Run the focused manifest command and retain its failure.
2. Add `MAX_KICKSTART_BYTES = 1024 * 1024`, the frozen dataclass field, exact parser field, canonical
   serializer entry, required version, and kernel arguments. Rerun the manifest tests to green.
3. Extend source-test arguments with a private Kickstart fixture. Add happy-path byte/digest checks
   and the five failure classes; run the source tests and retain the initial failures.
4. Add required `--kickstart`; open and bound it with `_bounded_file`, write the accepted bytes into
   the temporary profile directory with mode 0600, derive `_artifact_data`, validate the complete
   profile, and publish through the existing directory edge. Rerun source tests to green.
5. Run `just check` and commit as `feat: bind Kickstart in manifest version 3`.

Acceptance: canonical manifests and prepared profiles carry the exact artifact, unsafe inputs fail
before extraction/publication where possible, and no compatibility path accepts version 2.
Rollback reverts this commit as one pre-release contract replacement.

## Task 2: Verify Kickstart download and handoff in the launcher

Files: modify `assets/dracut/iso-chain-launch.sh`; modify `tests/test_iso_chain_launch.sh`.

### Interfaces

- Required command-line keys are `iso_chain.profile_kickstart_path`,
  `iso_chain.profile_kickstart_size`, and `iso_chain.profile_kickstart_sha256`.
- `download_artifact kickstart ...` creates `$workspace/kickstart` only after HTTP, regular-file,
  exact-size, and digest checks.
- The fixed Anaconda argv adds `inst.ks=file:/iso-chain/ks.cfg` beside `inst.repo`; source
  preparation embeds the same bytes represented by the profile artifact in the installer initramfs.
- Task 1 supplies the exact kernel-argument names and manifest bounds.

### Verification

- Mode: focused-test — shell configuration and happy path; the command-line fixture has all three
  fields, mocked curl returns `ks`, request count becomes five, and kexec contains one local-file
  `inst.ks`. Expected red: mocked curl rejects the new URL or the request/argv assertions fail.
  Green command: `bash tests/test_iso_chain_launch.sh`, ending `launcher shell tests: passed`.
- Mode: focused-test — failure paths; missing/duplicate fields, invalid canonical path, zero or
  oversized size, malformed digest, HTTP failure, exact-size failure, digest failure, and command
  overflow emit the existing fixed stage class without kexec. Expected red: each new case reaches
  kexec or reports the wrong stage. Green command: the shell-test command above.
- Mode: focused-test — preserved networking; the successful kexec argv still has the exact static
  `ip`, `ifname`, route, DNS, `inst.repo`, console, `rd.neednet=1`, `ip=dhcp` absence, and IPv6
  disablement assertions. Expected red: no new test failure once implementation is correct. Green
  command: the shell-test command above.

### Steps

1. Extend `command_line`, fake curl, request count, and kexec assertions; add configuration and
   transfer faults, run the shell suite, and retain the failed fifth-artifact observation.
2. Parse and validate the three values using the existing artifact path/size/digest functions.
3. Add the bounded download after repository metadata and before `artifacts: passed`; ensure the
   workspace cleanup path owns it without another cleanup branch.
4. Add one fixed `inst.ks` argv element, run every shell case, then run `just check`.
5. Commit as `feat: pass verified Kickstart to Anaconda`.

Acceptance: only exact verified bytes produce `inst.ks`, and the prior network and cleanup contracts
remain covered. Rollback removes the fifth artifact and returns the launcher to pre-install mode.

## Task 3: Add the Fedora reference Kickstart and persistent QEMU workflow

Files: create `assets/kickstart/fedora-44-power9.ks`; modify `scripts/iso_chain.py`; modify
`tests/test_iso_chain.py`.

### Interfaces

- `_qemu_network(manifest, capture)` returns the one-adapter fixed argv used by the install phase.
- `install_qemu_commands(iso, overlay, manifest, install_capture, memory_mib)` returns
  `(install_argv, boot_argv)`; only the first contains CD-ROM and network-capture arguments and
  neither contains `-snapshot`, monitor, QMP, or a caller tail.
- `install_fedora(args)` validates inputs and one nonexistent output directory, stages fixed
  `disk.qcow2`, `install-console.log`, `boot-console.log`, `install.pcap`, and `result.json` children,
  creates the private overlay with explicit `-f qcow2 -F qcow2`, runs both phases through
  `_run_qemu_phase`, checks their logs and hashes, and publishes the directory without replacement.
- `_installed_boot_id(encoded)` returns the one canonical UUID from the fixed boot marker or raises
  `ValidationError` without echoing input.
- `install-fedora` exposes required `--iso`, `--disk`, `--config`, and `--output` paths plus
  `--memory-mib`, `--install-timeout-seconds`, and `--boot-timeout-seconds` bounded from 1 through
  86,400. The output parent must be quota-limited for the private run and have at least 16 GiB free.

### Verification

- Mode: focused-test — Kickstart structure in `InstallTests`; pykickstart-relevant commands select
  text, `/dev/vda`, required Power partitioning, locked root, disabled first boot, `%post
  --erroronfail`, completion token, enabled console service, boot ID, and poweroff, with no secret or
  endpoint. Expected red: the asset is missing. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.InstallTests -v`.
- Mode: focused-test — fixed phase argv; install has read-only boot-first ISO, writable overlay, and
  one matched-network capture; boot has only the overlay plus `-nic none`. Expected red: the
  interface does not exist. Green command: the InstallTests command above.
- Mode: focused-test — storage/output safety; wrong image format, input symlink, existing output,
  low free space, qemu-img failure or timeout, publication race, changed backing, unchanged overlay,
  console overflow, phase timeout, nonzero QEMU, and missing/repeated/malformed marker fail without
  replacing outputs. Expected red: the subcommand is absent. Green command: the InstallTests
  command above.
- Mode: focused-test — two successful mocked QEMU phases publish one overlay, two logs, one capture,
  and one result record with private creation and distinct command identities. Expected red: the
  subcommand is absent. Green command: the InstallTests command above.

### Steps

1. Add structural Kickstart tests and the fixture. Validate its Fedora 44 syntax with `ksvalidator`
   when the command exists; otherwise record that target-sensitive check as pending live evidence.
2. Add pure command constructors and boot-marker parser tests, retain red, implement the minimum
   fixed argv, install-only NIC, and parser, and rerun focused tests.
3. Add mocked orchestration tests for validation, qemu-img JSON, setup and phase timeouts, console
   overflow, subprocess failures, hashes, result record, cleanup, and no-replace publication; retain
   the initial missing-command failure.
4. Implement `install_fedora` with private same-parent staging, explicit command vectors,
   bounded `subprocess.Popen` console streaming, 60-second qemu-img calls, a quota/capacity preflight,
   canonical `result.json`, and existing no-replace primitives. Do not add a generalized runner or
   disk abstraction.
5. Add the parser surface and main dispatch, rerun InstallTests, run `just check`, and commit as
   `feat: prove persistent Fedora install and boot`.

Acceptance: mocked behavior proves the two-process boundary, only the overlay mutates, each named
external process is time-bounded, and success requires the disk-only marker. Rollback removes the
command and fixture; the verified launcher remains independently usable with another reviewed
Kickstart.

## Task 4: Bind installation evidence

Files: modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`.

### Interfaces

- `verify_fedora_install_evidence(args) -> tuple[str, ...]` consumes the eleven exact inputs and
  produces only fixed public-safe result lines.
- `_verify_install_http_requests(records, profile)` requires the five launcher requests in order,
  exact artifact byte counts, one Kickstart request, and later repository traffic.
- `_installed_boot_id(encoded)` is consumed from Task 3 without changing its contract.
- `verify-fedora-install-evidence` requires `--record`, `--config`, `--kickstart`,
  `--install-console-log`, `--boot-console-log`, `--access-log`, `--result`, `--install-pcap`,
  `--backing-hash-before`, `--backing-hash-after`, `--overlay-hash-before`, and
  `--overlay-hash-after`.

### Verification

- Mode: focused-test — strict record and digest binding in `FedoraInstallEvidenceTests`; canonical
  happy input passes, while unknown/duplicate/missing fields, replaced inputs, wrong profile, wrong
  Kickstart, invalid disk label, false same-run flag, and input bounds fail. Expected red: parser and
  verifier are absent. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.FedoraInstallEvidenceTests -v`.
- Mode: focused-test — machine evidence; reordered/missing/repeated Kickstart requests, failed HTTP,
  absent repository traffic, install-launcher mismatch, nonzero or malformed process results, boot
  marker in only the install log,
  missing/repeated/malformed boot markers, changed backing, unchanged/empty overlay, and either
  forbidden capture fail. Expected red: the verifier is absent. Green command: the evidence-test
  command above.
- Mode: focused-test — public-safe output; pass lines classify machine and operator evidence and no
  failure includes supplied paths, labels, boot IDs, network values, or bytes. Expected red: absent
  interface. Green command: the evidence-test command above.

### Steps

1. Build canonical in-memory fixtures for the eleven inputs and strict record; add the parser and
   replacement cases, run focused tests, and retain the missing-subcommand failure.
2. Implement exact record/result parsing, manifest/Kickstart identity, and reuse
   `_verify_input_digests`, `_disk_digest`, `verify_launcher_log`, and `verify_pcap` at their existing
   boundaries.
3. Add install-specific HTTP ordering, boot-marker, backing equality, overlay inequality/nonempty,
   and same-run checks. Keep errors fixed and non-echoing.
4. Add parser/main dispatch, run focused tests, then `just check` and commit as
   `feat: verify Fedora installation evidence`.

Acceptance: no single log, marker, hash, or operator flag can satisfy the record; the bound set of
eleven inputs must agree. Rollback removes only the post-install verifier.

## Task 5: Document and exercise the complete proof

Files: modify `README.md`; create `docs/experiments/2026-09-10-fedora-kickstart-install.md`.

### Interfaces

- README consumes the exact Task 1–4 subcommands and file names and distinguishes smoke from
  destructive-to-overlay installation.
- The experiment record supplies public-safe commands, versions, timeouts, result lines, disk hash
  relationships, request counts, limitations, and cleanup without raw identifiers.
- The live arm consumes Fedora Server 44 ppc64le source media, the reference Kickstart, a disposable
  qcow2 backing disk, ppc64le QEMU, and private evidence storage.

### Verification

- Mode: focused-test — ppc64le QEMU full path; prepare version-3 source, build the launcher, run
  `install-fedora`, filter the install capture, create the canonical record, and run
  `verify-fedora-install-evidence`. Expected result: fixed manifest, Kickstart, HTTP, installation,
  disk, disk-only boot, and two network pass lines plus `same-run: operator-reviewed`.
- Mode: focused-test — controlled live failures; invalid Kickstart preparation, unreachable local
  HTTP, bounded install timeout, installation failure, wrong target disk, and a boot-log false marker
  each fail at their named boundary without a pass record.
- Mode: task-test-not-applicable — native PowerVM/HMC/VIOS behavior; the approved exclusions assign
  it to separate future work and this environment has no authorized native resource.
- Mode: task-test-not-applicable — prose readability; no executable assertion can establish that a
  human can follow the narrative, so review checks it against the already-executed commands while
  guardrails check Markdown structure and references to implemented interfaces.

### Steps

1. Check the live host for `qemu-system-ppc64`, `qemu-img`, `ksvalidator`, ppc64le GRUB tools, Fedora
   44 media, RAM, a quota-limited private filesystem, and disk capacity before starting the bounded
   run. Record an exact missing
   prerequisite rather than substituting another release or architecture.
2. Use a fresh mode-0700 private directory and the fixed reference Kickstart. Run preparation,
   build, install, boot, capture filtering, record construction, and the verifier with bare exit
   statuses and declared timeouts. Confirm the deployed ISO was built from branch HEAD.
3. Run the controlled failure arms that the available environment can exercise without repeating
   the full installation; preserve raw evidence privately and record only public-safe facts.
4. Update README commands and warnings only after their interface exists. Write the experiment
   outcome, limitations, cleanup, and whether the live arm passed or named a prerequisite blocker.
5. Run `just check` and `.venv/bin/pre-commit run --all-files`, commit as
   `docs: record Fedora unattended installation proof`, and retain the exact guardrail outputs.

Acceptance: documentation names only installed interfaces; the live result is either a complete
machine-verified pass or an exact, public-safe prerequisite gap with no false success claim.
Rollback removes the experiment record and installation-specific README section.
