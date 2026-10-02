# openSUSE Installer Profile Implementation Plan

**Goal:** Add an `opensuse`/`15.6` manifest v4 profile that boots openSUSE Leap 15.6's linuxrc and
YaST text installer over static IPv4, and prove it under QEMU pSeries POWER9.

**Architecture:** The profile pins the repository's kernel and initrd, anchored on the signed
repository `CHECKSUMS` (ADR 0014). The Python parser, kernel arguments, preparation, and verifiers
gain one more shape. The launcher gains a two-download linuxrc handoff beside the Ubuntu one.

Expected implementation size: 380–520 changed lines (M) — about 110 Python, 35 shell, 230 Python
tests, 45 shell tests, and 60 docs lines, counted from the tasks below.

## Global Constraints

- Python 3.14, standard library only in `scripts/`; ruff line length 100.
- Every failure raises `ValidationError` naming fields, never values; validation runs before any
  subprocess or tree read (`run.assert_not_called()`).
- Fedora, Rocky, and Ubuntu manifests, kernel arguments, launcher output, and evidence stay
  byte-identical.
- Guardrails: `just check-tests` while iterating; `just check` before each commit. `.secrets.baseline`
  line numbers are refreshed when a covered file shifts (`just check-secrets` shows the drift).
- Spec: `docs/workflow/specs/2026-10-02-opensuse-installer-profile-design.md`.

## File map

| File | Change |
|---|---|
| `scripts/iso_chain.py` | openSUSE parsing and network subset, kernel arguments, `_manifest_data`, `prepare-opensuse-source`, console caller field, launcher-log handoff, `HEAD`-aware access log, openSUSE HTTP rule |
| `assets/dracut/iso-chain-launch.sh` | `valid_opensuse_arguments`, `opensuse_command_line`, `launch_opensuse` |
| `tests/test_iso_chain.py` | `opensuse_profile()`, `opensuse_manifest_data()`; cases in `ManifestV4Tests` and `BuildTests`; new `OpenSUSESourceTests` and `OpenSUSEEvidenceTests` |
| `tests/test_iso_chain_launch.sh` | `opensuse_command_line()` and openSUSE cases |
| `README.md`, `AGENTS.md` | openSUSE profile and `prepare-opensuse-source` |
| `docs/experiments/2026-10-02-opensuse-installer.md` | QEMU proof record |

No transition: each piece extends its existing owner, as Rocky and Ubuntu did.

## Task 1: Manifest and kernel arguments

**Interfaces.** Consumes `_installer_profile`, `load_manifest_bytes`, `_manifest_data`,
`_profile_source_arguments`, and `_external_artifacts`. Provides `PROFILE_RELEASES["opensuse"] ==
"15.6"`, `Repository.treeinfo`/`repomd` typed `Artifact | None`, and the test factories
`opensuse_profile()` (base `/distribution/leap/15.6/repo/oss`, kernel size 6, initramfs size 9,
`repository` `{path: base}`, memory 4096) and `opensuse_manifest_data(**changes)` (one default
route via `10.0.2.2`, DNS `["10.0.2.3"]`, MAC `52:54:00:12:34:56`) used by Tasks 2–4.

**Verification.**

- Parsing, field set, release message, network subset. Mode: focused-test, in
  `ManifestV4Tests.test_opensuse_*`. Red: `profiles.opensuse.distribution/release: must be ...`.
  Green: `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests`.
- Kernel arguments and `build` staging. Mode: focused-test, in
  `ManifestV4Tests.test_opensuse_kernel_arguments` and `BuildTests.test_opensuse_profile_stages_nothing`.
  Red: `AttributeError: 'NoneType' object has no attribute 'size'`. Green: the command above plus
  `tests.test_iso_chain.BuildTests`.
- Canonical round-trip. Mode: focused-test, `ManifestV4Tests.test_opensuse_manifest_round_trips`.
  Red: `AttributeError` in `_manifest_data`. Green: as above.

**Steps.**

1. Add the factories beside `rocky_profile()`. Write failing tests: acceptance; `repository` with
   a `treeinfo` key rejected; `opensuse`/`15.5` rejected with the four-pair message; a second route
   and a second DNS server each rejected with `opensuse handoff supports only the default route
   and at most one DNS server`; kernel arguments that contain `iso_chain.profile_repository_path=`
   and none of `profile_treeinfo`, `profile_repomd`, `profile_kickstart`, `profile_live_iso`;
   `_manifest_data` digest equal to `load_manifest_bytes`'s; `build` writing no `profiles/`
   directory. Run and see red.
2. In `scripts/iso_chain.py`: `PROFILE_RELEASES` gains `"opensuse": "15.6"`; the two `Repository`
   fields become optional. `_installer_profile` parses an `opensuse` profile's `repository` with
   `_manifest_object(..., {"path"}, ...)` and `_url_path`, returning `Repository(path, None, None)`
   and no Kickstart or live ISO; the release message becomes `must be fedora/44, opensuse/15.6,
   rocky/9.8, or ubuntu/26.04.1`. In `load_manifest_bytes`, beside the Ubuntu subset:

   ```python
   # linuxrc's ifcfg= carries one gateway and a space-separated DNS field (ADR 0014).
   if profile.distribution == "opensuse" and (
       [destination for destination, _ in network.routes] != ["0.0.0.0/0"] or len(network.dns) > 1
   ):
       _manifest_error(
           f"profiles.{name}",
           "opensuse handoff supports only the default route and at most one DNS server",
       )
   ```

   When `profile.repository.treeinfo is None`: `_profile_source_arguments` returns only
   `iso_chain.profile_repository_path=<path>`, `_manifest_data` emits `{"path": ...}`, and
   `_external_artifacts` returns `(kernel, initramfs)`. Run and see green; commit
   `feat: accept the openSUSE Leap 15.6 installer profile`.

## Task 2: `prepare-opensuse-source`

**Interfaces.** Consumes `_regular_file`, `_path`, `_url_path`, `_integer`, `_bounded_file`,
`_artifact_data`, `_installer_profile`, `_publish_directory`. Provides `OPENSUSE_PRODUCTS =
b"/ openSUSE-Leap 15.6-1\n"`, `_opensuse_checksums(path: Path) -> dict[str, str]`,
`prepare_opensuse_source(args: argparse.Namespace) -> None`, and the parser entry with
`--checksums --tree --repository-path --minimum-memory-mib --output`.

**Verification.**

- Success and each rejection. Mode: focused-test, `OpenSUSESourceTests`. Red: `AttributeError:
  module 'scripts.iso_chain' has no attribute 'prepare_opensuse_source'`. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.OpenSUSESourceTests`.
- Parser registration. Mode: focused-test, `OpenSUSESourceTests.test_parser_dispatches`. Red:
  argparse `invalid choice`. Green: as above.
- README/AGENTS command documentation. Mode: task-test-not-applicable — prose read by people; no
  executable consumer validates it.

**Steps.**

1. Write `OpenSUSESourceTests`: a tree with `media.1/products` = `OPENSUSE_PRODUCTS`,
   `boot/ppc64le/linux` = `b"kernel"`, `boot/ppc64le/initrd` = `b"initramfs"`, and a `CHECKSUMS`
   built from their digests plus one unrelated line. Cases: the published `profile.json` equals
   the expected `opensuse` profile (sizes 6 and 9) and loads through `_installer_profile`;
   rejections for a line with one space, an upper-case digest, a repeated path, a missing
   `boot/ppc64le/initrd` entry, a `CHECKSUMS` over 1 MiB, a modified kernel, a missing initrd
   (`openSUSE tree boot/ppc64le/initrd: unavailable`), a `products` of `/ openSUSE-Leap 15.5-1\n`
   (with its entry updated), and an existing output; each rejection leaves `OUT` absent. Run and
   see red.
2. Implement in the spec's order. `_opensuse_checksums` reads at most 1 MiB, skips empty lines,
   matches each other line with `re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)`, rejects a repeat
   (`openSUSE CHECKSUMS: malformed or repeated entry`), and requires the three entries
   (`openSUSE CHECKSUMS: missing a boot or product entry`). `prepare_opensuse_source` validates
   every argument and the absent output first, then checks `products` (4 KiB bound, digest and
   bytes), then for `linux` and `initrd` calls `_regular_file(tree / relative, f"openSUSE tree
   {relative}")` before `_artifact_data(..., 2**31)` and compares the digest. It validates the
   profile with `_installer_profile` and publishes `profile.json` through a temporary directory
   beside `OUT` and `_publish_directory`, as `prepare-rocky-source` does.
3. Register the subparser beside `prepare-rocky-source` and its dispatch in `main()`. Add a README
   section after the Rocky one with the `gpgv` sequence (`gpg --dearmor` of
   `gpg-pubkey-29b700a4-62b07e22.asc`, `gpgv --keyring ... CHECKSUMS.asc CHECKSUMS`), the key's
   2026-06-19 expiry, the served tree's required files, and the command; add the command to
   `AGENTS.md`'s lists. Run and see green; `just check`; commit
   `feat: prepare an openSUSE source from the signed CHECKSUMS`.

## Task 3: Launcher handoff

**Interfaces.** Consumes `parse_arguments`, `download_artifact`, `execute_kexec`, `routes`, `dns`,
`address`, `mac`, `lpar`, `source`, `repository_path`. Provides `opensuse_command_line`, whose
output Task 4's `_opensuse_handoff` must match token for token.

**Verification.**

- Downloads and exact kexec arguments, with and without DNS. Mode: focused-test, in
  `tests/test_iso_chain_launch.sh` (`opensuse` block). Red: `test failure: openSUSE arguments are
  wrong` (configuration fails today). Green: `bash tests/test_iso_chain_launch.sh` printing
  `launcher shell tests: passed`.
- Rejections: a `.treeinfo` argument, a live-ISO argument, a second route, a second DNS server,
  and no repository path. Mode: focused-test, `assert_configuration_rejected` cases. Red: the
  first case printing `test failure: ... was accepted`. Green: as above.

**Steps.**

1. Add `opensuse_command_line()` to the shell test, modelled on `ubuntu_command_line()`: profile
   `opensuse`, release `15.6`, kernel `/oss/boot/ppc64le/linux` size 6, initramfs
   `/oss/boot/ppc64le/initrd` size 9, repository `/oss`, one route, `iso_chain.dns=10.0.2.3`.
   Assert the calls file holds the two downloads, no `mount`, and ends in
   `--command-line=ifcfg=52:54:00:ab:cd:ef=10.0.2.15/24,10.0.2.2,10.0.2.3 hostname=sys-r1
   install=http://192.0.2.2/oss textmode=1 self_update=0 console=hvc0 ipv6.disable=1`; with
   `iso_chain.dns=` the `ifcfg` ends at `,10.0.2.2`. Add the rejections. Run and see red.
2. In `iso-chain-launch.sh`: `valid_opensuse_arguments` requires empty live-ISO, `.treeinfo`,
   `repomd`, and Kickstart variables, a `valid_path` repository, no newline in `routes` (one
   route), and no comma in `dns`. `opensuse_command_line` prints
   `ifcfg=$mac=$address,<gateway>${dns:+,$dns} hostname=$lpar install=$source$repository_path
   textmode=1 self_update=0 console=hvc0 ipv6.disable=1`. `launch_opensuse` makes the workspace
   (`umask 077`), downloads `kernel` then `initramfs` with `download_artifact`, prints
   `artifacts: passed`, and calls `execute_kexec "$(opensuse_command_line)"`. Add
   `opensuse:15.6)` to `parse_arguments` and `opensuse)` to `main`. Run and see green;
   `just check`; commit `feat: hand off to openSUSE linuxrc with a static ifcfg`.

## Task 4: Evidence

**Interfaces.** Consumes `_kernel_command_line`, `verify_launcher_log`, `_access_records`,
`_verify_http_requests`, `verify_installer_evidence`, `_external_artifacts`. Provides
`_opensuse_handoff(manifest, profile) -> list[str]` (the seven tokens `opensuse_command_line`
emits) and `OPENSUSE_PROBES`, the ten repository-relative 404 paths from the spec.

**Verification.**

- Console caller field. Mode: focused-test,
  `OpenSUSEEvidenceTests.test_accepts_kernel_caller_field`, plus
  `RockyEvidenceTests.test_rejects_kernel_caller_field` (a Rocky installer line with `[    T0]`
  still fails). Red: `console log requires one contiguous installer kernel command line`. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.OpenSUSEEvidenceTests
  tests.test_iso_chain.RockyEvidenceTests`.
- Launcher-log handoff and `IP addresses:`. Mode: focused-test,
  `OpenSUSEEvidenceTests.test_rejects_wrong_handoff`. Red: the `repo=` case not raising. Green: as
  above.
- `HEAD`, probes, pins, corroboration. Mode: focused-test, `OpenSUSEEvidenceTests.test_*http*`.
  Red: `access log method is invalid` on the `HEAD` record. Green: as above.
- `HEAD` still rejected for Rocky. Mode: focused-test,
  `RockyEvidenceTests.test_rejects_head_requests`. It pins existing behaviour, so it is green
  before and after the change. Green: `.venv/bin/python -m unittest
  tests.test_iso_chain.RockyEvidenceTests`.

**Steps.**

1. Write `OpenSUSEEvidenceTests` from `RockyEvidenceTests`' setUp with `opensuse_manifest_data()`,
   pins `(kernel, 6)` and `(initramfs, 9)`, later GETs `{base}/CHECKSUMS` (5) and
   `{base}/boot/ppc64le/root` (20), an installer line `[    1.000000][    T0] Kernel command
   line: ...` built from `_opensuse_handoff`, and `IP addresses:` followed by an indented
   `10.0.2.15`. Give `write_access_with_status` a method field. Cases:
   - Accepted: the base log; `HEAD {base}/repodata/repomd.xml` (200, 0 bytes) with all ten
     probes as 404.
   - HTTP rejections: another 404; a repeated probe; a 200 `autoinst.xml`; a later GET of the
     kernel; a path outside `{base}/`; probes as the only later traffic; a `HEAD` before the pins;
     a `HEAD` with status 404.
   - Handoff rejections: a wrong `ifcfg`; no `install=`; an added `repo=http://x/y`; an added
     `insecure=1`; an added `Self-Update=1`; a missing `IP addresses:` line; a different address
     after it.

   Add the Rocky `HEAD` case. Run and see red.
2. Implement:
   - `_kernel_command_line` gains `caller_field: bool = False`; when true its pattern is
     `\[\s*\d+\.\d+\](?:\[\s*[TC]\d+\])? Kernel command line: (.*)`. Only the installer
     call for an openSUSE profile passes `True`.
   - In `verify_launcher_log`, before the Fedora/Rocky branch, an openSUSE profile requires
     `[argument.replace('"', "") for argument in installer] == _opensuse_handoff(...)`, else
     `installer handoff evidence is missing, repeated, or different`. It also requires exactly one
     `IP addresses:` line after `kexec-exec: started`, with the next line equal to the manifest
     address's IP, else `installer network evidence is missing or different`.
   - `_access_records(encoded, allow_head=False)` accepts `HEAD` only when `allow_head`, only with
     status 200, and only with 0 bytes; `GET` keeps `bytes > 0`. `verify_installer_evidence`
     passes `allow_head=profile.distribution == "opensuse"`.
   - In `_verify_http_requests`, the top-level `probes` assignment gives openSUSE
     `tuple(f"{base}/{p}" for p in OPENSUSE_PROBES)`, so the existing `_reject_failed_requests`
     call applies them; every 404 must come after the second record. The openSUSE branch, before
     the Fedora/Rocky rule, requires the first two records to be the 200 GET pins at their sizes;
     rejects a later record naming a pin path, a probe path with status 200, or a path outside
     `{base}/`; and requires one later 200 GET (`HTTP evidence lacks post-kexec repository
     corroboration`).

   Run and see green; `just check`; commit `feat: verify openSUSE installer evidence`.

## Task 5: QEMU proof

**Interfaces.** Consumes every command above. Provides the experiment record and the measured
`minimum_memory_mib`.

**Verification.** Mode: task-test-not-applicable — the proof is the live run itself, judged by
`verify-installer-evidence`'s exit status and the operator-reviewed screens; the record is prose.

**Steps.**

1. Rebuild the launcher initramfs from this branch with `container-prepare-initramfs`.
2. In a fresh private directory (`umask 077`), run `prepare-opensuse-source` against the
   gpgv-checked `CHECKSUMS` and the partial tree with `--minimum-memory-mib 1024`, write a manifest
   with that profile, `source` `http://10.0.2.2:<port>`, one route, and DNS `10.0.2.3`; run
   `validate-external-source` against its own `serve-source` instance and access log; `build`.
3. Sweep QEMU arms at 6,144, 6,656, and 7,168 MiB, each with a fresh `serve-source` access log and
   capture; record each `MemTotal` and stop point, including `run-space: failed`. With no passing
   arm, stop and report. Otherwise regenerate the profile with the smallest passing arm's
   `MemTotal` rounded down to 256 MiB, rebuild, and run the acceptance arm fresh to Suggested
   Partitioning. Any linuxrc digest or signature dialog, or YaST signature or key warning, fails
   the run.
4. Run `verify-installer-evidence`; write `docs/experiments/2026-10-02-opensuse-installer.md`
   with the media, digests, signing key and its expiry, commands, results, RAM, external traffic,
   and boundary; put the measured value into README's example; `just check`; commit
   `docs: record the openSUSE installer QEMU proof`.
