# Ubuntu Unattended Install Implementation Plan

Goal: an Ubuntu 26.04.1 launcher ISO built from a manifest with SSH keys and a login user installs
Ubuntu unattended onto the one blank disk, reboots, and boots that disk through the ISO's
installed-disk entry. Spec: `docs/workflow/specs/2026-10-03-ubuntu-unattended-install-design.md`;
ADR 0020.

Architecture: `build` renders cloud-init user data holding the autoinstall configuration from the
manifest and a fixed JSON template, stages it with an empty `meta-data` at the ISO root, and binds
its size and digest on the kernel command line. The launcher checks both files on the media and
kexecs casper with `ds=nocloud` and a `cc:` token that points NoCloud at the ISO's label. A QEMU
harness and verifier share the Rocky install code.

Tech stack: Python 3.14 standard library, POSIX `sh` in the dracut launcher, `unittest`, the Bash
launcher harness, QEMU pSeries for the proof.

Expected implementation size: 850–1,050 changed lines (L) — about 230 Python, 40 JSON template,
70 shell and 90 shell-test, 380 unit-test, and 200 README, AGENTS.md, ADR 0012, and experiment
lines across the four tasks below; the design artifacts are excluded.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function; errors are
  `ValidationError` messages that name a field and never echo a key or user value.
- The launcher stays POSIX `sh` using only tools in `DRACUT_TOOLS`.
- Every GRUB menu entry stays under 1,024 bytes; the kernel command line stays under 2,048 bytes.
- Keyless manifests (every profile kind) keep their kernel command lines, launcher handoffs, ISO
  contents, and evidence.
- Test keys are fake strings beginning `ssh-ed25519 AAAA`; if detect-secrets flags one, refresh
  `.secrets.baseline` in the same commit and record why.
- No private data in committed evidence; raw logs, captures, and disks stay in private storage.

## File map

- `scripts/iso_chain.py` — new `UBUNTU_AUTOINSTALL`, `MAX_USER_DATA_BYTES`, `_ubuntu_user_data`,
  `_profile_user_data`; extended `_profile_source_arguments`, `_kernel_arguments`,
  `_stage_profile_artifacts`, `_build_manifest`, `_ubuntu_handoff`, `verify_launcher_log`,
  `_verify_install_http_requests`, `_verify_install_result`, `_install_evidence`; `install_rocky`
  becomes `_install_unattended(args, distribution)` called by `install_rocky` and new
  `install_ubuntu`; `verify_rocky_install_evidence` becomes `_verify_unattended_install(args,
  distribution)` called by it and new `verify_ubuntu_install_evidence`; `parser`, `main`.
- `assets/autoinstall/ubuntu-26.04.1.json` — new fixed autoinstall keys (Success 3).
- `assets/dracut/iso-chain-launch.sh` — argument parsing, `valid_ubuntu_arguments`,
  `check_capacity`, `ubuntu_command_line`, `launch_ubuntu` (Success 4).
- `tests/test_iso_chain.py`, `tests/test_iso_chain_launch.sh` — tests.
- `docs/adr/0012-...md` (consequence line), `README.md`, `AGENTS.md`, `.secrets.baseline`,
  `docs/experiments/2026-10-03-ubuntu-unattended-install.md`.

## Task 1: Rendered user data in build

Files: `scripts/iso_chain.py`, `assets/autoinstall/ubuntu-26.04.1.json`,
`tests/test_iso_chain.py`.

Interfaces: produces `_ubuntu_user_data(manifest: Manifest) -> bytes`,
`_profile_user_data(manifest: Manifest, name: str) -> bytes | None`, and
`_ubuntu_handoff(manifest: Manifest, profile: InstallerProfile, label: str | None) -> list[str]`,
consumed by Task 3; consumes the existing `Manifest`, `_kernel_arguments`,
`_profile_source_arguments`, `_stage_profile_artifacts`, `_build_manifest`, `_volume_id`.

Verification:

- Mode: focused-test. Contract: refusal lifted only for manifests whose profiles are all `rocky` or
  all `ubuntu`. `BuildTests`: an Ubuntu manifest with keys builds; a Fedora, openSUSE, or Rocky
  profile beside an Ubuntu one with keys raises before `subprocess.run`. Red: the current refusal
  names only `rocky`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Mode: focused-test. Contract: the rendering. New `UbuntuUserDataTests`: hostile keys
  (`'`, `"`, `\`, `#`, `:`, `{`, leading `-`, `%`, Cyrillic) round-trip through
  `json.loads(rendered.split(b"\n", 1)[1])`; the first line is `#cloud-config`; the only top-level
  key is `autoinstall`; network, user, host name, and `disable_root` match the manifest; DNS is
  omitted when empty; `iso-chain` does not occur; an `lpar` ending in `-` raises. Red: the function
  does not exist. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuUserDataTests`.
- Mode: focused-test. Contract: staging and command-line binding. `BuildTests`: the staged
  `user-data` equals the rendering, `meta-data` is empty, the command line carries
  `iso_chain.profile_user_data_size` and `_sha256` right after the live ISO path; a keyless Ubuntu
  build stages neither file and keeps its command line. Red: no such argument. Green as above.
- Mode: focused-test. Contract: completion-marker menu. `BuildTests`: a keyed Ubuntu `grub.cfg`
  contains `load_env --file` for `iso_chain_installed` and clears `iso_chain_disk` unless it is
  `1`; keyless Ubuntu, Rocky, and Fedora `grub.cfg` text equals today's. Red: the marker text is
  absent. Green as above.

Steps:

1. Write the tests above; run them and see them fail.
2. Add the template:

```json
{
  "apt": {"fallback": "offline-install", "geoip": false, "mirror-selection": {"primary": []}},
  "early-commands": [["sh", "-c", "<ADR 0018 disk check printing autoinstall-disk: ...>"]],
  "late-commands": [["curtin", "in-target", "--target=/target", "--", "grub-editenv",
                     "/boot/grub/grubenv", "set", "iso_chain_installed=1"]],
  "refresh-installer": {"update": false},
  "shutdown": "reboot",
  "ssh": {"allow-pw": false, "install-server": true},
  "storage": {"layout": {"name": "direct"}},
  "timezone": "Etc/UTC",
  "version": 1
}
```

   The disk script is ADR 0019's `%pre` count and zero checks with messages
   `autoinstall-disk: failed count=$count`, `autoinstall-disk: failed blank`, and
   `autoinstall-disk: passed $disk`, and no partitioning output.

3. Add the renderer:

```python
UBUNTU_AUTOINSTALL = REPOSITORY_ROOT / "assets/autoinstall/ubuntu-26.04.1.json"
MAX_USER_DATA_BYTES = 1024 * 1024


def _ubuntu_user_data(manifest: Manifest) -> bytes:
    """Render cloud-init user data holding the unattended autoinstall (ADR 0020)."""
    if manifest.lpar.endswith("-"):
        _manifest_error("lpar", "must not end in - for an unattended ubuntu install")
    network = manifest.network
    ethernet: dict[str, object] = {
        "match": {"macaddress": network.mac},
        "addresses": [network.address],
        "routes": [{"to": "default", "via": dict(network.routes)["0.0.0.0/0"]}],
        "dhcp4": False,
        "dhcp6": False,
        "accept-ra": False,
        "link-local": [],
    }
    if network.dns:
        ethernet["nameservers"] = {"addresses": list(network.dns)}
    autoinstall = json.loads(UBUNTU_AUTOINSTALL.read_text())
    autoinstall["network"] = {"version": 2, "ethernets": {"iso0": ethernet}}
    autoinstall["user-data"] = {
        "hostname": manifest.lpar,
        "disable_root": True,
        "users": [
            {
                "name": manifest.login_user,
                "lock_passwd": True,
                "shell": "/bin/bash",
                "ssh_authorized_keys": list(manifest.ssh_authorized_keys),
            }
        ],
    }
    document = json.dumps(
        {"autoinstall": autoinstall}, ensure_ascii=False, indent=2, sort_keys=True
    )
    rendered = f"#cloud-config\n{document}\n".encode()
    if len(rendered) > MAX_USER_DATA_BYTES:
        raise ValidationError("rendered user data exceeds 1 MiB")
    return rendered


def _profile_user_data(manifest: Manifest, name: str) -> bytes | None:
    if manifest.profile(name).distribution != "ubuntu" or manifest.login_user is None:
        return None
    return _ubuntu_user_data(manifest)
```

4. `_profile_source_arguments(profile, kickstart, user_data: bytes | None)` appends, for a live
   ISO profile with user data, `iso_chain.profile_user_data_size=<len>` and
   `iso_chain.profile_user_data_sha256=<sha256>`; `_kernel_arguments` passes
   `_profile_user_data(manifest, profile)`.
5. `_stage_profile_artifacts` writes `stage / "user-data"` (the rendering) and an empty
   `stage / "meta-data"` when any profile's `_profile_user_data` is not `None`.
6. `_build_manifest` refuses login values unless the set of distributions is `{"rocky"}` or
   `{"ubuntu"}`, with the message `login_user and ssh_authorized_keys: every profile must be rocky,
   or every profile ubuntu (ADR 0017, ADR 0019, ADR 0020)`, then calls `_rocky_kickstart` or
   `_ubuntu_user_data` for that distribution.
7. `_grub_config` uses `INSTALLED_DISK_MENU` unchanged unless `manifest.login_user` is set and
   every profile is `ubuntu`; then it uses this menu, which keeps the search loop and adds the
   marker check:

```text
for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do
    if [ -z "$iso_chain_disk" ]; then
        if search --no-floppy --file --set=iso_chain_disk $iso_chain_directory/grubenv; then
            set iso_chain_config=$iso_chain_directory/grub.cfg
            set iso_chain_env=$iso_chain_directory/grubenv
        fi
    fi
done
if [ -n "$iso_chain_disk" ]; then
    load_env --file ($iso_chain_disk)$iso_chain_env iso_chain_installed
    if [ "$iso_chain_installed" != 1 ]; then
        unset iso_chain_disk
    fi
fi
```

   followed by the existing `if [ -n "$iso_chain_disk" ]` entry block.

8. `_ubuntu_handoff(manifest, profile, label)` returns `ip=`, `BOOTIF=`, `iso-url=`, then for a
   label `autoinstall`, `ds=nocloud`,
   `cc:datasource:%20{NoCloud:%20{fs_label:%20<label>}}%20end_cc`, `console=hvc0`, `---`,
   `ipv6.disable=1`; without a label `console=hvc0`, `ipv6.disable=1`.
9. Run the focused tests green, then `just check`; commit
   `feat: render Ubuntu autoinstall user data in build`.

## Task 2: Launcher user-data check and unattended handoff

Files: `assets/dracut/iso-chain-launch.sh`, `tests/test_iso_chain_launch.sh`.

Interfaces: consumes Task 1's kernel arguments `iso_chain.profile_user_data_size` and
`iso_chain.profile_user_data_sha256` and the ISO-root `/user-data` and `/meta-data`; produces the
unattended casper command line that Task 3's verifier compares.

Verification:

- Mode: focused-test. Contract: argument grammar. Shell cases: Ubuntu with both or neither
  argument passes configuration; one alone, a size of 1,048,577, a non-hex digest, or either
  argument on a Fedora, Rocky, or openSUSE line prints `configuration: failed`. Red: the arguments
  are ignored today. Green: `bash tests/test_iso_chain_launch.sh` printing
  `launcher shell tests: passed`.
- Mode: focused-test. Contract: media checks and handoff. Shell cases: matching user data and an
  empty `meta-data` reach kexec with the exact unattended line from the spec and `media: passed`;
  a wrong digest prints `user-data-digest: failed`; a non-empty or missing `meta-data` prints
  `meta-data: failed`; a second device under the lower-case label or `LABEL_FATBOOT` prints
  `media-label: failed`; keyless Ubuntu keeps its line and never mounts media. The fake `blkid`
  answers each `-t` tag separately and exits 2 when nothing matches, as util-linux does. Green as
  above.

Steps:

1. Write the shell cases; run and see them fail.
2. Parse `iso_chain.profile_user_data_size=*` and `iso_chain.profile_user_data_sha256=*` into
   `user_data_size` and `user_data_digest`, each at most once.
3. In `valid_ubuntu_arguments`, accept both empty or `valid_size` with `-le 1048576` plus
   `valid_sha256`; after the distribution `case`, reject either variable for any other
   distribution.
4. Add `${user_data_size:-0}` to `check_capacity`'s download sum.
5. `launch_ubuntu`: when `user_data_size` is set, `find_media || { stage_failure media; ... }`,
   then for each tag `LABEL=<lower-case label>` and `LABEL_FATBOOT=<label>` run
   `blkid -c /dev/null -t "$tag" -o device`, requiring exit status 2 and no output or
   `stage_failure media-label`; print `media: passed`, `copy_media_artifact user-data /user-data "$user_data_size"
   "$user_data_digest"`, require `[ -f "$media_dir/meta-data" ] && [ ! -L ... ] && [ ! -s ... ]`
   or `stage_failure meta-data`, then unmount as `launch_anaconda` does.
6. `ubuntu_command_line` appends `autoinstall ds=nocloud
   cc:datasource:%20{NoCloud:%20{fs_label:%20$(media_label)}}%20end_cc console=hvc0 ---
   ipv6.disable=1` when user data is set, else `console=hvc0 ipv6.disable=1`.
7. Run the shell test green and `just check`; commit
   `feat: hand verified user data to the Ubuntu installer`.

## Task 3: Launcher-log verification, harness, and evidence verifier

Files: `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: consumes `_profile_user_data`, `_ubuntu_handoff`, `_volume_id`; produces
`install_ubuntu(args) -> None`, `verify_ubuntu_install_evidence(args) -> tuple[str, ...]`, and the
CLI subcommands `install-ubuntu` and `verify-ubuntu-install-evidence`.

Verification:

- Mode: focused-test. Contract: `verify_launcher_log` for Ubuntu. `UbuntuEvidenceTests`: an
  unattended log with `media: passed` and the exact unattended line passes; a missing
  `media: passed`, a missing `autoinstall`, an extra `url=`, or a keyless line on unattended media
  raises; keyless logs still pass. Red: the media marker is not required. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuEvidenceTests`.
- Mode: focused-test. Contract: `install-ubuntu` shape. `InstallTests`: refuses a keyless or
  non-Ubuntu manifest before `qemu-img`; runs install with `-no-reboot`, then boot until
  `<lpar> login:`, publishing `result.json` with `boot_stop`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.InstallTests`.
- Mode: focused-test. Contract: `verify-ubuntu-install-evidence`. New
  `UbuntuInstallEvidenceTests`: a consistent record set passes with the Rocky result lines but
  `user-data: passed` in place of `kickstart: passed`; an access log with a fourth request, a
  missing or repeated `autoinstall-disk: passed <disk>` line, a missing reboot line, an
  unchanged disk, a keyless manifest, and a boot log without the
  installed-disk handoff each raise. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.UbuntuInstallEvidenceTests`.

Steps:

1. Write the tests; see them fail.
2. `verify_launcher_log`: `media` is required when `_profile_kickstart` or `_profile_user_data`
   returns a value; for a live ISO profile compare the whole installer argument list, with quotes
   removed, to `_ubuntu_handoff(manifest, profile, label)` where `label` is `_volume_id(digest)`
   for unattended media and `None` otherwise.
3. Rename `install_rocky`'s body to `_install_unattended(args, distribution)`; `install_rocky` and
   `install_ubuntu` call it with `"rocky"` and `"ubuntu"`.
4. `_install_evidence` requires login values for `rocky` and `ubuntu`;
   `_verify_install_result` keys `boot_stop` on both; `_verify_install_http_requests` calls
   `_verify_http_requests` for a live ISO profile.
5. Rename `verify_rocky_install_evidence`'s body to `_verify_unattended_install(args,
   distribution)`; the second result line is `kickstart: passed` for Rocky and
   `user-data: passed` for Ubuntu, and the Ubuntu path also requires exactly one install-console
   line matching `autoinstall-disk: passed [a-z][a-z0-9]*` after `kexec-exec: started`.
6. Register both subcommands in `parser()` with `install-rocky`'s and
   `verify-rocky-install-evidence`'s arguments, and dispatch them in `main()`.
7. Run focused tests, then `just check-tests` and `just check`; commit
   `feat: add the Ubuntu unattended harness and evidence verifier`.

## Task 4: Documents and QEMU proof

Files: `docs/adr/0012-hand-off-to-the-ubuntu-live-server-installer.md`, `README.md`, `AGENTS.md`,
`.secrets.baseline`, `docs/experiments/2026-10-03-ubuntu-unattended-install.md`.

Verification:

- Mode: task-test-not-applicable. Surface: ADR 0012 consequence line, README, AGENTS.md, and the
  experiment record. Reason: prose read only by people; no executable consumer validates it, and
  `just check-markdown` already gates its form.
- Mode: task-test-not-applicable. Surface: the QEMU proof. Reason: it needs an emulated pSeries
  install of about an hour with a 1.6 GB live ISO that the unit suites cannot run; its record is
  checked by `verify-ubuntu-install-evidence` on the private evidence.

Steps:

1. Add one ADR 0012 consequence line pointing at ADR 0020 for the unattended handoff.
2. README: the unattended Ubuntu flow, `install-ubuntu`, and `verify-ubuntu-install-evidence`.
   AGENTS.md: overview, decision list, and test-class names.
3. Build the launcher at the branch head, run `install-ubuntu` against a loopback `serve-source`,
   run `verify-ubuntu-install-evidence`, log in over SSH on a disposable overlay, then run one
   interrupted arm: stop QEMU after `autoinstall-disk: passed` and before the late command, boot
   the same disk and ISO, and expect the installer entry and `disk-blank: failed`. Write the
   public-safe experiment record with emulator labelling.
4. Refresh `.secrets.baseline` line numbers if `just check-secrets` reports drift; run
   `just check`; commit `docs: record the Ubuntu unattended install`.
