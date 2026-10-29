# ADR 0034: Carry Operator Installer Configuration in the Manifest

## Status

Accepted (2026-10-29) — reviewed contract for #125 and #127 to #131; not implemented.

## Context

Epic #120 asks that operators embed their own Kickstart (Fedora, Rocky, RHEL) or autoinstall
user data (Ubuntu) on the launcher ISO, with the tool adding the fixed safety content. Today
Rocky, RHEL and Ubuntu answers are derived from fixed templates and the manifest's login values
(ADR 0019, 0020, 0031), customised only by presets (ADR 0032). Fedora stages an operator
`kickstart` artifact that `build` checks by size and digest but neither renders nor edits
(ADR 0021); that media keeps ADR 0018's `grubenv`-only menu (ADR 0025), so an interrupted install
can become the default and no installer-side blank-disk guard runs. Manifest v4 is the single
source of truth (`config_sha256`), `validate-config` reads no artifact (ADR 0029), and the code
has no YAML or Kickstart parser (stdlib only).

## Decision

- **Representation.** Operator configuration is inline text in the profile: optional
  `operator_kickstart` on `fedora`, `rocky` and `rhel` profiles and `operator_user_data` on
  `ubuntu` profiles, each a JSON string holding the file's exact text. `openSUSE` accepts
  neither. A Fedora profile carries exactly one of `kickstart` and `operator_kickstart`. The
  manifest digest therefore binds the operator bytes; ADR 0029 and the `prepare-*-source`
  commands are unchanged.
- **Operator mode.** A manifest with any operator field is in operator mode. Every profile must
  then carry one; an Ubuntu operator manifest has exactly one profile, because NoCloud user data
  sits at the ISO root (ADR 0020). Operator mode refuses `login_user`, `ssh_authorized_keys` and
  `install`, so it never coexists with derived templates or presets.
- **Ownership.** The operator file owns users, keys, passwords, privileges, root, host name,
  installed network, partitioning, packages, the end action, and any installer network or source
  it adds. The launcher's source, network and digest contracts end at the `kexec` handoff of the
  composed file. ADR 0017 and ADR 0023 govern the manifest's login values and derived answers
  only. The implementing PR (#125) updates the `AGENTS.md` binding-contract bullets for login
  values, privileges, no fallbacks and digest-checked installer content to say so.
- **Composition.** `build` composes the staged file deterministically. A Kickstart becomes a
  fixed `%pre --erroronfail` guard (ADR 0018's single-blank-disk check), then the operator text
  unchanged, then a fixed final `%post --erroronfail` that sets `iso_chain_installed=1` in
  `/boot/grub2/grubenv`; Anaconda runs each kind of script in file order, so the guard runs
  first and the marker last. User data is `#cloud-config` followed by one JSON object parsed with
  `json`, every decoded string and number held to the field's character and finiteness rules;
  build prepends the shipped template's guard to `autoinstall.early-commands`, appends
  its marker to `autoinstall.late-commands`, and re-serialises as ADR 0020 does.
- **Binding.** The composed file's size and SHA-256 ride the kernel command line through the
  existing `profile_kickstart_*` and `profile_user_data_*` arguments, so the launcher, its log
  verifier and the evidence verifiers recompute them from the manifest alone.
- **Menu.** `_grub_config` selects `COMPLETION_MENU` when the manifest is keyed or in operator
  mode. This extends ADR 0021's scope beyond keyed media and narrows ADR 0025's unkeyed rule to
  manifests without operator fields. ADR 0021's statement that `build` neither renders nor edits
  a Fedora Kickstart stays true of the `kickstart` artifact only.
- **Fedora compatibility.** Injection is opt-in through `operator_kickstart`. A manifest without
  operator fields, Fedora `kickstart` artifacts included, produces byte-identical staged files,
  kernel arguments and `grub.cfg`.

Specification:
[Operator installer configuration](../workflow/specs/2026-10-29-operator-installer-configuration-design.md).

## Consequences

- Operators author a file and embed it with one documented `jq --rawfile` command; the manifest,
  ISO and evidence record each carry the text, so it is private as the manifest is.
- The tool cannot see credentials or policy inside operator text. A password hash there is the
  operator's choice and is published with the ISO; tool-defined fields stay credential-free.
- hmcpctl's built mode, which always forwards login values (ADR 0017), cannot use operator mode.
- JSON escaping inflates text inside the 2 MiB manifest bound; a file that no longer fits is
  refused, never truncated.
- Operator-mode evidence proves that the composed file reached its marker and that GRUB handed
  off to the disk, not that the installed system boots or logs in; it keeps the existing traffic
  rules, so a file that fetches outside the manifest source cannot produce passing evidence.
- A file that ends in power-off, or fails before its marker, boots back into the launcher, whose
  guard refuses the non-blank disk. A file without a GRUB bootloader still gets the marker, so
  GRUB hands off to a missing `grub.cfg` and stops with an error.
- `prepare-fedora-source` still requires `--kickstart`; operator mode replaces that field.

## Considered & rejected

- **A digest-pinned artifact file, as Fedora's `kickstart`.** judgment: cost; it needs an ADR 0029
  amendment, three `prepare-*-source` ingest options and new verifier inputs to bind what the
  manifest digest already binds, the second-file cost ADR 0017 rejected.
- **Ubuntu user data as a JSON object in the manifest.** judgment: fit; one text grammar for both
  kinds keeps the field byte-equal to the file the operator tests and diffs, though build
  re-serialises the composed copy.
- **YAML user data.** verified: `python3 -c 'import importlib.util as u;
  print(u.find_spec("yaml"))'` prints `None` (Python 3.9.6, macOS, 2026-10-29); the stdlib has no
  YAML parser, and textual splicing into YAML is unsafe.
- **Apply manifest login values by injecting `user`/`sshkey` lines or a user entry.**
  judgment: fit; build would edit operator-owned accounts, the layering #120 excludes.
- **Inject into every Fedora `kickstart` artifact.** verified: the fixture
  `assets/kickstart/fedora-44-power9.ks` ends in `poweroff` and masks `serial-getty@hvc0`
  (`cat`, 30acf8c), and injection changes every existing Fedora ISO digest and menu.
- **Check operator text for a marker or guard instead of injecting.** judgment: fit; ADR 0025
  rejects it, since a text match cannot show a command runs, or runs last.
- **Place the guard at the end of the Kickstart.** judgment: fit; an operator `%pre` would then
  run before the guard and could write the disk.
- **Allow operator profiles beside interactive or derived ones.** judgment: complexity; one menu
  serves the whole ISO (ADR 0021), so a profile without the marker would never become default.
- **Validate Kickstart syntax at build.** verified: the same probe for `pykickstart` prints
  `None` there and under `.venv/bin/python -I` (Python 3.14.3); Anaconda refuses bad syntax at
  install, visibly.
- **Do nothing.** judgment: fit; #120 goal 3 stays unmet and Fedora operator files keep no guard.
