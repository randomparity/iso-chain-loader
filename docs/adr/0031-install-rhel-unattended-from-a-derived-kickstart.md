# ADR 0031: Install RHEL Unattended From a Build-Derived Kickstart

## Status

Accepted

## Context

ADR 0028 added interactive `rhel` profiles (RHEL 9.0 to 10.2) and left login values refused for
them "until an unattended profile exists". Issue #79 asks for that profile. ADR 0019 derives a
Kickstart for Rocky from the manifest's keys, login user, and network; ADR 0021 adds the
completion marker; ADR 0017 refuses login values unless every profile applies them. The launcher
already accepts an optional Kickstart for Rocky and builds RHEL's arguments from Rocky's. RHEL's
BaseOS `.treeinfo` names no AppStream, so the launcher passes `inst.addrepo=AppStream,...` (ADR
0028). Two questions were open: whether one template serves RHEL 9 and 10, and whether the
Kickstart or the launcher declares the repositories.

## Decision

- **Trigger.** A `rhel` profile in a manifest that carries `ssh_authorized_keys` and `login_user`
  installs unattended; without them it keeps ADR 0028's interactive handoff and kernel command
  line. The profile grammar does not change.
- **Derivation.** `build` renders the RHEL Kickstart exactly as ADR 0019 renders Rocky's: the same
  generated lines, then the fixed template `assets/kickstart/rhel-unattended.ks`, staged as
  `/profiles/<profile>/ks.cfg` with its path, size, and SHA-256 on the kernel command line.
  The template is Rocky's with the volume group named `rhel`; both the RHEL 9 and RHEL 10
  pykickstart grammars accept it, and no per-minor check was made, so one template serves RHEL 9.0
  to 10.2. It uses only `text`, `lang`, `keyboard`, `timezone`, `rootpw`, `firstboot`, `selinux`,
  `firewall`, `network`, `user`, `sshkey`, `bootloader`, `part`, `volgroup`, `logvol`, `zerombr`,
  `clearpart`, `ignoredisk`, `%include`, `%packages`, `%pre`, `%post` and `reboot`. Rocky's template
  and bytes do not change.
- **Repositories.** The Kickstart carries no `repo` line. The launcher's `inst.repo` and
  `inst.addrepo=AppStream,...` stay the only source declarations, and `verify_launcher_log` keeps
  checking exactly those. The launcher adds `inst.ks=cdrom:LABEL=...` before `inst.repo`.
- **Login rule.** `build` and `container-build` refuse login values unless every profile is
  `rocky` or `rhel`, or every profile is `ubuntu`. Keyed media may carry Rocky and RHEL profiles
  together; each profile stages its own Kickstart. Fedora and openSUSE stay refused.
- **Unchanged.** The login user has no administrative access (ADR 0023), the completion marker and
  menu follow ADR 0021, and the disk guard, network keyfile, and root lock follow ADR 0019.

Specification: [RHEL unattended install](../workflow/specs/2026-10-16-rhel-unattended-install-design.md).

## Consequences

- Built-mode RHEL media installs over a blank disk with no prompt; its ISO digest changes with
  keys, user, and network as Rocky's does.
- **Unverified: Anaconda on RHEL.** The template is checked only against pykickstart's grammar and
  by unit tests. No RHEL release was installed from it, and whether each release honours
  `inst.addrepo` beside `inst.ks` is untested. The QEMU `install-rhel` harness and its evidence
  verifier are follow-up issue #97, so the install has no recorded proof.
- **RHEL 10 on POWER9** carries ADR 0028's caveat: a profile that renders is not a statement that
  the release supports the host.
- Subscription registration is not configured; packages come from the unpinned BaseOS and AppStream
  mirror (ADR 0013, ADR 0028).
- A change to the shared parts of the Rocky and RHEL templates must be made in both files; a test
  pins the RHEL template to Rocky's apart from its header and volume group lines.

## Considered & rejected

- **One template per RHEL major.** verified: `ksvalidator -v RHEL9` and `ksvalidator -v RHEL10`
  (pykickstart 3.78, throwaway venv on macOS arm64, 2026-10-16) both accepted the rendered Rocky
  Kickstart with its `%include` replaced by a concrete disk file. This checks grammar only, not
  Anaconda.
- **Point the RHEL profile at Rocky's template file.** judgment: fit; the file is named for Rocky
  9.8 and sets `volgroup rocky`, and Rocky's bytes must not change.
- **A Kickstart `repo` line for BaseOS and AppStream.** judgment: fit; it would declare a second
  source beside `inst.repo`, and `verify_launcher_log` and the access-log rules check one.
- **Refuse Rocky and RHEL profiles on one keyed ISO.** judgment: complexity; every profile applies
  the values, so the refusal would be a rule with no purpose.
- **Do nothing.** judgment: fit; hmcpctl's built mode stays refused for RHEL.
