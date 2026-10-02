# Ubuntu Installer Profile — Implementation Plan

**Goal:** a v4 manifest can select an Ubuntu 26.04.1 profile, and the launcher hands off to
Ubuntu's casper/subiquity installer over the manifest's static IPv4 settings, proven under QEMU
pSeries POWER9.

**Architecture:** The profile parser picks an exact field set by `distribution`. Ubuntu profiles pin
the netboot kernel and initrd and name the live ISO that casper downloads. `prepare-ubuntu-source`
derives those pins from the signed ISO. The launcher gains a distribution-specific argument set and
`launch_ubuntu`, which shares the download and kexec code with Fedora. The evidence verifiers and
the local server become distribution-neutral under generic names.

**Tech stack:** Python 3.14 stdlib (`scripts/iso_chain.py`), POSIX sh
(`assets/dracut/iso-chain-launch.sh`), `unittest`, the Bash launcher harness, QEMU 10.2.2.

Spec: `docs/workflow/specs/2026-10-02-ubuntu-installer-profile-design.md`. ADR 0012.

Expected implementation size: 650–900 changed lines (L) — derived from the file map: `iso_chain.py`
~220, launcher ~70, Python tests ~300, shell tests ~90, README/AGENTS ~110, and the experiment
record ~70.

## Global Constraints

- Python 3.14, stdlib only in `scripts/`. Annotate every function. Operator errors raise
  `ValidationError`, and messages never echo input values.
- ruff and rumdl line length is 100. Never edit generated output. Guardrails: run
  `just check-tests` after each task and `just check` before each commit. Both are about 5 s on this
  host.
- No DHCP, no IPv6, no redirects for launcher downloads, no alternate source, adapter, or profile.
- Launcher runs under the guest's C locale; the shell harness pins `LC_ALL=C`.
- `.secrets.baseline` records line numbers for some files. If `just check-secrets` fails after an
  edit, refresh only the recorded line numbers, never findings.
- Ubuntu constants: release `26.04.1`; ISO name `ubuntu-26.04.1-live-server-ppc64el.iso`;
  `.disk/info` starts with `Ubuntu-Server 26.04.1 LTS` plus a space, and contains
  `- Release ppc64el` surrounded by spaces.
- Conventional commits, one per task, on `feat/ubuntu-profile-8`.

## File map

| File | Today owns | Change |
|---|---|---|
| `scripts/iso_chain.py` | manifest, build, prepare, serve, verify, CLI | Ubuntu profile, prepare, handoff evidence, renames |
| `assets/dracut/iso-chain-launch.sh` | guest launcher (Fedora only) | per-distribution arguments, `launch_ubuntu`, shared `execute_kexec` |
| `tests/test_iso_chain.py` | Python behaviour | Ubuntu manifest, prepare, evidence; renamed commands |
| `tests/test_iso_chain_launch.sh` | launcher black box | Ubuntu command line, success and rejections |
| `README.md`, `AGENTS.md` | operator and agent docs | Ubuntu workflow, renamed commands, ADR count |
| `docs/experiments/2026-10-02-ubuntu-installer.md` (new) | — | public-safe proof record |

Renamed, no compatibility path (pre-release, operator decision 2026-10-02):
`serve-fedora-source`→`serve-source`, `verify-fedora-evidence`→`verify-installer-evidence`,
`FedoraRequestHandler`→`SourceRequestHandler`, `FedoraHTTPServer`→`SourceHTTPServer`,
`_fedora_server`→`_source_server`, `serve_fedora_source`→`serve_source`,
`verify_fedora_evidence`→`verify_installer_evidence`, `MAX_FEDORA_ISO_BYTES`→
`MAX_INSTALLER_ISO_BYTES`. Historical records under `docs/experiments/` and `docs/workflow/` keep
the old names. `install-fedora` and `verify-fedora-install-evidence` stay Fedora-only and reject a
non-Fedora profile.

## Task 1: Ubuntu profile in manifest v4

Files: modify `scripts/iso_chain.py` and `tests/test_iso_chain.py`.

**Interfaces.** Produces:

- `InstallerProfile` with fields `distribution, release, kernel, initramfs, repository:
  Repository | None, kickstart: Artifact | None, live_iso: Artifact | None, minimum_memory_mib`;
- `_external_artifacts(profile) -> tuple[Artifact, ...]`, which returns kernel, initramfs, and
  live ISO for Ubuntu;
- `_ubuntu_handoff(manifest: Manifest, profile: InstallerProfile) -> list[str]`;
- the constants `MAX_INSTALLER_ISO_BYTES` and `UBUNTU_ISO_NAME`.

Later tasks use all of these.

**Verification.**

- Contract: Ubuntu profile parsing (exact fields, `.iso` suffix, size bound, release message,
  network subset). Mode: focused-test. Case: `ManifestV4Tests.test_ubuntu_profile_*`. Red: an
  `AttributeError` or `ValidationError` "must be fedora/44". Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests`.
- Contract: Ubuntu kernel arguments, with Fedora's unchanged. Mode: focused-test. Case:
  `ManifestV4Tests.test_ubuntu_kernel_arguments_name_the_live_iso`. Green: the same command.
- Contract: `_ubuntu_handoff` values. Mode: focused-test. Case:
  `ManifestV4Tests.test_ubuntu_handoff_matches_the_static_network`. Green: the same command.
- Contract: `build` stages no Kickstart for Ubuntu. Mode: focused-test. Case:
  `BuildTests.test_ubuntu_manifest_stages_no_kickstart`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.

Steps:

1. Add the test factory beside `manifest_data`:

   ```python
   def ubuntu_profile():
       return {
           "distribution": "ubuntu",
           "release": "26.04.1",
           "kernel": {"path": "/ubuntu/netboot/ppc64el/linux", "size": 6, "sha256": "6" * 64},
           "initramfs": {
               "path": "/ubuntu/netboot/ppc64el/initrd",
               "size": 9,
               "sha256": "7" * 64,
           },
           "live_iso": {
               "path": "/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
               "size": 13,
               "sha256": "8" * 64,
           },
           "minimum_memory_mib": 4096,
       }


   def ubuntu_manifest_data(**changes):
       return manifest_data(
           profiles={"ubuntu": ubuntu_profile()}, selected_profile="ubuntu", **changes
       )
   ```

2. Add the `ManifestV4Tests` cases:
   - `test_ubuntu_profile_parses_exact_fields`: it loads `ubuntu_manifest_data()` and asserts
     `live_iso.path`, `repository is None`, and `kickstart is None`.
   - `test_ubuntu_profile_rejects_shape_and_release_without_echoing_input`: each of these raises
     `ValidationError` and the message excludes the bad value:
     - adding `"kickstart"`;
     - removing `"live_iso"`;
     - a path ending `.img`;
     - a size of `4 * 1024**3 + 1`;
     - release `"26.04"`;
     - distribution `"debian"` with the Fedora field set.
     The release case asserts `must be fedora/44 or ubuntu/26.04.1`.
   - `test_ubuntu_profile_requires_the_handoff_network_subset`: a second route
     `{"destination": "192.0.2.0/24", "gateway": "10.0.2.2"}`, and then three DNS servers, each
     raise `profiles.ubuntu: ubuntu handoff supports only the default route and at most two DNS
     servers`. A manifest with Fedora and Ubuntu profiles plus the extra route also raises.
   - `test_ubuntu_kernel_arguments_name_the_live_iso`: the arguments contain
     `iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso`, and contain
     no `profile_repository_path`, `profile_treeinfo`, `profile_repomd`, or `profile_kickstart`
     argument. The existing Fedora argument tests stay unchanged.
   - `test_ubuntu_handoff_matches_the_static_network`:

     ```python
     manifest = iso_chain.load_manifest_bytes(json.dumps(ubuntu_manifest_data()).encode())[0]
     self.assertEqual(
         iso_chain._ubuntu_handoff(manifest, manifest.profile("ubuntu")),
         [
             "ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off:10.0.2.3",
             "BOOTIF=01-52-54-00-12-34-56",
             "iso-url=http://10.0.2.2:8000/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
         ],
     )
     ```

     With `network.dns` set to `[]`, the first element is
     `ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off`.
3. Add `BuildTests.test_ubuntu_manifest_stages_no_kickstart`. It copies
   `test_build_stages_manifest_menu_and_publishes_once`'s setup with `ubuntu_manifest_data()` and
   an empty `--profiles` directory. It asserts that `grub2-mkrescue` ran and that the stage has no
   `profiles` directory.
4. Run `.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests
   tests.test_iso_chain.BuildTests`. Expected: the new cases fail.
5. Implement the following in `scripts/iso_chain.py`:
   - Rename `MAX_FEDORA_ISO_BYTES` to `MAX_INSTALLER_ISO_BYTES` at its definition, its use in
     `prepare_fedora_source`, and the test patch at `tests/test_iso_chain.py:2344`
     (`mock.patch.object(iso_chain, "MAX_FEDORA_ISO_BYTES", ...)`). Add `UBUNTU_ISO_NAME = "ubuntu-26.04.1-live-server-ppc64el.iso"`
     and `PROFILE_RELEASES = {"fedora": "44", "ubuntu": "26.04.1"}`.
   - Change `InstallerProfile` as described under **Interfaces**, keeping the field order
     `distribution, release, kernel, initramfs, repository, kickstart, live_iso,
     minimum_memory_mib`.
   - In `_installer_profile`, choose the field set before `_manifest_object`:

     ```python
     ubuntu = type(value) is dict and value.get("distribution") == "ubuntu"
     fields = (
         {"distribution", "release", "kernel", "initramfs", "live_iso", "minimum_memory_mib"}
         if ubuntu
         else {
             "distribution",
             "release",
             "kernel",
             "initramfs",
             "repository",
             "kickstart",
             "minimum_memory_mib",
         }
     )
     data = _manifest_object(value, fields, field)
     distribution = _string(data["distribution"], f"{field}.distribution")
     release = _string(data["release"], f"{field}.release")
     if PROFILE_RELEASES.get(distribution) != release:
         _manifest_error(f"{field}.distribution/release", "must be fedora/44 or ubuntu/26.04.1")
     kernel = _artifact(data["kernel"], f"{field}.kernel", 2 * 1024 * 1024 * 1024)
     initramfs = _artifact(data["initramfs"], f"{field}.initramfs", 2 * 1024 * 1024 * 1024)
     memory = _integer(data["minimum_memory_mib"], f"{field}.minimum_memory_mib", 1, 65536)
     if ubuntu:
         live_iso = _artifact(data["live_iso"], f"{field}.live_iso", MAX_INSTALLER_ISO_BYTES)
         if not live_iso.path.endswith(".iso"):
             _manifest_error(f"{field}.live_iso.path", "must end in .iso")
         return InstallerProfile(distribution, release, kernel, initramfs, None, None, live_iso, memory)
     ```

     The Fedora branch keeps today's repository and Kickstart code, and returns
     `InstallerProfile(distribution, release, kernel, initramfs, repository, kickstart, None,
     memory)`.
   - In `load_manifest_bytes`, skip profiles whose `kickstart is None` in the media loop. Compute
     `network = _validate_network(root["network"])` before building `Manifest`, then reject the
     Ubuntu network subset:

     ```python
     for name, profile in profiles:
         if profile.distribution == "ubuntu" and (
             [destination for destination, _ in network.routes] != ["0.0.0.0/0"] or len(network.dns) > 2
         ):
             _manifest_error(
                 f"profiles.{name}",
                 "ubuntu handoff supports only the default route and at most two DNS servers",
             )
     ```

     Pass `network=network` to `Manifest(...)`.
   - In `_manifest_data`, emit the Ubuntu dict for an Ubuntu profile: `distribution`, `release`,
     `kernel`, `initramfs`, `live_iso` (with path), and `minimum_memory_mib`. Fedora's dict is
     unchanged.
   - In `_kernel_arguments`, keep the common arguments through `profile_initramfs_sha256`. Then
     emit `[f"iso_chain.profile_live_iso_path={selected.live_iso.path}"]` for Ubuntu, or today's
     nine repository, `.treeinfo`, `repomd`, and Kickstart arguments for Fedora. Then emit
     `profile_minimum_memory_mib` and the rest unchanged.
   - In `_stage_profile_artifacts`, add `if profile.kickstart is None: continue` as the loop's first
     statement.
   - `_external_artifacts`: return `(profile.kernel, profile.initramfs, profile.live_iso)` when
     `profile.live_iso is not None`, otherwise today's tuple.
   - Add this after `_kernel_arguments`:

     ```python
     def _ubuntu_handoff(manifest: Manifest, profile: InstallerProfile) -> list[str]:
         """Return the casper arguments that iso-chain-launch.sh ubuntu_command_line emits."""
         interface = ipaddress.IPv4Interface(manifest.network.address)
         fields = [
             str(interface.ip),
             "",
             manifest.network.routes[0][1],
             str(interface.netmask),
             manifest.lpar,
             "",
             "off",
             *manifest.network.dns,
         ]
         return [
             "ip=" + ":".join(fields),
             "BOOTIF=01-" + manifest.network.mac.replace(":", "-"),
             f"iso-url={manifest.source}{profile.live_iso.path}",
         ]
     ```

6. Re-run the step 4 command. Expected: `OK`. Run `just check`. Expected: exit 0.
7. Commit: `feat: accept an Ubuntu 26.04.1 profile in manifest v4`.

Acceptance: every v4 Fedora test passes unchanged, and the Ubuntu cases pass.

## Task 2: Ubuntu handoff in the launcher

Files: modify `assets/dracut/iso-chain-launch.sh` and `tests/test_iso_chain_launch.sh`.

**Interfaces.** It consumes the Task 1 argument names
(`iso_chain.profile_distribution=ubuntu`, `iso_chain.profile_release=26.04.1`, and
`iso_chain.profile_live_iso_path=...`). It produces the console markers `artifacts: passed`,
`kexec-load: passed`, and `kexec-exec: started`, plus the casper arguments that `_ubuntu_handoff`
mirrors.

**Verification.**

- Contract: the Ubuntu argument set is accepted, and a mixed or invalid set is rejected. Mode:
  focused-test. Cases: the new Ubuntu blocks in `tests/test_iso_chain_launch.sh`. Red: `test
  failure: Ubuntu launch missed artifacts marker`. Green: `bash tests/test_iso_chain_launch.sh`
  prints `launcher shell tests: passed`.
- Contract: the Ubuntu kexec command line. Mode: focused-test. Same file and command.
- Contract: Fedora behaviour is unchanged. Mode: focused-test. Those are the existing harness
  blocks, unchanged.

Steps:

1. In the fake `curl`, add the cases `*/netboot/ppc64el/linux) content=kernel ;;` and
   `*/netboot/ppc64el/initrd) content=initramfs ;;`. Add this helper after `command_line`:

   ```bash
   ubuntu_command_line() {
       printf '%s' 'iso_chain.lpar=sys-r1 iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
       printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3,10.0.2.4 '
       printf '%s' 'iso_chain.source=http://192.0.2.2 iso_chain.profile=ubuntu '
       printf '%s' 'iso_chain.profile_distribution=ubuntu iso_chain.profile_release=26.04.1 '
       printf '%s' 'iso_chain.profile_kernel_path=/ubuntu/netboot/ppc64el/linux iso_chain.profile_kernel_size=6 '
       printf '%s' 'iso_chain.profile_kernel_sha256=6923dd1bc0460082c5d55a831908c24a282860b7f1cd6c2b79cf1bc8857c639c '
       printf '%s' 'iso_chain.profile_initramfs_path=/ubuntu/netboot/ppc64el/initrd iso_chain.profile_initramfs_size=9 '
       printf '%s' 'iso_chain.profile_initramfs_sha256=9752c38a9065f7646ffaac3621d1fa2f7dbe726c7e12e511eac7fdb14d4e2a24 '
       printf '%s' 'iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso '
       printf '%s' 'iso_chain.profile_minimum_memory_mib=4096 '
       printf '%s' "iso_chain.config_sha256=$config_digest"
   }
   ```

2. Append these blocks before the final `printf`:
   - **Success.** Run `run_launcher "eth0" "" 206 "$(ubuntu_command_line)"`. Assert:
     - `artifacts: passed`, `kexec-load: passed`, and `kexec-exec: started` are present;
     - `media: passed` is absent, and there is no `mount` call;
     - the curl URLs are exactly
       `http://192.0.2.2/ubuntu/netboot/ppc64el/linux http://192.0.2.2/ubuntu/netboot/ppc64el/initrd`;
     - the calls contain the literal
       `--command-line=ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off:10.0.2.3:10.0.2.4
       BOOTIF=01-52-54-00-ab-cd-ef
       iso-url=http://192.0.2.2/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso console=hvc0
       ipv6.disable=1` (one line);
     - the `dhcp|ipv6[^.]|--location` grep is empty.
   - **No DNS.** Replace `iso_chain.dns=10.0.2.3,10.0.2.4` with `iso_chain.dns=`. Assert that the
     calls contain `:sys-r1::off BOOTIF=01-`.
   - **Rejections.** Each case uses `assert_configuration_rejected` on the Ubuntu line with:
     - the live-ISO path removed;
     - the live-ISO path ending `.img`;
     - `iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg` appended;
     - `iso_chain.route=192.0.2.0/24,10.0.2.2` appended;
     - the DNS value `10.0.2.3,10.0.2.4,10.0.2.5`;
     - the release `44`.

     Separately, the Fedora `command_line` with
     `iso_chain.profile_live_iso_path=/ubuntu/x.iso` appended is also rejected.
   - **Faults.** For `digest` and `initramfs-digest` on the Ubuntu line, assert
     `launcher: failed` with the matching `kernel-digest: failed` or `initramfs-digest: failed`
     reason, and no `^kexec `.
3. Run `bash tests/test_iso_chain_launch.sh`. Expected: `test failure: ...` on the first Ubuntu
   assertion.
4. Implement the following in `assets/dracut/iso-chain-launch.sh`:
   - In `parse_arguments`, initialize `live_iso_path=''` and add the case
     `iso_chain.profile_live_iso_path=*)` with the same duplicate guard as the other cases.
   - Replace `[ "$distribution" = fedora ] && [ "$release" = 44 ] || return 1` and the
     repository, `.treeinfo`, `repomd`, and Kickstart validation lines with:

     ```sh
     case "$distribution:$release" in
     fedora:44) valid_fedora_arguments || return 1 ;;
     ubuntu:26.04.1) valid_ubuntu_arguments || return 1 ;;
     *) return 1 ;;
     esac
     ```

     Define these before `parse_arguments`:

     ```sh
     valid_fedora_arguments() {
         [ -z "$live_iso_path" ] && valid_path "$repository_path" || return 1
         valid_size "$treeinfo_size" && valid_sha256 "$treeinfo_digest" || return 1
         valid_size "$repomd_size" && valid_sha256 "$repomd_digest" || return 1
         valid_path "$kickstart_path" && valid_size "$kickstart_size" || return 1
         [ "$kickstart_size" -le 1048576 ] && valid_sha256 "$kickstart_digest"
     }

     valid_ubuntu_arguments() {
         [ -z "$repository_path$treeinfo_size$treeinfo_digest$repomd_size$repomd_digest" ] ||
             return 1
         [ -z "$kickstart_path$kickstart_size$kickstart_digest" ] || return 1
         valid_path "$live_iso_path" || return 1
         case "$live_iso_path" in *.iso) ;; *) return 1 ;; esac
         # casper's ip= carries one gateway and at most two DNS servers (ADR 0012).
         # Each route line ends in a newline, so a second newline means a second route.
         case "$routes" in *"
     "*"
     "*) return 1 ;; esac
         case "$dns" in *,*,*) return 1 ;; esac
     }
     ```

     The kernel and initramfs path, size, and digest checks stay common.
   - In `check_capacity`, set
     `download_bytes=$((executable_bytes + ${treeinfo_size:-0} + ${repomd_size:-0} + ${kickstart_size:-0}))`.
   - Extract the tail of `launch_fedora`, from `kexec -l` through `return 1`, into
     `execute_kexec`, which takes the command line as `$1`. `launch_fedora` ends with
     `arguments=$(fedora_command_line) || return 1` and then `execute_kexec "$arguments"`.
   - Add:

     ```sh
     ubuntu_command_line() {
         route=${routes%"
     "}
         dns_fields=
         [ -z "$dns" ] || dns_fields=:$(printf '%s' "$dns" | tr ',' ':')
         bootif=01-$(printf '%s' "$mac" | tr ':' '-')
         arguments="ip=${address%/*}::${route#*,}:$(netmask):$lpar::off$dns_fields"
         printf '%s\n' "$arguments BOOTIF=$bootif iso-url=$source$live_iso_path console=hvc0 ipv6.disable=1"
     }

     launch_ubuntu() {
         umask 077
         workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
         download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
         download_artifact initramfs \
             "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
         printf '%s\n' 'artifacts: passed'
         execute_kexec "$(ubuntu_command_line)"
     }
     ```

   - In `main`, replace `launch_fedora || fail 'launcher: failed'` with:

     ```sh
     case "$distribution" in
     ubuntu) launch_ubuntu ;;
     *) launch_fedora ;;
     esac || fail 'launcher: failed'
     ```

5. Run `bash tests/test_iso_chain_launch.sh`. Expected: `launcher shell tests: passed`. Run
   `just check`. Expected: exit 0.
6. Commit: `feat: hand off to Ubuntu casper with static ip= and BOOTIF`.

## Task 3: Prepare the Ubuntu source

Files: modify `scripts/iso_chain.py` and `tests/test_iso_chain.py`.

**Interfaces.** It consumes `_installer_profile`, `MAX_INSTALLER_ISO_BYTES`, and `UBUNTU_ISO_NAME`
from Task 1, and the existing `_copy_with_sha256(source, destination, size, label, *, exact)`,
`_bounded_file(path, label, maximum)`, `_artifact_data(path, url_path, maximum)`,
`_publish_directory(source, destination)`, `_regular_file`, `_path`, `_sha256`, `_url_path`,
and `_integer`. It produces `prepare_ubuntu_source(args: argparse.Namespace) -> None` and the
`prepare-ubuntu-source` parser.

**Verification.**

- Contract: digest-anchored extraction and a canonical profile. Mode: focused-test. Case:
  `UbuntuSourceTests.test_verifies_digest_then_extracts_and_writes_canonical_profile`. Red:
  `AttributeError: ... prepare_ubuntu_source`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuSourceTests`.
- Contract: refusals (wrong digest, wrong or oversized `.disk/info`, existing output) with nothing
  published. Mode: focused-test. Same class.
- Contract: parser shape. Mode: focused-test. Case:
  `UbuntuSourceTests.test_parser_exposes_complete_command_contract`.

Steps:

1. Add `class UbuntuSourceTests(unittest.TestCase)` after `FedoraSourceTests`, with:
   - `setUp`, which writes `self.iso` (`b"verified Ubuntu image"`), its digest, and
     `self.output = root / "source"`. It sets
     `self.members = {"/.disk/info": b'Ubuntu-Server 26.04.1 LTS "Resolute Raccoon" - Release
     ppc64el (20260826)\n', "/casper/vmlinux": b"kernel", "/casper/initrd": b"initramfs"}`.
   - `args(**changes)`, which returns a `SimpleNamespace` of `iso`, `iso_sha256`,
     `release_path="/ubuntu/releases/26.04.1/release"`, `minimum_memory_mib=4096`, and `output`.
   - `fake_run(command, **kwargs)`, which records the command and writes
     `self.members[command[6]]` to `Path(command[7])`. It returns `CompletedProcess(command, 0)`.
   - The success test asserts three commands of the shape
     `["xorriso", "-osirrox", "on", "-indev", <work copy, not self.iso>, "-extract", member,
     target]`, for the members `/.disk/info`, `/casper/vmlinux`, and `/casper/initrd`, in that
     order. It then asserts:
     - `profile.json` is canonical sorted compact JSON plus a newline;
     - it parses inside `manifest_data(profiles={"ubuntu": profile}, selected_profile="ubuntu")`;
     - the kernel is at `/ubuntu/releases/26.04.1/release/netboot/ppc64el/linux`, and the
       initramfs at `.../netboot/ppc64el/initrd`, both with the fake bytes' sizes and digests;
     - `live_iso` is at `.../ubuntu-26.04.1-live-server-ppc64el.iso` with the ISO's size and
       digest;
     - the output directory lists exactly `netboot` and `profile.json`, and
       `netboot/ppc64el/linux` and `netboot/ppc64el/initrd` hold the fake kernel and initrd bytes.
   - `test_wrong_digest_does_not_extract_or_publish` uses `iso_sha256="0"*64`. It expects a
     `ValidationError` matching `digest does not match`, no `xorriso` command, and no output.
   - `test_rejects_wrong_release_or_oversized_disk_info` covers `.disk/info` as
     `b"Ubuntu-Server 24.04.5 LTS ... - Release ppc64el ...\n"`, then the 26.04.1 prefix with
     ` - Release arm64 `, then `b"x" * 4097`. Each raises `ValidationError`, and the output does
     not exist.
   - `test_existing_output_is_refused_before_copy`: create the output, expect `already exists`,
     and assert no command ran.
   - `test_parser_exposes_complete_command_contract` parses `prepare-ubuntu-source` with all five
     options. The command and `minimum_memory_mib == 4096` match.
2. Run `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuSourceTests`. Expected:
   errors.
3. Implement the following:
   - Generalize two Fedora-specific labels:
     - `_artifact_data`'s label becomes `"prepared artifact"`.
     - `_publish_directory`'s `EEXIST` message becomes `"output appeared during source
       preparation"`.

     Run `rg -n 'prepared Fedora artifact|during Fedora source preparation' tests` and update any
     asserting test to the new text.
   - Add the following after `prepare_fedora_source`:

     ```python
     def prepare_ubuntu_source(args: argparse.Namespace) -> None:
         iso = _regular_file(Path(args.iso).absolute(), "Ubuntu ISO")
         expected_digest = _sha256(args.iso_sha256, "ISO digest")
         release_path = _url_path(args.release_path, "release path")
         memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
         output = Path(args.output).absolute()
         parent = _path(output.parent, "output parent", "directory")
         if os.path.lexists(output):
             raise ValidationError("Ubuntu source output already exists")
         with tempfile.TemporaryDirectory(prefix=".iso-chain-ubuntu-", dir=parent) as temporary:
             work = Path(temporary)
             verified_iso = work / "source.iso"
             copied = _copy_with_sha256(
                 iso, verified_iso, MAX_INSTALLER_ISO_BYTES, "Ubuntu ISO", exact=False
             )
             if copied != expected_digest:
                 raise ValidationError("Ubuntu ISO digest does not match")
             members = (
                 ("/.disk/info", "info"),
                 ("/casper/vmlinux", "kernel"),
                 ("/casper/initrd", "initramfs"),
             )
             for member, name in members:
                 subprocess.run(
                     [
                         "xorriso",
                         "-osirrox",
                         "on",
                         "-indev",
                         str(verified_iso),
                         "-extract",
                         member,
                         str(work / name),
                     ],
                     check=True,
                 )
             info = _bounded_file(work / "info", "Ubuntu .disk/info", MAX_DISK_INFO_BYTES)
             text = info.decode("utf-8", errors="replace")
             if not text.startswith("Ubuntu-Server 26.04.1 LTS ") or (" - Release ppc64el " not in text):
                 raise ValidationError("Ubuntu ISO is not the 26.04.1 ppc64el live server")
             netboot = f"{release_path}/netboot/ppc64el"
             profile = {
                 "distribution": "ubuntu",
                 "release": "26.04.1",
                 "kernel": _artifact_data(work / "kernel", f"{netboot}/linux", 2**31),
                 "initramfs": _artifact_data(work / "initramfs", f"{netboot}/initrd", 2**31),
                 "live_iso": {
                     "path": f"{release_path}/{UBUNTU_ISO_NAME}",
                     "size": verified_iso.stat().st_size,
                     "sha256": expected_digest,
                 },
                 "minimum_memory_mib": memory,
             }
             _installer_profile(profile, "profile")
             published = work / "tree"
             (published / "netboot/ppc64el").mkdir(parents=True)
             os.link(work / "kernel", published / "netboot/ppc64el/linux")
             os.link(work / "initramfs", published / "netboot/ppc64el/initrd")
             (published / "profile.json").write_bytes(
                 json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
             )
             _publish_directory(published, output)
     ```

     Add `MAX_DISK_INFO_BYTES = 4096` beside the other `MAX_*` constants.
   - Add the parser entry `prepare-ubuntu-source` with the required `--iso` (Path),
     `--iso-sha256`, `--release-path`, `--minimum-memory-mib` (int), and `--output` (Path).
     Dispatch in `main` with `elif args.command == "prepare-ubuntu-source":
     prepare_ubuntu_source(args)`.
4. Re-run the step 2 command. Expected: `OK`. Run `just check`. Expected: exit 0.
5. Commit: `feat: prepare Ubuntu profile pins from the signed ISO`.

## Task 4: Generic server and Ubuntu evidence

Files: modify `scripts/iso_chain.py` and `tests/test_iso_chain.py`.

**Interfaces.** It consumes `_ubuntu_handoff` and `_external_artifacts` from Task 1. It produces:

- `verify_installer_evidence(args) -> tuple[str, ...]`, which replaces `verify_fedora_evidence`;
- `serve_source(args)`, `_source_server(directory, bind, port, access_log)`,
  `SourceRequestHandler`, and `SourceHTTPServer`;
- the CLI names `serve-source` and `verify-installer-evidence`.

**Verification.**

- Contract: the renamed commands and parsers. Mode: focused-test. Cases:
  `SourceServerTests.test_parser_exposes_server_contract` (the class is renamed from
  `FedoraServerTests`) and `InstallerEvidenceTests.test_parser_exposes_complete_verifier_contract`
  (the class is renamed from `FedoraEvidenceTests`). Red: argparse `invalid choice`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.SourceServerTests
  tests.test_iso_chain.InstallerEvidenceTests`.
- Contract: the Ubuntu launcher-log handoff. Mode: focused-test. Cases in `UbuntuEvidenceTests`:
  accept, then `media: passed` not required, then a missing, repeated, quoted, or different
  `iso-url=`, `ip=`, or `BOOTIF=`, or a stray `url=` or `cloud-config-url=`, each rejected with
  `installer handoff evidence`. Green: `.venv/bin/python -m unittest -v
  tests.test_iso_chain.UbuntuEvidenceTests`.
- Contract: Ubuntu HTTP evidence is exactly three requests. Mode: focused-test. Cases in
  `UbuntuEvidenceTests`: the wrong order, an extra path, a wrong ISO size, and a missing ISO each
  raise `HTTP evidence must be exactly`.
- Contract: the access-log byte bound is 4 GiB. Mode: focused-test. Case:
  `UbuntuEvidenceTests.test_accepts_a_live_iso_larger_than_2_gib`, which records a live-ISO size of
  `3 * 1024**3` in both the manifest and the access record.
- Contract: Fedora-only commands refuse an Ubuntu profile. Mode: focused-test. Cases:
  `FedoraInstallEvidenceTests.test_rejects_a_non_fedora_profile` and
  `InstallTests.test_install_fedora_rejects_a_selected_ubuntu_profile` (with `run` not called).
- Contract: external validation of three artifacts. Mode: focused-test. Case:
  `ExternalSourceTests.test_validates_ubuntu_artifacts`, which serves the three files from the
  class's tree. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.ExternalSourceTests`.

Steps:

1. Tests:
   - Rename `FedoraServerTests` to `SourceServerTests` and `FedoraEvidenceTests` to
     `InstallerEvidenceTests`. Replace `_fedora_server`, `verify_fedora_evidence`,
     `"serve-fedora-source"`, and `"verify-fedora-evidence"` with the new names.
   - Add `UbuntuEvidenceTests`, whose `setUp` mirrors `InstallerEvidenceTests.setUp` with these
     changes:
     - the manifest is `ubuntu_manifest_data()`, and the profile is `"ubuntu"`;
     - the console omits `media: passed`, and its last line is
       `"[    0.000000] Kernel command line: " + " ".join(iso_chain._ubuntu_handoff(manifest,
       profile)) + " console=hvc0 ipv6.disable=1"`;
     - the access records are the kernel, initramfs, and live-ISO paths with bytes 6, 9, and 13.

     The accept test expects the Fedora tuple with its last line replaced by
     `"installer-network: operator-reviewed"`.
   - Add the two Fedora-only refusal tests.
2. Run the Task 4 green commands. Expected: failures and errors.
3. Implement the following:
   - Rename the symbols listed under **Interfaces**, plus their parser entries and `main`
     branches. Keep the arguments identical.
   - In `_access_records`, change the bytes bound to `MAX_INSTALLER_ISO_BYTES`.
   - In `verify_launcher_log`:

     ```python
     profile = manifest.profile(expected_profile)
     media = ("media: passed",) if profile.distribution == "fedora" else ()
     ```

     Iterate `(*media, "artifacts: passed", "kexec-load: passed", "kexec-exec: started")`. After
     parsing `installer`, for Ubuntu:

     ```python
     keys = ("ip", "BOOTIF", "url")
     handoff = [argument for argument in installer if argument.replace('"', "").split("=", 1)[0] in keys]
     if handoff != _ubuntu_handoff(manifest, profile):
         raise ValidationError("installer handoff evidence is missing, repeated, or different")
     ```

     Otherwise run the existing Kickstart check. Return the result tuple with `"media: passed"`
     only when `media` is non-empty.
   - In `_verify_http_requests`, add this first:

     ```python
     if profile.live_iso is not None:
         expected = [(artifact.path, artifact.size) for artifact in _external_artifacts(profile)]
         if [(record["path"], record["bytes"]) for record in records] != expected:
             raise ValidationError(
                 "HTTP evidence must be exactly the kernel, initramfs, and live ISO requests"
             )
         return
     ```

   - In `verify_installer_evidence`, make the last result line
     `"installer-network: operator-reviewed"` when `profile.distribution == "ubuntu"`, and
     `"intended-source: operator-reviewed"` otherwise.
   - In `verify_fedora_install_evidence`, right after `profile = manifest.profile(...)`, add
     `if profile.distribution != "fedora": raise ValidationError("installation evidence requires a
     Fedora profile")`. In `install_fedora`, right after `load_manifest`, add
     `if manifest.profile(manifest.selected_profile).distribution != "fedora": raise
     ValidationError("install-fedora requires a selected Fedora profile")`.
4. Re-run the green commands, then `just check`. Expected: `OK`, then exit 0.
5. Commit: `feat: verify Ubuntu installer evidence under generic command names`.

## Task 5: Operator documentation

Files: modify `README.md` and `AGENTS.md`.

**Verification.**

- Contract: documentation of the Ubuntu workflow and the renamed commands. Mode:
  task-test-not-applicable. Surface: prose for operators and agents. No executable consumer reads
  it; `just check-markdown` covers its form, and Task 6 follows its commands literally.

Steps:

1. Make these README changes:
   - Add an `Ubuntu 26.04.1 installer profile` section after the Fedora preparation section. It
     shows `gpgv` against `SHA256SUMS.gpg` with the Ubuntu CD signing key, then
     `prepare-ubuntu-source` with `--release-path /ubuntu/releases/26.04.1/release`, then a local
     tree laid out as
     `ubuntu/releases/26.04.1/release/{ubuntu-26.04.1-live-server-ppc64el.iso,netboot/ppc64el/linux,netboot/ppc64el/initrd}`
     served by `serve-source`.
   - State the network subset (default route only, at most two DNS servers), the unpinned
     live-ISO risk, and the measured minimum memory.
   - Replace `serve-fedora-source` and `verify-fedora-evidence` with the new names.
2. Make these AGENTS.md changes:
   - Profiles are `fedora`/`44` or `ubuntu`/`26.04.1`.
   - Add `prepare-ubuntu-source` to the stage list and the subcommand list, and rename the two
     commands.
   - The ADRs are "twelve accepted ... (0001–0012)".
   - Add `UbuntuSourceTests` and `UbuntuEvidenceTests` to the test class examples, and replace the
     stale `FedoraEvidenceTests` (line 213), `FedoraServerTests` (line 224), and
     `MAX_FEDORA_ISO_BYTES` (line 137) with `InstallerEvidenceTests`, `SourceServerTests`, and
     `MAX_INSTALLER_ISO_BYTES`.
3. Run `just check-markdown`. Expected: `Success: No issues found`. Then `just check`.
4. Commit: `docs: document the Ubuntu installer profile`.

## Task 6: QEMU POWER9 proof and experiment record

Files: create `docs/experiments/2026-10-02-ubuntu-installer.md`. Private evidence stays under the
operator's private directory, mode 0700, and is never committed.

**Verification.**

- Contract: an end-to-end handoff on the emulated target. Mode: focused-test. Observation:
  `verify-installer-evidence` on the run's record prints the ten result lines, ending
  `installer-network: operator-reviewed`. Red: any `error:` with exit 2.
- Contract: the experiment record's prose. Mode: task-test-not-applicable. It is a public-safe
  summary with no executable consumer, and the verifier output above is its evidence.

Steps:

1. Build the launcher kernel and initramfs:
   `scripts/iso_chain.py container-prepare-initramfs --output-dir PRIVATE/launcher`. If the
   emulated container is unavailable, run `prepare-initramfs` inside the `~/src/vm-ppc64le`
   Fedora 44 guest, and record which path ran.
2. Run `prepare-ubuntu-source --iso PRIVATE/ubuntu-26.04.1-live-server-ppc64el.iso --iso-sha256
   3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826 --release-path
   /ubuntu/releases/26.04.1/release --minimum-memory-mib 1024 --output PRIVATE/sweep-source`.
   Lay out `PRIVATE/www/ubuntu/releases/26.04.1/release/` with hard links to the operator's
   verified ISO and to `PRIVATE/sweep-source/netboot/ppc64el/{linux,initrd}`.
3. Write the manifest: `lpar`, the QEMU MAC `52:54:00:12:34:56`, `10.0.2.15/24`, the default route
   via `10.0.2.2`, DNS `10.0.2.3`, `source` `http://10.0.2.2:PORT`, and one `ubuntu` profile from
   `profile.json`. Write a host-side copy whose `source` is `http://127.0.0.1:PORT`. Start a
   throwaway `serve-source`, run `validate-external-source --config HOST-COPY --timeout-seconds
   300`, keep its JSON output for the record, and stop that server. Expected: three artifacts whose
   digests equal the pins. Build the ISO with `container-build --profiles PRIVATE/sweep-source`.
4. Sweep. For each QEMU arm of 4,096, 6,144, and 8,192 MiB, run a fresh `serve-source --directory
   PRIVATE/www --bind 127.0.0.1 --port PORT --access-log PRIVATE/arm-M/access.jsonl`, a fresh blank
   20 GiB qcow2, and `smoke --memory-mib M --capture-prefix PRIVATE/arm-M/capture`. Attach the
   console through `tmux` and `socat` to drive the screens. Record the launcher's `MemTotal` and
   the stop point: `profile-memory`, `available-memory`, `run-space`, a casper or subiquity failure,
   or guided storage. Decline any installer update. Stop the arm, then stop the server.
5. Take the smallest passing arm. Round its `MemTotal` down to a multiple of 256 MiB to get `N`.
   Regenerate with `--minimum-memory-mib N --output PRIVATE/ubuntu-source`, rewrite the manifest,
   and rebuild the ISO.
6. Run a fresh acceptance run at that arm, with a new server and access log, a new disk, and a new
   capture. A casper fetch retry makes the HTTP evidence fail; rerun the run fresh.
   - Record the disk SHA-256 before and after, and the guest `MemTotal`/`MemAvailable` from the
     launcher's memory line.
   - Filter the capture with `tcpdump -r CAPTURE -w FILTERED 'ip6 or udp port 67 or udp port
     68'`.
   - Write the record with `same_run_collection`, `installer_ready`, `intended_disk_visible`, and
     `intended_source_confirmed` set from the screens. `intended_source_confirmed` means the
     network screen showed `static` with the manifest's address.
   - Run `verify-installer-evidence`. Expected: the ten lines, exit 0.
7. Write the experiment record in the shape of `2026-09-09-fedora-installer.md`: Result, Inputs and
   environment (QEMU version, each arm's `-m`, `MemTotal`, and stop point, ISO and pin digests, the
   `validate-external-source` result, manifest digest), Evidence (verifier output; that the
   installer update was declined; whether the guest reached the ports archive), and Boundary (no
   native POWER9; under `-snapshot` the disk hash shows only that the backing file was untouched;
   public HTTPS mirror untested). It
   carries no MAC, IP, hostnames, or paths beyond the QEMU user-network defaults already public in
   tests.
8. Run `just check`. Expected: exit 0. Commit: `docs: record the Ubuntu installer QEMU proof`.

## Spec-to-task map

| Spec requirement | Task |
|---|---|
| Ubuntu profile fields, release message, network subset | 1 |
| Ubuntu kernel arguments; no Kickstart staging | 1 |
| Launcher argument sets, capacity, `launch_ubuntu`, command line | 2 |
| `prepare-ubuntu-source` | 3 |
| `serve-source`, `verify-installer-evidence`, launcher-log and HTTP evidence, byte bound, external validation, Fedora-only refusals | 4 |
| README/AGENTS | 5 |
| Proof, measured memory, experiment record | 6 |

## Deferrals

| Item | Owner |
|---|---|
| Native POWER9 PowerVM run of the Ubuntu profile | epic #1 (separately authorized live work) |
| casper over a public HTTPS mirror (BusyBox TLS) | epic #1 public-mirror goal |
