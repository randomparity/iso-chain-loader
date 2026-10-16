# RHEL Unattended Install Design

Issue: #79. Decision: [ADR 0031](../../adr/0031-install-rhel-unattended-from-a-derived-kickstart.md),
amending ADR 0017, 0019, 0021, and 0028.

## Problem

`rhel` profiles (ADR 0028) hand off to an interactive Anaconda, and `build` refuses
`ssh_authorized_keys` and `login_user` for them, so hmcpctl's built mode cannot install RHEL.
Rocky has the unattended path (ADR 0019, 0021) and the launcher already carries its pieces.

## Scope

- **Template.** New `assets/kickstart/rhel-unattended.ks`: Rocky's template with the header comment
  naming RHEL and `volgroup rhel` / `--vgname=rhel`. Rocky's file is not edited. One file serves
  RHEL 9.0 to 10.2; the commands it uses are accepted by pykickstart for both majors (ADR 0031).
- **Renderer.** In `scripts/iso_chain.py`, `_rocky_kickstart` becomes
  `_kickstart(manifest, distribution)`, reading `ROCKY_KICKSTART` or a new `RHEL_KICKSTART`
  at call time. Output for Rocky is byte-identical. The `lpar` error names the distribution.
  `_profile_kickstart` derives for `rocky` and `rhel`; `_configuration_manifest` renders one
  Kickstart per such distribution so `container-build` refuses before the engine runs.
- **Login rule.** `_configuration_manifest` admits login values when the distributions are a
  nonempty subset of `{rocky, rhel}` or exactly `{ubuntu}`; the message names rocky, rhel, and
  ubuntu. Fedora and openSUSE stay refused.
- **Launcher.** `assets/dracut/iso-chain-launch.sh`: delete `valid_rhel_arguments`, whose only job
  is to reject a Kickstart, and route the `rhel:9.[0-8] | rhel:10.[0-2]` cases to
  `valid_rocky_arguments`, which already bounds a Kickstart and requires its three fields together.
  Argument assembly is unchanged: `inst.ks=` precedes `inst.repo=` and `inst.addrepo=`. Keyless
  RHEL arguments are unchanged.
- **Documents.** README's intro and its RHEL and login-value paragraphs; AGENTS.md's profile line,
  login bullet, Rocky template line and ADR list; one-line banners on ADR 0017, 0019, 0021, 0028; `.secrets.baseline`
  line numbers if they shift.
- No change to Rocky, Fedora, Ubuntu, or openSUSE bytes, the harness, verifiers, or evidence.

## Failure model

1. **Actors and deployments**
   - A local operator running `build`, `container-build`, and `validate-config` on Linux or macOS.
   - hmcpctl booting keyed media on a PowerVM partition (as ADR 0019).
2. **Invariants and assets at stake**
   - Untrusted key strings never reach Kickstart parsing unquoted; leading `-` and `lpar` ending
     in `-` are refused before any command runs.
   - The staged Kickstart's size and SHA-256 equal the kernel arguments and the launcher check.
   - Rocky media and keyless RHEL media keep byte-identical Kickstarts and kernel arguments.
3. **Accepted failure classes**
   - Anaconda may reject the template on some RHEL release: unproven here; the install harness is
     follow-up issue #97 (ADR 0031).
   - `inst.addrepo` beside `inst.ks` is untested on RHEL: ADR 0028's accepted class.
   - Edits to the shared template body must be made in both files: a test pins the copies.
4. **Covered elsewhere**
   - Login user administrative access: ADR 0023. HMC/VIOS: #6. Native PowerVM proof: #28.

## Success

1. A `rhel` manifest with login values passes `build` and `validate-config`; mixed
   `rocky`+`rhel` passes; `fedora` or `openSUSE` with them is refused with the new message.
2. The rendered RHEL Kickstart equals Rocky's rendering of the same manifest apart from the
   header comment and the volume-group name; Rocky's rendering is unchanged.
3. The ISO stages `/profiles/<profile>/ks.cfg` for the RHEL profile, and its kernel arguments carry
   its path, size, and SHA-256, derived by the `_profile_kickstart` that `verify_launcher_log` uses.
4. The launcher accepts a RHEL Kickstart and passes `inst.ks=cdrom:LABEL=...`, `inst.repo=`, and
   `inst.addrepo=AppStream,...` in that order; a partial or oversized Kickstart is refused.
5. Keyed RHEL media uses the completion-checking menu; keyless RHEL media is unchanged.

## Validation

- **Template and renderer (Success 2).** Mode: focused-test. New `RhelKickstartTests` in
  `tests/test_iso_chain.py`: a RHEL render versus Rocky's with the two named differences; leading
  `-` key and `lpar` ending in `-` refused. Red: `AttributeError` on `_kickstart`.
- **Login rule (Success 1).** Mode: focused-test. Rename and extend
  `BuildTests.test_refuses_login_values_unless_all_rocky_rhel_or_ubuntu_before_grub`; a mixed
  keyed build test. Red: RHEL manifest still refused.
- **Staging and arguments (Success 3, 5).** Mode: focused-test. A keyed RHEL build test over the
  ISO tree, kernel arguments, menu, and `verify_launcher_log`. Red: no `ks.cfg`.
- **Launcher (Success 4).** Mode: focused-test. `tests/test_iso_chain_launch.sh` RHEL arms flip
  from refusal to acceptance plus partial and oversized refusals. Red: RHEL with Kickstart refused.
- **Installer runtime.** Mode: task-test-not-applicable; Anaconda behaviour is observable only by
  installing on ppc64le, deferred to #97.
- **Documents.** Mode: task-test-not-applicable; prose, held by `just check`'s Markdown lint.
