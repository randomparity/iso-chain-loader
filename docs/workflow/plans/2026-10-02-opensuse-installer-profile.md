# openSUSE Installer Profile Implementation Plan

**Goal:** Add an `opensuse`/`15.6` manifest v4 profile that boots openSUSE Leap 15.6's linuxrc and
YaST text installer over static IPv4, and prove it under QEMU pSeries POWER9.

**Architecture:** The profile pins the repository's kernel and initrd, anchored on the signed
repository `CHECKSUMS` (ADR 0014). The Python parser, kernel arguments, preparation, and verifiers
gain one more shape. The launcher gains a two-download linuxrc handoff beside the Ubuntu one.

**Tech stack:** Python 3.14, stdlib only; POSIX `sh` launcher; stdlib `unittest`; Bash shell test.

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
| `scripts/iso_chain.py` | openSUSE parsing and network subset, kernel arguments, `_manifest_data`, `prepare-opensuse-source`, launcher-log handoff, `HEAD`-aware access log, openSUSE HTTP rule |
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
`opensuse_profile()` and `opensuse_manifest_data(**changes)` used by Tasks 2–4.

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

1. Add factories beside `rocky_profile()`:

   ```python
   def opensuse_profile():
       base = "/distribution/leap/15.6/repo/oss"
       return {
           "distribution": "opensuse",
           "release": "15.6",
           "kernel": {"path": f"{base}/boot/ppc64le/linux", "size": 6, "sha256": "a" * 64},
           "initramfs": {"path": f"{base}/boot/ppc64le/initrd", "size": 9, "sha256": "b" * 64},
           "repository": {"path": base},
           "minimum_memory_mib": 4096,
       }


   def opensuse_manifest_data(**changes):
       network = {
           "mac": "52:54:00:12:34:56",
           "address": "10.0.2.15/24",
           "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
           "dns": ["10.0.2.3"],
       }
       return manifest_data(
           **{
               "network": network,
               "profiles": {"opensuse": opensuse_profile()},
               "selected_profile": "opensuse",
               **changes,
           }
       )
   ```

   Check `manifest_data()`'s network first and reuse it if it already meets the subset. Write
   failing tests: acceptance; `repository` with a `treeinfo` key rejected; `opensuse`/`15.5`
   rejected with the four-pair message; a second route and a second DNS server each rejected with
   `opensuse handoff supports only the default route and at most one DNS server`; kernel arguments
   that contain `iso_chain.profile_repository_path=` and none of `profile_treeinfo`,
   `profile_repomd`, `profile_kickstart`, `profile_live_iso`; `_manifest_data` digest equal to
   `load_manifest_bytes`'s; `build` writing no `profiles/` directory. Run and see red.
2. In `scripts/iso_chain.py`: `PROFILE_RELEASES` gains `"opensuse": "15.6"`;
   `Repository.treeinfo: Artifact | None` and `repomd: Artifact | None`. In `_installer_profile`,
   `opensuse = distribution_value == "opensuse"`, `specific = {"repository"}` for it, the message
   becomes `must be fedora/44, opensuse/15.6, rocky/9.8, or ubuntu/26.04.1`, and before the
   Fedora/Rocky repository parse:

   ```python
   if opensuse:
       repository_data = _manifest_object(data["repository"], {"path"}, f"{field}.repository")
       repository = Repository(
           _url_path(repository_data["path"], f"{field}.repository.path"), None, None
       )
       return InstallerProfile(
           distribution, release, kernel, initramfs, repository, None, None, memory
       )
   ```

   In `load_manifest_bytes`, beside the Ubuntu subset:

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

   `_profile_source_arguments` returns `[f"iso_chain.profile_repository_path={path}"]` when
   `profile.repository.treeinfo is None`. `_manifest_data` emits `{"path": ...}` only in that case.
   `_external_artifacts` returns `(kernel, initramfs)` in that case. Run and see green; commit
   `feat: accept the openSUSE Leap 15.6 installer profile`.

## Task 2: `prepare-opensuse-source`

**Interfaces.** Consumes `_regular_file`, `_path`, `_url_path`, `_integer`, `_bounded_file`,
`_file_sha256`, `_artifact_data`, `_installer_profile`, `_publish_directory`. Provides
`prepare_opensuse_source(args: argparse.Namespace) -> None` and the parser entry with
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

1. Write `OpenSUSESourceTests`: a tree with `media.1/products` = `b"/ openSUSE-Leap 15.6-1\n"`,
   `boot/ppc64le/linux` = `b"kernel"`, `boot/ppc64le/initrd` = `b"initramfs"`, and a `CHECKSUMS`
   built from their digests plus one unrelated line. Cases: the published `profile.json` equals
   the expected `opensuse` profile (sizes 6 and 9) and loads through `_installer_profile`;
   rejections for a line with one space, an upper-case digest, a repeated path, a missing
   `boot/ppc64le/initrd` entry, a `CHECKSUMS` over 1 MiB, a modified kernel, a `products` of
   `/ openSUSE-Leap 15.5-1\n` (with its entry updated), and an existing output; each rejection
   leaves `OUT` absent. Run and see red.
2. Implement:

   ```python
   OPENSUSE_PRODUCTS = b"/ openSUSE-Leap 15.6-1\n"


   def _opensuse_checksums(path: Path) -> dict[str, str]:
       encoded = _bounded_file(path, "openSUSE CHECKSUMS", 1024 * 1024)
       entries: dict[str, str] = {}
       for line in encoded.decode("utf-8", errors="replace").splitlines():
           if not line:
               continue
           match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
           if match is None or match.group(2) in entries:
               raise ValidationError("openSUSE CHECKSUMS: malformed or repeated entry")
           entries[match.group(2)] = match.group(1)
       required = ("boot/ppc64le/linux", "boot/ppc64le/initrd", "media.1/products")
       if any(name not in entries for name in required):
           raise ValidationError("openSUSE CHECKSUMS: missing a boot or product entry")
       return entries


   def prepare_opensuse_source(args: argparse.Namespace) -> None:
       checksums = _regular_file(Path(args.checksums).absolute(), "openSUSE CHECKSUMS")
       tree = _path(Path(args.tree).absolute(), "openSUSE tree", "directory")
       repository_path = _url_path(args.repository_path, "repository path")
       memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
       output = Path(args.output).absolute()
       parent = _path(output.parent, "output parent", "directory")
       if os.path.lexists(output):
           raise ValidationError("openSUSE source output already exists")
       entries = _opensuse_checksums(checksums)
       products = _bounded_file(tree / "media.1/products", "openSUSE tree", 4096)
       if (
           hashlib.sha256(products).hexdigest() != entries["media.1/products"]
           or products != OPENSUSE_PRODUCTS
       ):
           raise ValidationError("openSUSE tree: not the Leap 15.6 repository")
       pins = {}
       for name, field in (("linux", "kernel"), ("initrd", "initramfs")):
           relative = f"boot/ppc64le/{name}"
           data = _artifact_data(tree / relative, f"{repository_path}/{relative}", 2**31)
           if data["sha256"] != entries[relative]:
               raise ValidationError(f"openSUSE tree: {name} does not match CHECKSUMS")
           pins[field] = data
       profile = {
           "distribution": "opensuse",
           "release": "15.6",
           **pins,
           "repository": {"path": repository_path},
           "minimum_memory_mib": memory,
       }
       _installer_profile(profile, "profile")
       with tempfile.TemporaryDirectory(prefix=".iso-chain-opensuse-", dir=parent) as temporary:
           published = Path(temporary) / "tree"
           published.mkdir()
           (published / "profile.json").write_bytes(
               json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
           )
           _publish_directory(published, output)
   ```

   Register the subparser beside `prepare-rocky-source` and its dispatch in `main()`. Add a README
   section after the Rocky one with the `gpgv` sequence (`gpg --dearmor` of
   `gpg-pubkey-29b700a4-62b07e22.asc`, `gpgv --keyring ... CHECKSUMS.asc CHECKSUMS`), the served
   tree's required files, and the command; add the command to `AGENTS.md`'s lists. Run and see
   green; `just check`; commit `feat: prepare an openSUSE source from the signed CHECKSUMS`.

## Task 3: Launcher handoff

**Interfaces.** Consumes `parse_arguments`, `download_artifact`, `execute_kexec`, `routes`, `dns`,
`address`, `mac`, `lpar`, `source`, `repository_path`. Provides `opensuse_command_line` whose output
Task 4's `_opensuse_handoff` must match byte for byte.

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
   `opensuse`, distribution `opensuse`, release `15.6`, kernel
   `/oss/boot/ppc64le/linux` size 6, initramfs `/oss/boot/ppc64le/initrd` size 9, repository
   `/oss`, one route, `iso_chain.dns=10.0.2.3`. Assert the calls file holds the two downloads,
   no `mount`, and ends in `--command-line=ifcfg=52:54:00:ab:cd:ef=10.0.2.15/24,10.0.2.2,10.0.2.3
   hostname=sys-r1 install=http://192.0.2.2/oss textmode=1 self_update=0 console=hvc0
   ipv6.disable=1`; with `iso_chain.dns=` the `ifcfg` ends at `,10.0.2.2`. Add the rejections.
   Run and see red.
2. In `iso-chain-launch.sh`:

   ```sh
   valid_opensuse_arguments() {
       [ -z "$live_iso_path$treeinfo_size$treeinfo_digest$repomd_size$repomd_digest" ] || return 1
       [ -z "$kickstart_path$kickstart_size$kickstart_digest" ] || return 1
       valid_path "$repository_path" || return 1
       # linuxrc's ifcfg= carries one gateway and a space-separated DNS field (ADR 0014).
       case "$routes" in *"
   "*"
   "*) return 1 ;; esac
       case "$dns" in *,*) return 1 ;; esac
   }

   opensuse_command_line() {
       route=${routes%"
   "}
       arguments="ifcfg=$mac=$address,${route#*,}${dns:+,$dns} hostname=$lpar"
       arguments="$arguments install=$source$repository_path textmode=1 self_update=0"
       printf '%s\n' "$arguments console=hvc0 ipv6.disable=1"
   }

   launch_opensuse() {
       umask 077
       workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
       download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
       download_artifact initramfs \
           "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
       printf '%s\n' 'artifacts: passed'
       execute_kexec "$(opensuse_command_line)"
   }
   ```

   Add `opensuse:15.6) valid_opensuse_arguments || return 1 ;;` to `parse_arguments` and
   `opensuse) launch_opensuse ;;` to `main`. Run and see green; `just check`; commit
   `feat: hand off to openSUSE linuxrc with a static ifcfg`.

## Task 4: Evidence

**Interfaces.** Consumes `verify_launcher_log`, `_access_records`, `_verify_http_requests`,
`verify_installer_evidence`, `_external_artifacts`. Provides `_opensuse_handoff(manifest,
profile) -> list[str]` and `OPENSUSE_PROBES`, a tuple of the ten repository-relative 404 paths.

**Verification.**

- Launcher-log handoff. Mode: focused-test, `OpenSUSEEvidenceTests.test_rejects_wrong_handoff`.
  Red: the stray-`autoyast` case not raising. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.OpenSUSEEvidenceTests`.
- `HEAD`, probes, prefixes, corroboration. Mode: focused-test, `OpenSUSEEvidenceTests.test_*http*`.
  Red: `access log method is invalid` on the `HEAD` record. Green: as above.
- `HEAD` still rejected for Rocky. Mode: focused-test,
  `RockyEvidenceTests.test_rejects_head_requests`. Red: none expected before the change (it
  pins the existing behaviour); after the change it must still raise `access log method is
  invalid`. Green: `.venv/bin/python -m unittest tests.test_iso_chain.RockyEvidenceTests`.

**Steps.**

1. Write `OpenSUSEEvidenceTests` from `RockyEvidenceTests`' setUp with `opensuse_manifest_data()`,
   pins `(kernel, 6)` and `(initramfs, 9)`, later GETs `{base}/CHECKSUMS` (5) and
   `{base}/boot/ppc64le/root` (20), and an installer line built from `_opensuse_handoff`. Give
   `write_access_with_status` a method field. Cases: acceptance; acceptance with `HEAD
   {base}/repodata/repomd.xml` (status 200, bytes 0) and all ten probes as 404; rejection of
   another 404, a repeated probe, a path outside `{base}/`, probes as the only later traffic, a
   `HEAD` before the pins; handoff rejections for a wrong `ifcfg`, no `install=`, a repeated
   `install=`, a stray `AutoYaST=http://x/a.xml`, and a stray `netsetup=dhcp`. Add the Rocky
   `HEAD` case. Run and see red.
2. Implement:

   ```python
   OPENSUSE_PROBES = (
       "content",
       "boot/ppc64le/yast2-trans-en_US.rpm",
       "license.tar.gz",
       "media.1/info.txt",
       "part.info",
       "README.BETA",
       "autoinst.xml",
       "driverupdate",
       "add_on_products.xml",
       "add_on_products",
   )


   def _opensuse_handoff(manifest: Manifest, profile: InstallerProfile) -> list[str]:
       """Return the linuxrc arguments that iso-chain-launch.sh opensuse_command_line emits."""
       network = manifest.network
       fields = [network.address, network.routes[0][1], *network.dns]
       return [
           f"ifcfg={network.mac}=" + ",".join(fields),
           f"hostname={manifest.lpar}",
           f"install={manifest.source}{profile.repository.path}",
           "self_update=0",
       ]
   ```

   In `verify_launcher_log`, before the Fedora/Rocky branch:

   ```python
   if profile.distribution == "opensuse":
       keys = (
           "ifcfg",
           "install",
           "hostname",
           "self_update",
           "autoyast",
           "autoyast2",
           "netsetup",
           "info",
       )
       handoff = [
           argument.replace('"', "")
           for argument in installer
           # linuxrc reads option names without regard to case.
           if argument.replace('"', "").split("=", 1)[0].lower() in keys
       ]
       if handoff != _opensuse_handoff(manifest, profile):
           raise ValidationError("installer handoff evidence is missing, repeated, or different")
       return _launcher_results(media)
   ```

   `_access_records(encoded, allow_head=False)`: accept `method == "HEAD"` only when `allow_head`,
   and allow `bytes == 0` only for `HEAD`. `verify_installer_evidence` passes
   `allow_head=profile.distribution == "opensuse"`. In `_verify_http_requests`, add an openSUSE
   branch before the Fedora/Rocky rule:

   ```python
   if profile.distribution == "opensuse":
       base = profile.repository.path
       _reject_failed_requests(records, tuple(f"{base}/{probe}" for probe in OPENSUSE_PROBES))
       found = [(r["method"], r["path"], r["bytes"]) for r in records if r["status"] == 200]
       pins = [("GET", path, size) for path, size in launcher_artifacts]
       if found[:2] != pins:
           raise ValidationError("HTTP evidence has invalid launcher request order")
       later = found[2:]
       if any(not path.startswith(base + "/") for _, path, _ in later):
           raise ValidationError("HTTP evidence contains a path outside the selected profile")
       if not any(method == "GET" for method, _, _ in later):
           raise ValidationError("HTTP evidence lacks post-kexec repository corroboration")
       return
   ```

   A probe 404 that precedes the pins is caught by `_reject_failed_requests`' allowance only, so add
   a check that every 404's index is after the second pin. Run and see green; `just check`; commit
   `feat: verify openSUSE installer evidence`.

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
   `validate-external-source` against `serve-source`; `build`.
3. Sweep QEMU arms at 2,048, 3,072, and 4,096 MiB; record each `MemTotal` and stop point.
   Regenerate the profile with the smallest passing arm's `MemTotal` rounded down to 256 MiB,
   rebuild, and run the acceptance arm fresh to Suggested Partitioning.
4. Run `verify-installer-evidence`; write `docs/experiments/2026-10-02-opensuse-installer.md`
   with the media, digests, signing key, commands, results, RAM, external traffic, and boundary;
   put the measured value into README's example; `just check`; commit
   `docs: record the openSUSE installer QEMU proof`.
