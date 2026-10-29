# Operator installer configuration

Status: accepted contract (2026-10-29); not implemented.
Scope: #122, under #120. Decision: [ADR 0034](../../adr/0034-carry-operator-installer-configuration-in-the-manifest.md).
Implementation: foundation #125; Rocky/RHEL #127; Ubuntu #128; Fedora #129; harness and
verifiers #130; QEMU proof #131. Line references are to `scripts/iso_chain.py` at 30acf8c.

## Problem and selected approach

Operators can supply unattended answers only for Fedora, through a `kickstart` artifact that
`build` stages unchanged, with no installer-side guard and no completion marker. Rocky, RHEL and
Ubuntu answers come only from fixed templates. Select an opt-in, per-profile text field that the
manifest digest binds, compose it with fixed guard and marker content in `build`, and select the
completion menu for such media. Manifests without the field are untouched.

## Manifest contract

| Profile distribution | New optional field | Exclusive with |
| --- | --- | --- |
| `fedora` | `operator_kickstart` | `kickstart` (exactly one of the two is required) |
| `rocky`, `rhel` | `operator_kickstart` | none at profile level |
| `ubuntu` | `operator_user_data` | none at profile level |
| `opensuse` | none | not applicable |

Each value is a JSON string, refused with `profiles.<name>.<field>: <reason>` unless:

- it encodes as strict UTF-8 (no lone surrogate) in 1 to 1,048,576 bytes
  (`MAX_KICKSTART_BYTES`, `MAX_USER_DATA_BYTES`);
- it contains no U+0000 to U+001F other than TAB and LF, no U+007F to U+009F, and no U+2028,
  U+2029, U+FFFE or U+FFFF, so CR, every other line separator Python's `str.splitlines` honours
  and every character outside YAML 1.1's printable set are refused;
- its last character is LF.

The manifest stays version 4 and keeps its 2 MiB bound, canonical serialization and digest.
Manifest-level rules, checked by `load_manifest_bytes` and therefore by `validate-config`,
`build`, `container-build`, target composition and every evidence reader:

1. **Operator mode** holds when any profile carries an operator field.
2. In operator mode every profile carries an operator field (`every profile must carry operator
   configuration`).
3. `operator_user_data` requires exactly one profile.
4. Operator mode refuses `login_user`, `ssh_authorized_keys` and `install`, with a reason naming
   the field and ADR 0034. A target request carrying login values over an operator base is
   refused the same way, because the rule reads the composed manifest.

An existing manifest without operator fields parses to the same `Manifest` and the same bytes.
The `InstallerProfile` dataclass gains one value for the text; its name is #125's choice.

## Kickstart composition

`compose(text) = GUARD + text + MARKER`, UTF-8, with no other edit to the operator text.

- `GUARD` is `%pre --erroronfail --interpreter=/bin/sh\n`, a comment line naming ADR 0018 and
  ADR 0034, then the lines of `assets/kickstart/rocky-9.8-unattended.ks`'s `%pre` from `set -eu`
  through the `done` that closes the zero check, then `%end\n`. It omits that template's
  partitioning heredoc: the operator partitions. It reads disks and writes nothing.
- `MARKER` is `%post --erroronfail --interpreter=/bin/sh\n`, a comment line naming ADR 0021 and
  ADR 0034, `set -eu\n`, `grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1\n`,
  `%end\n`.
- Anaconda runs `%pre` scripts in file order before installation and `%post` scripts in file
  order after it (ADR 0021), so the guard precedes every operator `%pre` and the marker follows
  every operator `%post`, chrooted or not. Operator sections keep their relative order, and an
  operator `%include` expands where its line sits, before the marker.
- The composed file is at most 1 MiB, else `composed Kickstart exceeds 1 MiB`. It is staged at
  `/profiles/<name>/ks.cfg`, the derived path, and its size and SHA-256 become
  `iso_chain.profile_kickstart_{path,size,sha256}`. The launcher (`iso-chain-launch.sh`, Fedora
  requires and Rocky/RHEL accept those arguments) and its handoff are unchanged.

## Ubuntu grammar and composition

Grammar: the text is `#cloud-config\n` followed by exactly one JSON object, parsed with
`json.loads` using the manifest's duplicate-key hook and a `parse_constant` that refuses `NaN`,
`Infinity` and `-Infinity` and a `parse_float` that refuses a non-finite result (`1e400`).
Every decoded key and string obeys the field's character rule, which also excludes lone
surrogates. `RecursionError`, `ValueError` and these refusals become one fixed reason. The
object has exactly one key, `autoinstall`, whose value is an object; its `early-commands` and
`late-commands`, when present, are arrays. Under these rules the serialised document is JSON
whose strings hold only characters YAML 1.1 reads literally, so cloud-init reads it as JSON flow
syntax, as ADR 0020's derived user data relies on; no YAML parser or textual splice is involved.

Composition: copy the parsed `autoinstall`, set `early-commands` to the template's guard command
(`assets/autoinstall/ubuntu-26.04.1.json` `early-commands[0]`) followed by the operator's
entries, and `late-commands` to the operator's entries followed by the template's marker
(`late-commands[-1]`). Serialize as `_ubuntu_user_data` does: `#cloud-config\n` plus
`json.dumps({"autoinstall": ...}, ensure_ascii=False, indent=2, sort_keys=True)` plus `\n`. At
most 1 MiB, else `composed user data exceeds 1 MiB`. Staging stays `/user-data` and empty
`/meta-data` on the ISO root, with `iso_chain.profile_user_data_{size,sha256}` as today.
Subiquity runs both lists in order, so the guard is first and the marker last. The guard prints
`autoinstall-disk: passed <disk>`.

## Binding, menu and privacy

- `config_sha256` binds the operator text inside the canonical manifest; the command line binds
  the composed bytes. Composition is a pure function of the manifest, so `_kernel_arguments`,
  `verify_launcher_log` and evidence verifiers recompute every digest without extra inputs.
- `_grub_config` uses `COMPLETION_MENU` when `login_user` is set or operator mode holds. The menu
  text is unchanged. Operator text never reaches the command line, the media result, a JSON
  report or an error message; errors name the field path and a fixed reason only.
- The text is as private as the manifest and appears in `config.json`, the composed file and
  evidence records. `inspect` already prints the embedded manifest to its caller.

## Operator obligations

The guide for each distribution (#127 to #129) states them; the tool does not check them:
install GRUB to the one disk (`/boot/grub2` for Kickstart, `/boot/grub` for Ubuntu), end with a
reboot, close every Kickstart section with `%end`, and on PowerVM keep the firmware boot order
(`bootloader --leavebootorder`, ADR 0019). Users, root, privileges, host name and installed
network are the operator's (ADR 0034 Ownership). The tool does not police network or source
commands in the file; passing evidence needs it to fetch only from the manifest source, as the
template's `apt` and `refresh-installer` settings do for Ubuntu. The embedding commands, for
Rocky or RHEL (Ubuntu uses `operator_user_data`) and for a `prepare-fedora-source` base, which
still requires `--kickstart`, are:

```sh
jq --rawfile text install.ks '.profiles.<name>.operator_kickstart = $text' base.json
jq --rawfile text install.ks '.profiles.<name> |= (del(.kickstart) | .operator_kickstart = $text)' base.json
```

## Evidence observations (#130)

| Observation | Today | Operator mode |
| --- | --- | --- |
| Canonical manifest, launcher log, disk mutation, captures, traffic rules | required | required |
| One installer `reboot: Restarting system` | required | required |
| Ubuntu `autoinstall-disk: passed <disk>` after kexec | required | required |
| One `installed-disk handoff`, no optical handoff or launcher | required | required |
| `<lpar> login:` after the handoff | required | not required |
| Fedora `installed-boot: passed` and `--kickstart` input | `kickstart` artifact only | not used |

Under `COMPLETION_MENU` the installed-disk handoff appears only when the marker is set, so it
proves the composed file ran to its end; it does not prove the installed system boots. In
operator mode the boot phase stops at that handoff line and records
`boot_stop: installed-disk-handoff`. `install-rocky` and `install-ubuntu`
(`_install_unattended`, line 2907) and `install-fedora` (line 2855) accept a selected
operator-mode profile, and operator Fedora evidence uses the unattended verifier without
`--kickstart`.

## Implementation map

- #125: the field and text grammar (`_installer_profile`, lines 428-498), the operator-mode
  rules, the operator-mode predicate at each login-keyed site (lines 983, 1168, 1248, 1309, 1498,
  1580-1592), both composition helpers, `validate-config` renderability, and the `AGENTS.md`
  bullets named in ADR 0034 Ownership. No distribution is wired.
- #127: `_profile_kickstart` (line 1243) for Rocky/RHEL operator text; #129 for Fedora, with a
  starter example distinct from `assets/kickstart/fedora-44-power9.ks`; #128:
  `_profile_user_data` (line 1307) and `_stage_profile_artifacts` (line 1502).
- #130: the table above at the harness predicate (line 2911), `install_fedora` (2855), the boot
  stop and `boot_stop` value (2946, 2955), `_verify_install_result` (3580), the `unattended`
  rule (3693), the evidence profile rule (3648), the Fedora verifier (3715-3722) and the login
  check (3770); #131 records QEMU proof.

## Failure model

1. **Actors and deployments**
   - A local operator authoring a manifest on macOS arm64 or x86_64 Linux, building media.
   - Anaconda or subiquity on QEMU pSeries/POWER9 or native PowerVM consuming the composed file.
2. **Invariants and assets at stake**
   - No install over a disk that is not the single blank one (ADR 0018).
   - An interrupted operator install never becomes the menu default (ADR 0021).
   - Byte-identical media for manifests without operator fields; one digest chain from manifest
     to composed bytes.
   - Operator text never echoed by errors or reports.
3. **Accepted failure classes**
   - An operator file that is syntactically invalid, powers off, fails before its marker or leaves
     a section open: Anaconda or subiquity fails visibly, or the disk boots back to the launcher,
     whose guard refuses it. A file without a bootloader gets the marker, and GRUB stops on the
     missing `grub.cfg`. Accepted: the operator owns the file, and no disk is overwritten.
   - Network or source commands inside operator text, which the tool does not police: accepted
     by ADR 0034 Ownership; evidence traffic rules refuse such a run.
   - Credentials inside operator text: accepted by ADR 0034, private as the manifest.
   - Kickstart text whose own `%pre` writes a disk the guard did not check: unreachable, since
     the guard runs first and fails the install before any operator `%pre`.
4. **Covered elsewhere**
   - Launcher argument and media digest checks: `iso-chain-launch.sh` and
     `tests/test_iso_chain_launch.sh`.
   - Live install proof: #131. Native PowerVM boot-order behaviour: #6 and the operator.

## Threat model

- **Boundaries.** Added: operator text entering `build` and `validate-config` through the
  manifest; composed bytes entering the installer. Widened: the manifest's grammar.
- **Actors.** Trust sits with the local operator who writes the manifest. A party who can alter
  the ISO after build is detected by the launcher's digest checks.
- **Controls.** Strict type, UTF-8, control-character and size checks before any external
  command; `json.loads` with duplicate-key, constant and recursion refusal; fixed-reason errors;
  composition as concatenation or `json.dumps`, never interpolation into shell or YAML.
- **Out of scope.** Content policy inside operator text, including its network and source
  commands (accepted, ADR 0034; evidence refuses out-of-source traffic); a malicious operator,
  who already controls the install.

## Validation

Each implementing issue adds unit tests in the matching `tests/test_iso_chain.py` class and
proves new tests bite with a controlled fault. Tests and fixtures are their issues' changes.

| Contract | Owner | Evidence |
| --- | --- | --- |
| Text grammar and each refusal; no external command for invalid input | #125 | `ManifestV4Tests` |
| Operator-mode rules 1-4, including target composition | #125 | `ManifestV4Tests` |
| Kickstart composition bytes: guard first, text unchanged, marker last; 1 MiB bound | #125, #127, #129 | composition tests |
| User data grammar (non-finite numbers, decoded control and separator characters), injected guard/marker positions, deterministic bytes | #125, #128 | `UbuntuUserDataTests` |
| `COMPLETION_MENU` for operator mode; byte-identical media for `examples/*.json` and existing test manifests | #125 | `grub.cfg`, kernel-argument and staging tests |
| Errors and JSON reports omit operator text | #125 | error-message assertions |
| Evidence table, `boot_stop: installed-disk-handoff`, traffic rules | #130 | evidence verifier tests |
| Live installs | #131 | `docs/experiments/` records |

This design changes no code; `just check` is its guardrail.
