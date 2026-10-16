# RHEL Installer Profiles Implementation Plan

**Goal:** Add `rhel` manifest v4 profiles for RHEL 9.0 to 9.8 and 10.0 to 10.2 that boot the
interactive text Anaconda over static IPv4 with BaseOS and AppStream, and prove the newest 9.x and
10.x releases on a POWER9 partition.

**Architecture:** The `rhel` profile is Rocky's Anaconda profile plus an explicit AppStream
repository argument (ADR 0028). The Python parser, kernel arguments, preparation, and verifiers gain
one more shape; the launcher reuses `launch_anaconda`.

**Tech stack:** Python 3.14, stdlib only; POSIX `sh` launcher; stdlib `unittest`; Bash shell test.

Expected implementation size: 450–650 changed lines (L) — about 110 Python, 25 shell, 280 Python
tests, 50 shell tests, and 120 docs lines, counted from the tasks below.

## Global Constraints

- Python 3.14, standard library only in `scripts/`; ruff line length 100.
- Every failure raises `ValidationError` naming fields, never values; validation runs before any
  subprocess (`run.assert_not_called()`).
- Fedora, Rocky, openSUSE, and Ubuntu manifests, kernel arguments, launcher output, and evidence stay
  byte-identical.
- No file, test, or message names the operator's mirror; examples use `<REDACTED-FTP-MIRROR>` or
  `example.invalid`, and the credential never appears.
- Guardrails: `just check-tests` while iterating; `just check` before each commit. Refresh
  `.secrets.baseline` line numbers when a covered file shifts (`just check-secrets` shows the drift).
- Spec: `docs/workflow/specs/2026-10-15-rhel-profiles-design.md`.

## File map

| File | Change |
|---|---|
| `scripts/iso_chain.py` | `PROFILE_RELEASES` tuples, `RHEL_RELEASES`, `rhel` in `_installer_profile`, kernel arguments, `prepare_rhel_source`, parser entry, launcher-log handoff, HTTP prefixes and probes |
| `assets/dracut/iso-chain-launch.sh` | `valid_rhel_arguments`, the `rhel:` cases, `inst.addrepo` in `anaconda_command_line` |
| `tests/test_iso_chain.py` | `rhel_profile()`, `rhel_manifest_data()`; cases in `ManifestV4Tests`, `BuildTests`, `InstallerEvidenceTests`; new `RHELSourceTests`, `RHELEvidenceTests`, `FTPRHELEvidenceTests` |
| `tests/test_iso_chain_launch.sh` | `rhel_command_line()` and RHEL cases |
| `README.md`, `AGENTS.md` | the profile and `prepare-rhel-source` |
| `docs/experiments/2026-10-15-rhel-installer.md` | POWER9 proof record |

No caller migration. `ROCKY_REPOSITORY_SUFFIX` stays and `rhel` reuses it, because both trees share
the layout; renaming it would touch every Rocky site for no criterion.

## Task 1: Manifest, kernel arguments, and build (Python)

**Interfaces.** Consumes `_installer_profile`, `_profile_source_arguments`, `_build_manifest`, and
`PROFILE_RELEASES` in `scripts/iso_chain.py`. Provides `RHEL_RELEASES = ("9.0", ..., "10.2")`,
`PROFILE_RELEASES: dict[str, tuple[str, ...]]`, and the factories `rhel_profile(release="9.8")` and
`rhel_manifest_data(**changes)` that Tasks 2 to 4 use.

**Verification.**

- `rhel` parsing: every listed release, a thirteenth, noncanonical releases (`9`, `9.80`, `10.3`, `
  9.8 `), the field set, a stray `kickstart`, the suffix, and the new release message. Mode:
  focused-test, `ManifestV4Tests.test_rhel_profile*`. Red: the `must be fedora/44 ...` error for a
  `rhel` profile. Green: `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests`.
- Kernel arguments omit the Kickstart, `build` stages none, and login values are refused. Mode:
  focused-test, `ManifestV4Tests.test_rhel_kernel_arguments` and
  `BuildTests.test_rhel_*`. Red: `KeyError` on `kickstart`. Green: the same command plus
  `tests.test_iso_chain.BuildTests`.

**Steps.**

1. Add the factories beside `rocky_profile()`:

   ```python
   def rhel_profile(release="9.8"):
       profile = rocky_profile()
       base = "/pub/rhel/9.8/BaseOS/ppc64le/os"
       profile["kernel"]["path"] = f"{base}/ppc/ppc64/vmlinuz"
       profile["initramfs"]["path"] = f"{base}/ppc/ppc64/initrd.img"
       profile["repository"]["path"] = base
       return {**profile, "distribution": "rhel", "release": release}


   def rhel_manifest_data(**changes):
       return manifest_data(
           **{"profiles": {"rhel": rhel_profile()}, "selected_profile": "rhel", **changes}
       )
   ```

2. Write the failing tests and run the green command. Until step 3, a `rhel` profile without
   `kickstart` fails with `missing required field` because no `rhel` field-set branch exists; the
   release message appears only for a profile carrying `kickstart`. Confirm that error for the
   no-`kickstart` cases and the release error for the unlisted-release cases.
3. In `scripts/iso_chain.py` replace line 49 with

   ```python
   RHEL_RELEASES = (
       "9.0",
       "9.1",
       "9.2",
       "9.3",
       "9.4",
       "9.5",
       "9.6",
       "9.7",
       "9.8",
       "10.0",
       "10.1",
       "10.2",
   )
   PROFILE_RELEASES = {
       "fedora": ("44",),
       "opensuse": ("15.6",),
       "rhel": RHEL_RELEASES,
       "rocky": ("9.8",),
       "ubuntu": ("26.04.1",),
   }
   ```

   In `_installer_profile`: add `rhel = distribution_value == "rhel"`; change `elif rocky or
   opensuse:` to `elif rocky or rhel or opensuse:`; change the release test to
   `if release not in PROFILE_RELEASES.get(distribution, ()):`; change the message to
   `"must be fedora/44, opensuse/15.6, rhel/9.0 to 9.8 or 10.0 to 10.2, rocky/9.8, or ubuntu/26.04.1"`;
   change `if rocky:` to `if rocky or rhel:` (comment: the AppStream sibling is derived from this suffix).
4. Update the assertions at `tests/test_iso_chain.py` lines 474, 559, and 612 to the new message.
   `_build_manifest` already rejects login values for any distribution set other than Rocky or
   Ubuntu, so a `rhel` profile needs no code there.
5. Run `just check-tests`; commit `feat: accept rhel manifest profiles`.

## Task 2: `prepare-rhel-source` (Python)

**Interfaces.** Consumes `_treeinfo_images`, `_extract_treeinfo_images`, `_artifact_data`,
`_publish_directory`, `_installer_profile`, `_url_path`, `_sha256`, `_integer`, `_regular_file`,
`_path`, `RHEL_RELEASES`, and `ROCKY_REPOSITORY_SUFFIX`. Provides `prepare_rhel_source(args)` and the
`prepare-rhel-source` subcommand.

**Verification.**

- Argument validation precedes every file read and subprocess: a different `--digest-source`, an
  unlisted `--release`, a bad suffix, a malformed digest, and an out-of-range memory. A missing
  `--digest-source` is an argparse exit, tested through the parser. Mode: focused-test,
  `RHELSourceTests.test_rejects_before_reading`. Red: `AttributeError` on `prepare_rhel_source`.
  Green: `.venv/bin/python -m unittest tests.test_iso_chain.RHELSourceTests`.
- Success path and treeinfo failures (digest mismatch, wrong family, wrong version, wrong variant,
  extracted image mismatch, existing output) plus the printed `digest-source` line and no
  AppStream requirement. Mode: focused-test, same class, same command.

**Steps.**

1. Write `RHELSourceTests` from `RockySourceTests`, with a fake `.treeinfo` whose family is
   `Red Hat Enterprise Linux`, whose `[variant-BaseOS]` is the only variant section, and a fake
   `xorriso`. Confirm the failure.
2. Add after `prepare_rocky_source`:

   ```python
   def prepare_rhel_source(args: argparse.Namespace) -> None:
       if args.digest_source != "mirror-sha256sum":
           raise ValidationError("digest source: must be mirror-sha256sum")
       release = args.release
       if release not in RHEL_RELEASES:
           raise ValidationError("release: not a supported RHEL release")
       expected_digest = _sha256(args.iso_sha256, "ISO digest")
       repository_path = _url_path(args.repository_path, "repository path")
       if not repository_path.endswith(ROCKY_REPOSITORY_SUFFIX):
           raise ValidationError(f"repository path: must end in {ROCKY_REPOSITORY_SUFFIX}")
       memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
       iso = _regular_file(Path(args.iso).absolute(), "RHEL ISO")
       tree = _path(Path(args.tree).absolute(), "RHEL tree", "directory")
       images = _treeinfo_images(
           tree,
           expected_digest,
           "RHEL treeinfo",
           ("Red Hat Enterprise Linux", release, "ppc64le"),
           ("BaseOS",),
       )
       ...  # the remainder is prepare_rocky_source with "RHEL" labels, "rhel", and release
       print("digest-source: mirror-sha256sum")  # after _publish_directory
   ```

   Do not pass `appstream=` to `_treeinfo_images`; its default `None` omits the AppStream check
   that `prepare_rocky_source` makes. Every argument check runs before the first path is touched.
3. Add the subparser after `rocky`: `--iso`, `--iso-sha256`, `--digest-source` (required),
   `--tree`, `--repository-path`, `--release` (required), `--minimum-memory-mib`, `--output`, and the
   `elif args.command == "prepare-rhel-source"` dispatch branch.
4. Run `just check-tests`; commit `feat: add prepare-rhel-source`.

## Task 3: Launcher (shell)

**Interfaces.** Consumes `valid_rocky_arguments`, `anaconda_command_line`, `parse_arguments`'s
`case "$distribution:$release"` block. Provides `valid_rhel_arguments`.

**Verification.** A RHEL command line yields four downloads, no mount, and kexec arguments equal to
Rocky's plus `inst.addrepo=AppStream,…`; each of the twelve listed releases prints
`configuration: passed`; a Kickstart argument, a live-ISO argument, a bad suffix, and the releases
`9.9`, `10.3`, `9.80`, `09.8`, `10.10`, `9`, and `10` print `configuration: failed`. Mode:
focused-test, `tests/test_iso_chain_launch.sh`. Red: `configuration: failed` for a valid RHEL line.
Green: `bash tests/test_iso_chain_launch.sh` prints `launcher shell tests: passed`.

**Steps.**

1. Add `rhel_command_line()` and cases beside the Rocky ones in `tests/test_iso_chain_launch.sh`,
   including a loop over the twelve releases and a loop over the rejected releases above; run it and
   confirm the failure.
2. Add `valid_rhel_arguments`: Rocky's body without the optional-Kickstart branch, rejecting any
   `kickstart_*` value. Add to the `case`:

   ```sh
   rhel:9.[0-8]|rhel:10.[0-2]) valid_rhel_arguments || return 1 ;;
   ```

3. In `anaconda_command_line`, after the `inst.repo` line:

   ```sh
   [ "$distribution" != rhel ] ||
       arguments="$arguments inst.addrepo=AppStream,$source${repository_path%/BaseOS/ppc64le/os}/AppStream/ppc64le/os"
   ```

4. Run the shell test and `just check-tests`; commit `feat: launch rhel profiles`.

## Task 4: Evidence verifiers (Python)

**Interfaces.** Consumes `verify_launcher_log`, `_verify_http_requests`, `_anaconda_probes`,
`_repository_prefixes`, and `_manifest_data`. Provides `rhel` handling in each.

**Verification.**

- Launcher-log handoff: exactly one `inst.repo` and one AppStream `inst.addrepo`, no `inst.ks`; a
  stray `inst.ks`, a missing or repeated `inst.repo`, and a missing or wrong `inst.addrepo` fail.
  Mode: focused-test, `RHELEvidenceTests.test_*handoff*`. Red: `kernel configuration` or
  `installer repository evidence` errors. Green:
  `.venv/bin/python -m unittest tests.test_iso_chain.RHELEvidenceTests`.
- HTTP rules: BaseOS and AppStream allowed, the two probe 404s allowed once, other paths rejected;
  runs also under `ftp://` through `FTPRHELEvidenceTests`. Mode: focused-test, same class. Red:
  `HTTP evidence contains a path outside the selected profile`. Green: the same command plus
  `tests.test_iso_chain.FTPRHELEvidenceTests`.

**Steps.**

1. Write `RHELEvidenceTests(RockyEvidenceTests)`-style fixtures and `FTPRHELEvidenceTests`; confirm
   the failures.
2. Make both edits, which are one commit: in `verify_launcher_log` extend the Rocky `inst.repo`
   block to `profile.distribution in ("rocky", "rhel")` and, for `rhel`, also require the single
   AppStream `inst.addrepo`; in `_verify_http_requests` change `("fedora", "rocky")` to
   `("fedora", "rhel", "rocky")`, and in `_repository_prefixes` change `!= "rocky"` to
   `not in ("rocky", "rhel")` so the AppStream sibling is allowed.
   `_verify_install_http_requests` also calls it but only for the install commands, which have no
   `rhel` form, so it needs no change.
3. Run `just check-tests`; commit `feat: verify rhel installer evidence`.

## Task 5: Documentation

**Verification.** Task: `task-test-not-applicable` for prose in `README.md` and `AGENTS.md`: no
executable consumer reads it; `just check-markdown` and `just check-secrets` still gate it.

**Steps.** Add a README section for the profile and `prepare-rhel-source`, with
`ftp://<REDACTED-FTP-MIRROR>/…` examples and the `--digest-source` acknowledgement. In
`AGENTS.md` update the profile list, the subcommand list, the ADR count and bullets (twenty-eight),
the test-class counts and names, and the fixture factories. Run `just check`; commit
`docs: describe the rhel profiles`.

## Task 6: Build and POWER9 proof

**Verification.** `task-test-not-applicable`: the live run is operator-supervised hardware evidence
recorded in `docs/experiments/2026-10-15-rhel-installer.md`, not an automated test; the checks it
rests on are Tasks 1 to 4.

**Steps.**

1. `prepare-rhel-source` for 9.8 and 10.2 from the operator's mirror (credential from the private
   `.env`, never echoed), `container-prepare-initramfs`, and `container-build` into private storage.
2. Stop and ask the operator before touching the HMC; then boot each ISO with `hmcpctl`.
3. Record the launcher markers, whether AppStream is listed, the hub or the failure, and redacted
   identifiers. Before committing, search the record for the mirror's host, userinfo, and path
   prefix, supplied out of band, and note that the search found nothing; commit
   `docs: record the rhel POWER9 proof`.

## Rollback

Each task is one commit and reverts independently; no migration or persisted state changes.
