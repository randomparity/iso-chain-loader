# Rocky Installer Profile Implementation Plan

**Goal:** Add a `rocky`/`9.8` manifest v4 profile that boots Rocky Linux 9.8's interactive text
Anaconda over static IPv4, and prove it under QEMU pSeries POWER9.

**Architecture:** The Rocky profile is Fedora's Anaconda profile without a Kickstart
(ADR 0013). The Python parser, kernel arguments, preparation, and verifiers gain one more shape.
The launcher reuses the Anaconda path and skips the media when no Kickstart path is present.

**Tech stack:** Python 3.14, stdlib only; POSIX `sh` launcher; stdlib `unittest`; Bash shell test.

Expected implementation size: 220–300 changed lines (M) — about 70 Python, 30 shell, 100 Python
tests, 30 shell tests, and 30 docs lines, counted from the tasks below.

## Global Constraints

- Python 3.14, standard library only in `scripts/`; ruff line length 100.
- Every failure raises `ValidationError` naming fields, never values; validation runs before any
  subprocess (`run.assert_not_called()`).
- Fedora and Ubuntu manifests, kernel arguments, launcher output, and evidence stay byte-identical.
- Guardrails: `just check-tests` while iterating; `just check` before each commit. `.secrets.baseline`
  line numbers are refreshed when a covered file shifts (`just check-secrets` shows the drift).
- Spec: `docs/workflow/specs/2026-10-02-rocky-installer-profile-design.md`.

## File map

| File | Change |
|---|---|
| `scripts/iso_chain.py` | Rocky profile parsing, kernel arguments, treeinfo helper parameters, `prepare-rocky-source`, launcher-log handoff, HTTP prefixes |
| `assets/dracut/iso-chain-launch.sh` | `valid_rocky_arguments`; `launch_anaconda` and `anaconda_command_line` with optional Kickstart |
| `tests/test_iso_chain.py` | `rocky_profile()`, `rocky_manifest_data()`; cases in `ManifestV4Tests`, `BuildTests`, `InstallerEvidenceTests`; new `RockySourceTests` |
| `tests/test_iso_chain_launch.sh` | `rocky_command_line()` and Rocky cases |
| `README.md`, `AGENTS.md` | Rocky profile and `prepare-rocky-source` |
| `docs/experiments/2026-10-02-rocky-installer.md` | QEMU proof record |

No caller migration: Fedora's command names are unchanged. The internal shell functions
`launch_fedora` and `fedora_command_line` are renamed, and their only caller is `main`.

## Task 1: Manifest, kernel arguments, and evidence (Python)

**Interfaces.** Consumes `_installer_profile`, `_profile_source_arguments`, `_manifest_data`,
`verify_launcher_log`, `_access_records`, `_verify_http_requests`, and
`_verify_install_http_requests` in `scripts/iso_chain.py`. Provides `ROCKY_REPOSITORY_SUFFIX =
"/BaseOS/ppc64le/os"`, `PROFILE_RELEASES["rocky"] == "9.8"`, and the test factories
`rocky_profile()` and `rocky_manifest_data(**changes)`, which Tasks 2 and 3 use.

**Verification.**

- Rocky parsing (field set, stray `kickstart`, suffix, release message). Mode: focused-test, in
  `ManifestV4Tests.test_rocky_profile*`. Red: `profiles.rocky.distribution/release` error. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests`.
- Rocky kernel arguments omit the Kickstart, and `build` stages none. Mode: focused-test, in
  `ManifestV4Tests.test_rocky_kernel_arguments` and `BuildTests.test_rocky_profile_stages_no_kickstart`.
  Red: a `KeyError` or `AttributeError` on `kickstart`. Green: the same command plus
  `tests.test_iso_chain.BuildTests`.
- Launcher-log handoff, canonical round-trip, HTTP prefixes, and 404 probes. Mode: focused-test,
  in `InstallerEvidenceTests.test_rocky_*`. Red: an `AttributeError` from `_manifest_data` on the
  first Rocky log, then the access log's `failed or reordered requests` on a probe 404. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.InstallerEvidenceTests`.

**Steps.**

1. Add the factories beside `ubuntu_profile()`:

   ```python
   def rocky_profile():
       base = "/pub/rocky/9.8/BaseOS/ppc64le/os"
       return {
           "distribution": "rocky",
           "release": "9.8",
           "kernel": {"path": f"{base}/ppc/ppc64/vmlinuz", "size": 6, "sha256": "a" * 64},
           "initramfs": {"path": f"{base}/ppc/ppc64/initrd.img", "size": 9, "sha256": "b" * 64},
           "repository": {
               "path": base,
               "treeinfo": {"size": 10, "sha256": "c" * 64},
               "repomd": {"size": 11, "sha256": "d" * 64},
           },
           "minimum_memory_mib": 4096,
       }


   def rocky_manifest_data(**changes):
       return manifest_data(
           **{"profiles": {"rocky": rocky_profile()}, "selected_profile": "rocky", **changes}
       )
   ```

   Write failing tests for: acceptance; a `kickstart` key rejected; a `repository.path` of
   `/repository` rejected with `must end in /BaseOS/ppc64le/os`; `rocky`/`9` rejected with the
   new message; Rocky kernel arguments that contain `iso_chain.profile_repository_path=` and no
   `iso_chain.profile_kickstart`; Fedora and Ubuntu arguments unchanged (the existing tests);
   and `build` with a Rocky-only manifest writing no `profiles/` directory. Run them and see red.
2. In `scripts/iso_chain.py`, set `PROFILE_RELEASES = {"fedora": "44", "rocky": "9.8", "ubuntu":
   "26.04.1"}` and add `ROCKY_REPOSITORY_SUFFIX`. In `_installer_profile`, compute
   `specific = {"live_iso"} if ubuntu else {"repository"} if rocky else {"repository",
   "kickstart"}`, where `rocky = type(value) is dict and value.get("distribution") == "rocky"`.
   Change the release message to `must be fedora/44, rocky/9.8, or ubuntu/26.04.1`. After
   building `repository`, add:

   ```python
   if rocky:
       if not repository_path.endswith(ROCKY_REPOSITORY_SUFFIX):
           _manifest_error(f"{field}.repository.path", f"must end in {ROCKY_REPOSITORY_SUFFIX}")
       return InstallerProfile(
           distribution, release, kernel, initramfs, repository, None, None, memory
       )
   ```

   In `_profile_source_arguments`, append the three Kickstart arguments only when
   `profile.kickstart is not None`. `_stage_profile_artifacts` already skips `None`. Run and see
   green.
3. Write failing evidence tests. `installer_command_line` (`tests/test_iso_chain.py:453`) reads the
   `fedora` profile, so add a `rocky_installer_command_line(manifest, extra="")` helper. It returns
   `"[    1.000000] Kernel command line: inst.text rd.neednet=1 "
   f"inst.repo={manifest.source}{manifest.profile('rocky').repository.path}{extra} console=hvc0
   ipv6.disable=1"`. A Rocky log with `inst.repo=<source><path>` and no `inst.ks` passes. A stray
   `inst.ks=…`, a missing `inst.repo`, a second `inst.repo`, or a wrong value fails. An access log
   with a GET of
   `/pub/rocky/9.8/AppStream/ppc64le/os/repodata/repomd.xml` after the four pins passes, and
   `/pub/rocky/9.8/extras/x` fails. A 404 record for `<repository.path>/images/updates.img` or
   `…/product.img` (once each) passes for Rocky. The same 404 under a Fedora profile fails, as
   does a Rocky 404 on any other path or a repeated probe.
4. In `_manifest_data` (`scripts/iso_chain.py:601-609`), set `data["kickstart"]` only when
   `profile.kickstart is not None`, so the Rocky digest matches its canonical bytes. In
   `verify_launcher_log`, replace the Kickstart block's tail. Expect `[expected_kickstart]` when
   `profile.kickstart` is set and `[]` otherwise. When it is unset, also require
   `[a for a in installer if a.replace('"', "").split("=", 1)[0] == "inst.repo"] ==
   [f"inst.repo={manifest.source}{profile.repository.path}"]`. Raise the existing messages, or
   `installer repository evidence is missing, repeated, or different`. In `_verify_http_requests`,
   build `prefixes = (profile.repository.path + "/",)` and add
   `profile.repository.path.removesuffix(ROCKY_REPOSITORY_SUFFIX) + "/AppStream/ppc64le/os/"` for
   Rocky. Use `path.startswith(prefixes)` in both repository checks. In `_access_records`, accept
   `status in (200, 404)` instead of `status != 200`. Add
   `_reject_failed_requests(records, allowed: tuple[str, ...]) -> None`, which raises
   `access log contains failed or reordered requests` when any 404 record's path is not in
   `allowed` or an allowed path's 404 repeats. Call it first in `_verify_http_requests`, with
   `(f"{path}/images/updates.img", f"{path}/images/product.img")` for Rocky and `()` otherwise.
   Call it with `()` in `_verify_install_http_requests`. Exclude the 404 records from the
   remaining checks there. Run and see green, then run `just check`.
5. Commit: `feat: accept the Rocky 9.8 installer profile`.

## Task 2: `prepare-rocky-source`

**Interfaces.** Consumes `_treeinfo_images(tree, iso_digest)`, `_copy_with_sha256`,
`_artifact_data`, `_publish_directory`, and `_installer_profile`. Changes the helper's signature
to `_treeinfo_images(tree: Path, iso_digest: str, label: str, identity: tuple[str, str, str],
variants: tuple[str, ...]) -> tuple[tuple[str, str], ...]`. Extracts
`_extract_treeinfo_images(iso, expected_digest, images, repository_path, work, label) ->
list[dict[str, object]]` from `prepare_fedora_source`. Adds `prepare_rocky_source(args)`.

**Verification.**

- Rocky preparation. Mode: focused-test, in the new `RockySourceTests` (fake `xorriso` copied from
  `FedoraSourceTests`): success, digest mismatch, wrong `.treeinfo` identity, wrong or missing
  AppStream repository, bad path suffix, existing output, and `run.assert_not_called()` on each argument
  error. Red: `prepare-rocky-source` is an invalid choice. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.RockySourceTests tests.test_iso_chain.FedoraSourceTests`.

**Steps.**

1. Write `RockySourceTests` from `FedoraSourceTests`' helpers, with a treeinfo whose `[general]`
   is `family = Rocky Linux`, `version = 9.8`, `arch = ppc64le`, `variant = BaseOS`, plus
   `[variant-AppStream] repository = ../../../AppStream/ppc64le/os/`. Run and see red.
2. Parameterize `_treeinfo_images`, replacing the literal `Fedora treeinfo` with `label`. Fedora's
   caller passes `("Fedora treeinfo", ("Fedora", "44", "ppc64le"), FEDORA_VARIANTS)`, so its
   messages are unchanged. Move the copy, extract, and match loop into
   `_extract_treeinfo_images`, and have `prepare_fedora_source` call it.
3. Add `prepare_rocky_source`. It validates the arguments, including `ROCKY_REPOSITORY_SUFFIX`
   (`repository path: must end in /BaseOS/ppc64le/os`). It calls the helper with
   `("Rocky treeinfo", ("Rocky Linux", "9.8", "ppc64le"), ("BaseOS",))`. It then re-reads the
   bounded `.treeinfo` and requires
   `parser.get("variant-AppStream", "repository", fallback=None)` to be in
   `("../../../AppStream/ppc64le/os", "../../../AppStream/ppc64le/os/")`, catching
   `configparser.Error`, or it raises `Rocky treeinfo: AppStream is not the sibling repository`.
   Finally it extracts,
   builds the `rocky` profile with no `kickstart`, validates it with `_installer_profile`, writes
   `profile.json`, and publishes. Register the subparser with Fedora's arguments minus
   `--kickstart`, and dispatch it in `main()`. Run and see green, then run `just check`.
4. Commit: `feat: prepare a Rocky source from the signed boot ISO`.

## Task 3: Launcher

**Interfaces.** Consumes `parse_arguments`, `valid_fedora_arguments`, `launch_fedora`, and
`fedora_command_line` in `assets/dracut/iso-chain-launch.sh`. Provides `valid_rocky_arguments`,
`launch_anaconda`, and `anaconda_command_line`.

**Verification.**

- The Rocky handoff. Mode: focused-test, in `tests/test_iso_chain_launch.sh` with a new
  `rocky_command_line()` (Fedora's line with Rocky paths and no Kickstart arguments). It asserts
  four curl requests in order, no `mount` call, no `media:` line, and kexec arguments ending
  `ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1:iso0:none nameserver=10.0.2.3 nameserver=10.0.2.4
  inst.repo=http://192.0.2.2/pub/rocky/9.8/BaseOS/ppc64le/os console=hvc0 ipv6.disable=1`. It
  also asserts that a Kickstart argument, a live-ISO argument, and the path `/repository` each
  fail configuration, and that `digest` fails with `kernel-digest: failed`. Red: `configuration:
  failed` for the valid line. Green: `bash tests/test_iso_chain_launch.sh` prints `launcher shell
  tests: passed`.

**Steps.**

1. Add the tests and see red.
2. Add:

   ```sh
   valid_rocky_arguments() {
       [ -z "$live_iso_path$kickstart_path$kickstart_size$kickstart_digest" ] || return 1
       valid_path "$repository_path" || return 1
       case "$repository_path" in */BaseOS/ppc64le/os) ;; *) return 1 ;; esac
       valid_size "$treeinfo_size" && valid_sha256 "$treeinfo_digest" || return 1
       valid_size "$repomd_size" && valid_sha256 "$repomd_digest"
   }
   ```

   Add `rocky:9.8) valid_rocky_arguments || return 1 ;;` to the distribution `case`. Rename the
   two functions, keeping `main`'s `*) launch_anaconda ;;`. In `launch_anaconda`, wrap the media
   lines (from `find_media` through `media_mounted=`) in `if [ -n "$kickstart_path" ]; then …
   fi`. In `anaconda_command_line`, emit the `inst.ks=` fragment only when `kickstart_path` is
   non-empty. Run and see green, then run `just check`.
3. Commit: `feat: hand off to Rocky Anaconda without a Kickstart`.

## Task 4: Documentation and QEMU proof

**Verification.** Docs. Mode: task-test-not-applicable, because prose has no executable consumer.
`just check-markdown` gates its form. The live proof is the spec's Proof section. Its pass is
`verify-installer-evidence` printing the ten result lines, ending in `intended-source:
operator-reviewed`.

**Steps.**

1. Document `rocky`/`9.8` and `prepare-rocky-source` in `README.md`'s worked sequence and in
   `AGENTS.md`'s overview, stages, ADR count (thirteen), and test-class list (eighteen classes,
   adding `RockySourceTests`). State that `prepare-rocky-source` needs `xorriso`, and give the
   `iso-chain-builder:44` container form README already shows for `prepare-fedora-source`.
2. Rebuild the launcher initramfs from this commit. Build with `minimum_memory_mib` 1024, run the
   RAM sweep (start at 3,072, 4,096, and 6,144 MiB, and add arms to bracket the floor), then
   regenerate the profile and do a fresh acceptance run. Keep raw evidence under
   `~/iso-chain-private/rocky-9.8/`.
3. Write `docs/experiments/2026-10-02-rocky-installer.md` in the Ubuntu record's format, and
   refresh `.secrets.baseline` if `just check-secrets` reports drift. Run `just check` and commit:
   `docs: record the Rocky installer QEMU proof`.
