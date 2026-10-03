# Rocky Unattended Install Implementation Plan

Goal: a Rocky 9.8 launcher ISO built from a manifest with SSH keys and a login user installs Rocky
unattended onto the one blank disk, reboots, and boots that disk through the ISO's installed-disk
entry. Spec: `docs/workflow/specs/2026-10-02-rocky-unattended-install-design.md`; ADR 0019.

Architecture: `build` renders a Kickstart from the manifest and a fixed template, stages it on the
ISO, and binds it on the kernel command line exactly as a Fedora profile Kickstart is bound; the
launcher's Rocky argument check accepts it, and the existing `launch_anaconda` path hands it to
Anaconda. A new QEMU harness and verifier reuse the Fedora install helpers.

Tech stack: Python 3.14 standard library, POSIX `sh` in the dracut launcher, `unittest`, the Bash
launcher harness, QEMU pSeries for the proof.

Expected implementation size: 1,400–1,550 changed lines (M) — about 530 Python, 50 Kickstart
template, 50 shell and shell-test, 660 test, and 210 README, AGENTS.md, ADR 0013, and experiment
lines across the four tasks below; the design artifacts are excluded. Corrected after the build
from 600–750: the Fedora install helpers moved into shared functions both harnesses call, the
review-driven checks (argparse refusal, reboot line, `inst.repo`, device and guard assertions)
each added focused tests, and the experiment record was longer; the scope is unchanged.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function; errors are
  `ValidationError` messages that name a field and never echo a key or user value.
- The launcher stays POSIX `sh` using only tools in `DRACUT_TOOLS`.
- Every GRUB menu entry stays under 1,024 bytes; the kernel command line stays under 2,048 bytes.
- Keyless manifests (every profile kind) keep their kernel command lines, launcher handoffs, and
  evidence; every `grub.cfg` gains only the installed-disk echo line.
- Test keys are fake strings beginning `ssh-ed25519 AAAA`; if detect-secrets flags one, refresh
  `.secrets.baseline` in the same commit and record why.
- No private data in committed evidence; raw logs, captures, and disks stay in private storage.

## File map

- `scripts/iso_chain.py` — `ROCKY_KICKSTART` path constant, `_rocky_kickstart`,
  `_profile_kickstart`, `_profile_source_arguments`, `_kernel_arguments`, `_stage_profile_artifacts`,
  `_build_manifest`, `INSTALLED_DISK_MENU`, `verify_launcher_log`, `_copy_bounded_stream`,
  `_run_qemu_phase`, `install_rocky`, `_verify_install_http_requests`, `_installed_disk_login`,
  `verify_rocky_install_evidence`, `parser`, `main`. Extended in place.
- `assets/kickstart/rocky-9.8-unattended.ks` — new fixed template (criterion 3, 4, 5).
- `assets/dracut/iso-chain-launch.sh` — `valid_rocky_arguments` (criterion 2).
- `tests/test_iso_chain.py`, `tests/test_iso_chain_launch.sh` — tests.
- `docs/adr/0013-...md` (consequence line), `README.md`, `AGENTS.md`,
  `docs/experiments/2026-10-02-rocky-unattended-install.md`.

## Task 1: Derived Rocky Kickstart in build

Files: `scripts/iso_chain.py`, `assets/kickstart/rocky-9.8-unattended.ks`,
`tests/test_iso_chain.py`.

Interfaces: produces `_rocky_kickstart(manifest: Manifest) -> bytes` and
`_profile_kickstart(manifest: Manifest, name: str) -> tuple[Artifact, bytes | None] | None`, the
latter consumed by Task 2's `verify_launcher_log`; consumes the existing `Manifest`,
`MAX_KICKSTART_BYTES`, `_kernel_arguments`, `_grub_config`, `_stage_profile_artifacts`.

Verification:

- Mode: focused-test. Contract: refusal lifted only for all-Rocky manifests. Tests in `BuildTests`:
  a Rocky manifest with keys builds; a Fedora, Ubuntu, or openSUSE profile beside keys raises
  `ValidationError` matching `rocky` with `run.assert_not_called()`; a key starting with `-` and an
  `lpar` ending in `-` raise field-named errors that do not echo the value. Red: the current
  blanket refusal. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Mode: focused-test. Contract: rendering is breakout-free. `RockyKickstartTests` renders keys
  `"ssh-ed25519 AAAA a'b"`, `'... "q" \\ # %pre'`, `"%post"`, and a Cyrillic comment, and asserts
  each `sshkey` line `shlex.split(line, comments=True) == ["sshkey", "--username=core", key]`,
  exactly one `%pre`, `%post`, `%packages` line, every non-section line from the generated tail
  starts with a fixed command, the last command is `reboot`, the `%pre` bootloader line carries
  `--leavebootorder` and `ipv6.disable=1`, and 16 keys of 8,192 `'` characters stay under
  `MAX_KICKSTART_BYTES`. Red: `_rocky_kickstart` undefined. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.RockyKickstartTests`.
- Mode: focused-test. Contract: no fixed device and the `%pre` guard. `RockyKickstartTests` asserts
  the rendered Kickstart contains no `vd`, `sd`, or `nvme` device literal, every disk option in the
  `%pre` heredoc uses `$disk`, and the `%pre` keeps its `count` test, both zero-digest reads, and
  `exit 1` refusals.
- Mode: focused-test. Contract: keyfile and hostname. The same class asserts the `%post` keyfile
  lines for a manifest with two routes and two DNS servers, and `network --hostname=<lpar>`.
- Mode: focused-test. Contract: staging and binding. `BuildTests` asserts the staged
  `/profiles/rocky/ks.cfg` bytes equal `_rocky_kickstart`, the GRUB variable carries the three
  `iso_chain.profile_kickstart_*` arguments, and a keyless Rocky manifest's command line equals the
  pre-change one (no Kickstart arguments).
- Mode: focused-test. Contract: installed-disk echo. The existing menu case asserts the entry body
  starts with `echo 'ISO_CHAIN: GRUB installed-disk handoff'` and stays under 1,024 bytes.
- Template: task-test-not-applicable for its Anaconda semantics; Anaconda is not available to the
  suite, and Task 4's QEMU run exercises them. Its structure is covered by the `RockyKickstartTests`
  section counts above.

Steps:

1. Write the tests above; run red.
2. Add the template. Its `%pre`, with `--erroronfail --interpreter=/bin/sh`:

   ```sh
   set -eu
   zero=30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58
   count=0
   for entry in /sys/block/*; do
       [ -e "$entry/device" ] || continue
       case "${entry##*/}" in sr*) continue ;; esac
       count=$((count + 1))
       disk=${entry##*/}
   done
   [ "$count" -eq 1 ] || { echo "iso-chain-disk: failed count=$count" >&2; exit 1; }
   sectors=$(cat "/sys/block/$disk/size")
   case "$sectors" in '' | *[!0-9]*) echo 'iso-chain-disk: failed blank' >&2; exit 1 ;; esac
   for skip in 0 $((sectors - 2048)); do
       found=$(dd if="/dev/$disk" bs=512 skip="$skip" count=2048 2>/dev/null | sha256sum)
       [ "${found%% *}" = "$zero" ] || { echo 'iso-chain-disk: failed blank' >&2; exit 1; }
   done
   cat >/tmp/iso-chain-disk.ks <<EOF
   ignoredisk --only-use=$disk
   zerombr
   clearpart --all --initlabel --drives=$disk
   bootloader --location=mbr --boot-drive=$disk --leavebootorder --append="console=hvc0 ipv6.disable=1"
   part prepboot --fstype=prepboot --size=4 --ondisk=$disk
   part /boot --fstype=xfs --size=1024 --ondisk=$disk
   part pv.01 --grow --size=1 --ondisk=$disk
   volgroup rocky pv.01
   logvol / --fstype=xfs --grow --size=4096 --name=root --vgname=rocky
   EOF
   ```

   plus the commands the spec lists and `reboot`.
3. Implement `_rocky_kickstart`: read the template bytes from
   `REPOSITORY_ROOT / "assets/kickstart/rocky-9.8-unattended.ks"`, prepend the spec's generated
   lines with `shlex.quote` for the user and each key, encode UTF-8, and raise `ValidationError`
   (`"rendered Kickstart exceeds 1 MiB"`) above `MAX_KICKSTART_BYTES`. Before rendering, raise
   `"manifest ssh_authorized_keys[<i>]: must not start with -"` and
   `"manifest lpar: must not end in - for an unattended rocky install"`.
4. Implement `_profile_kickstart`: Fedora returns `(profile.kickstart, None)`; Rocky with
   `manifest.login_user` returns `(Artifact(f"/profiles/{name}/ks.cfg", len(data), sha256), data)`;
   otherwise `None`. Pass its artifact into `_profile_source_arguments(profile, kickstart)`; make
   `_stage_profile_artifacts` write derived bytes directly and copy declared ones as today.
5. Narrow the `_build_manifest` refusal to manifests with a non-`rocky` profile, message
   `"login_user and ssh_authorized_keys: only rocky profiles apply them (ADR 0017, ADR 0019)"`.
6. Add the echo line to `INSTALLED_DISK_MENU`; run green; `just check`; commit.

## Task 2: Launcher and launcher-log evidence

Files: `assets/dracut/iso-chain-launch.sh`, `tests/test_iso_chain_launch.sh`, `scripts/iso_chain.py`,
`tests/test_iso_chain.py`.

Interfaces: consumes `_profile_kickstart` from Task 1; the launcher consumes the
`iso_chain.profile_kickstart_*` arguments Task 1 emits.

Verification:

- Mode: focused-test. Contract: Rocky Kickstart arguments. Shell cases: a Rocky command line with a
  valid Kickstart triple mounts the media, verifies the Kickstart, and passes
  `inst.ks=cdrom:LABEL=<label>:/profiles/rocky/ks.cfg` and `inst.repo=...`; a partial triple and a
  1,048,577-byte size fail with `configuration: failed` before any `curl` or `mount`; the keyless
  case is unchanged. Red: `valid_rocky_arguments` rejects Kickstart arguments. Green:
  `bash tests/test_iso_chain_launch.sh` prints `launcher shell tests: passed`.
- Mode: focused-test. Contract: `verify_launcher_log` for unattended Rocky. `RockyEvidenceTests`
  accepts a log with `media: passed`, the derived `inst.ks`, and `inst.repo`, and rejects one
  missing any of them or carrying a different `inst.repo`.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.RockyEvidenceTests`.

Steps: write the tests; run red; change `valid_rocky_arguments` to accept an all-empty triple or
`valid_path`, `valid_size`, size at most 1,048,576, and `valid_sha256`; replace the update comment in
`launch_anaconda`; switch `verify_launcher_log`'s `profile.kickstart` uses to `_profile_kickstart`
and key its `inst.repo` check on `profile.distribution == "rocky"`; run green; commit.

## Task 3: Rocky QEMU harness and verifier

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: produces `install_rocky(args: argparse.Namespace) -> None` and
`verify_rocky_install_evidence(args: argparse.Namespace) -> tuple[str, ...]`; extends
`_run_qemu_phase(command, log, timeout, capture_fifo=None, capture=None, until: bytes | None =
None) -> int` (returns 0 when it stopped QEMU after `until` appeared) and
`_verify_install_http_requests(records, profile)` (Rocky prefixes and probes).

Verification:

- Mode: focused-test. Contract: harness command shape and flow. `InstallTests` with
  `subprocess.run`/`Popen` patched: two QEMU runs, both with the ISO, disk, NIC, and `-no-reboot`;
  the second stops after `<lpar> login:`; `result.json` has `boot_stop: login-prompt`; a keyless or
  non-Rocky manifest raises before any command. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.InstallTests`.
- Mode: focused-test. Contract: evidence verifier. `RockyInstallEvidenceTests` accepts a consistent
  set and rejects: a non-Rocky or keyless manifest, an unchanged disk hash, a replaced input, an
  install console without `reboot: Restarting system` or with `reboot: Power down`, an
  access-log path outside BaseOS/AppStream, a second 404 of a probe, a boot console with an optical
  handoff or launcher line, and one without the login line. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.RockyInstallEvidenceTests`.

Steps: write tests; run red; implement the marker watch in `_copy_bounded_stream` (keep the last
`len(until)` bytes across blocks, set a `threading.Event`, terminate QEMU); implement
`install_rocky` beside `install_fedora`; factor the Fedora verifier's input reading and record
identity into a helper both verifiers call; add the parsers and dispatch; run green; commit.

## Task 4: Proof and documentation

Files: `docs/experiments/2026-10-02-rocky-unattended-install.md`, `README.md`, `AGENTS.md`,
`docs/adr/0013-hand-off-to-the-rocky-anaconda-installer.md`.

Verification:

- Mode: task-test-not-applicable. Surface: the QEMU record. Reason: it needs emulated firmware and a
  multi-hour TCG install the suites cannot run.
- Mode: task-test-not-applicable. Surface: README, AGENTS.md, ADR 0013 line. Reason: prose with no
  executable consumer; `just check-markdown` gates its form.

Steps:

1. Build the launcher with `container-build` from a private manifest (QEMU default addresses, one
   Rocky profile, a test key pair kept private plus an adversarial-comment key), serve the private
   Rocky mirror with `serve-source`, and populate missing packages in a scratch run first.
2. Run `install-rocky`, then `verify-rocky-install-evidence`; boot a disposable qcow2 overlay of
   the published disk with the ISO and an SSH host forward, log in with the private key, and
   record user, hostname, address, routes, `nmcli` profile, and `authorized_keys` equality.
3. Write the experiment record (public-safe summary, labelled QEMU, stating that SLOF cannot show
   the effect of `--leavebootorder`), README sections for unattended Rocky, `install-rocky`, and
   `verify-rocky-install-evidence`, AGENTS.md updates (profile text, subcommands, ADR count), and
   ADR 0013's consequence line pointing at ADR 0019; `just check`; commit.

Rollback: revert the branch; keyless media is unaffected by construction.
