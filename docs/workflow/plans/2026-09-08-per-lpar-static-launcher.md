# Per-LPAR Static Launcher Implementation Plan

Goal: build and verify per-LPAR ppc64le ISOs with fail-closed static networking and explicit profile
selection.

Architecture: Python validates and embeds a canonical JSON manifest and generates the GRUB menu.
A repository-local dracut hook supplies the ppc64le Linux launcher, with one shared payload reused
across ISOs. QEMU/TCG and packet captures prove emulator behavior without claiming native PowerVM.

Tech stack: Python 3.14 standard library, POSIX shell in dracut, GRUB powerpc-ieee1275, tested dracut
107-8.fc43, iproute, curl, xorriso, QEMU ppc64, tcpdump, and the Fedora 43 ppc64le VM image.

Expected implementation size: 380–500 changed lines (M) — derived from the three-task file map.

The upper range reflects executable negative-path evidence rather than additional product scope.

## Global Constraints

- Host architecture: x86_64. Target architecture: ppc64le. Relationship: different.
- Python requires 3.14; just requires 1.57 or newer. Target payload preparation is compatibility-
  tested with dracut 107-8.fc43 on ppc64le and checks required command flags instead of asserting a
  generalized version floor. No Python dependency is added.
- The manifest schema, identifier limits, IPv4-only rules, PowerPC 2,048-byte complete command-line
  limit, five-second GRUB timeout, 30-second HTTP timeout, 1-byte response limit, and fixed evidence
  wording are transcribed from the specification.
- No DHCP client, credentials, redirects, raw private evidence, VM-tooling change, native PowerVM
  claim, installer download, or kexec implementation enters this change.
- Guardrails are `just check` and `.venv/bin/pre-commit run --all-files`; both passed on the base in
  0.67 and 0.71 seconds. CI hard-gates only `just check`. No ADR index exists, so it is not coupled.
- Branch: `feat/per-lpar-static-launcher-4`; base branch: `main`; scope token: `q4-611bec5c`.

## File map

- Modify `scripts/iso_chain.py`: manifest model, payload preparation, ISO build/inspection, smoke
  command, and bounded evidence verification.
- Modify `tests/test_iso_chain.py`: Python contract and command-boundary tests.
- Create `assets/dracut/iso-chain-launch.sh`: fail-closed initqueue-settled runtime hook.
- Create `tests/test_iso_chain_launch.sh`: shell behavior tests with fake sysfs and commands.
- Modify `Justfile`: include the shell test in the shared test gate.
- Modify `README.md`: public usage and evidence boundary.
- Create `docs/experiments/2026-09-08-static-launcher.md`: anonymous VM result and native gap.

## Task 1: Manifest-driven ISO construction

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces:

- Define immutable `NetworkConfig` and `Manifest` dataclasses and
  `load_manifest(path: Path) -> tuple[Manifest, bytes, str]`, returning the validated value,
  canonical bytes, and lowercase SHA-256.
- Replace build arguments with `--config`, `--grub-modules`, `--kernel`, `--initramfs`, and
  `--output`; `build_iso(args: argparse.Namespace) -> None` retains atomic publication.
- Add `inspect_iso(path: Path) -> bytes` for later verification and documentation.
- Later tasks rely on kernel arguments named `iso_chain.mac`, `iso_chain.address`,
  `iso_chain.route`, `iso_chain.dns`, `iso_chain.source`, `iso_chain.profile`, and
  `iso_chain.config_sha256`.

Verification:

- Mode: focused-test — schema, canonicalization, routing, and redacted validation; add
  `ManifestTests` cases, first observe failures because `load_manifest` is absent, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestTests -v` and expect all cases `ok`.
- Mode: focused-test — GRUB menu/default, the complete 2,048-byte command-line boundary, and distinct
  embedded manifests; extend `BuildTests`, first observe the old builder reject `config`, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.BuildTests -v` and expect all cases `ok`.
- Mode: focused-test — bounded ISO inspection and fixed diagnostics; add `InspectTests`, first
  observe absence of `inspect_iso`, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.InspectTests -v` and expect all cases `ok`.

Steps:

1. Add fixtures for valid manifests, every field/type/bound failure, route ordering and gateway
   reachability including the default route, unknown keys, canonical equivalence, malicious strings,
   and two manifests with distinct profile/digest values.
2. Run the three focused commands and retain the expected missing-interface failures.
3. Implement the two dataclasses, 64-KiB descriptor-bound read, strict JSON/schema validation,
   `ipaddress`/`urllib.parse` checks, canonical serialization, and fixed diagnostics.
4. Generate the five-second GRUB menu and restricted argument vector from the validated manifest;
   reject complete command lines over 2,048 bytes including separators and terminating NUL, then
   stage canonical JSON and the shared payload before invoking `grub2-mkrescue` without a shell.
5. Implement inspection through one fixed `xorriso` argument vector into private temporary state,
   revalidate the extracted bytes, and emit canonical JSON only on success.
6. Run all three focused commands, then `just check`; expect zero failures and warnings.
7. Commit as `feat: build manifest-driven ppc64le ISOs`.

Acceptance: two manifests generate different defaults, arguments, embedded canonical bytes, and
digests; every invalid input fails before an external command; failures and races leave no output.

## Task 2: Shared dracut launcher payload

Files: `assets/dracut/iso-chain-launch.sh`, `assets/dracut/iso-chain-launch.service`,
`assets/dracut/iso-chain.target`, `tests/test_iso_chain_launch.sh`, `Justfile`,
`scripts/iso_chain.py`, and `tests/test_iso_chain.py`.

Interfaces:

- `iso-chain-launch.sh` consumes the exact `iso_chain.*` arguments from Task 1 and returns after a
  fixed success or fails after a fixed diagnostic. Tests set `ISO_CHAIN_SYS_CLASS_NET` and
  `ISO_CHAIN_RESOLV_CONF` to private fixtures; production defaults are `/sys/class/net` and
  `/etc/resolv.conf`.
- `iso-chain.target` is selected by `rd.systemd.unit`; it requires a one-shot launcher service after
  udev settling, has no real-root dependency, enters `emergency.target` on service failure, and stays
  active after success so the probe cannot repeat or fall through to a later root failure.
- `prepare_initramfs(args: argparse.Namespace) -> None` checks `platform.machine() == "ppc64le"`,
  verifies required dracut flags, and invokes `dracut --no-hostonly --reproducible` with fixed
  `--include`, `--install`, and `--force-drivers` arguments for the launcher, service, target,
  systemd support, and named kernel.

Verification:

- Mode: focused-test — exact adapter cardinality before network commands; add shell cases for zero,
  one, and two normalized MAC matches, first observe the script missing, then run
  `bash tests/test_iso_chain_launch.sh` and expect `launcher shell tests: passed`.
- Mode: focused-test — ordered static address/routes/DNS, bounded no-redirect HTTP, fixed markers,
  and fail-fast command errors; fake `ip` and `curl`, inject one fault at each step, and use the same
  shell command expecting `launcher shell tests: passed`.
- Mode: focused-test — target-only reproducible dracut invocation and atomic output; add
  `PrepareTests`, first observe absence of the command, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.PrepareTests -v` and expect all cases `ok`.
- Mode: focused-test — one-shot rootless lifecycle and terminal states; assert the systemd unit
  relationships and boot one prepared image past the old settled-hook opportunity, first observing
  no launcher marker with the old hook layout, then expecting one probe and an active
  `iso-chain.target` with no later failure marker.

Steps:

1. Write shell fixtures and fake commands that record calls but cannot access a real network; add
   the shell suite to `just check` and confirm it fails because the runtime is absent.
2. Implement argument validation, udev-settled sysfs inventory, exact MAC cardinality, ordered `ip`
   calls, atomic resolver content, bounded curl, fixed markers, and fixed failure paths.
3. Make a controlled fault allow the zero-match case to reach fake `ip`; observe the shell suite
   fail, restore the gate, and observe it pass.
4. Add the dedicated target/service and `prepare-initramfs`, target/platform/tool/flag checks, fixed
   dracut arguments, and no-replace publication tests; implement it and run its focused suite.
5. Boot the prepared image once before the wider VM matrix; require exactly one launcher invocation,
   the explicit success target, and no later failure marker.
6. Run `just check`; expect zero failures and warnings.
7. Commit as `feat: add fail-closed dracut launcher`.

Acceptance: no negative case records an ip/curl call; success records the exact ordered static
operations and fixed markers; preparation rejects x86_64 and never modifies the VM tooling checkout.

## Task 3: VM and packet evidence

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`, `README.md`, and
`docs/experiments/2026-09-08-static-launcher.md`.

Interfaces:

- `qemu_command(iso, disk, manifest, capture_prefix, adapter_state) -> list[str]` accepts only
  `matched`, `missing`, or `duplicate`; each netdev gets one QEMU `filter-dump` pcap.
- `verify_launcher_log(log: Path, manifest: Manifest, expected_profile: str) -> tuple[str, ...]`
  returns fixed pass labels and permits an allowed non-default profile only when named explicitly.
- `verify_pcap(path: Path) -> str` invokes `tcpdump -nn -r PATH -c 1` with a DHCP-only filter,
  captures rather than echoes packet output, and returns `dhcp: absent` only when no match exists.

Verification:

- Mode: focused-test — fixed QEMU NIC/MAC/capture topology and no arbitrary arguments; add
  `SmokeTests`, fault one expected MAC, observe failure, restore it, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.SmokeTests -v` expecting all cases `ok`.
- Mode: focused-test — ordered, redacted log markers and DHCP-free pcaps; add `EvidenceTests` with
  mocked tcpdump and bounded files, first observe missing verifiers, then run
  `.venv/bin/python -m unittest tests.test_iso_chain.EvidenceTests -v` expecting all cases `ok`.
- Mode: task-test-not-applicable — the prose explanation of the native PowerVM evidence gap has no
  executable consumer; compare it manually with the frozen scope and anonymous observed results.

Steps:

1. Add command and verifier tests for three adapter states, output collisions, reordered/spoofed
   markers, oversized evidence, tcpdump failure, a DHCP match, and empty captures.
2. Implement fixed QEMU topology, one no-overwrite capture per netdev, bounded log verification, and
   tcpdump invocation that never publishes packet contents.
3. Run the two focused suites and `just check`; expect zero failures and warnings.
4. In an ephemeral ppc64le VM session, install the declared dracut/runtime packages, copy this
   checkout's local module, run `prepare-initramfs`, and copy only the generated payload back.
5. Start a private local HTTP server, build two anonymous manifests, inspect both ISOs, and boot the
   matched default cases. Require distinct manifest/profile evidence and exactly one expected probe
   each.
6. On one ISO, send the GRUB console input for an allowed non-default profile and require that
   profile with the unchanged manifest digest and exactly one expected probe.
7. Boot missing and duplicate cases. Require fixed adapter failure, no HTTP request, and no packet in
   every capture. Run each pcap verifier and retain its fixed `dhcp: absent` output.
8. Stop the VM/server, account for private artifacts, and publish only anonymous fixed results and
   the native gap in README and the experiment record.
9. Run `just check` and `.venv/bin/pre-commit run --all-files`; expect both green.
10. Commit as `docs: record static launcher VM evidence`.

Acceptance: the VM proves two distinct embedded configurations and static HTTP probes; every capture
is DHCP-free; negative adapter cases produce neither network traffic nor profile fallback; the report
does not expose identifiers or claim native PowerVM success.
