# Operator configuration foundation plan

Issue: #125, under epic #120. Contract: [ADR 0034](../../adr/0034-carry-operator-installer-configuration-in-the-manifest.md)
and the [operator installer configuration spec](../specs/2026-10-29-operator-installer-configuration-design.md).
Excluded and owned elsewhere: Rocky/RHEL staging (#127), Ubuntu staging (#128), Fedora staging
(#129), harness and verifiers (#130), live proof (#131), guides and support-matrix rows.

## Sequencing decision (no distribution staged yet)

`_profile_kickstart` and `_profile_user_data` stay as they are: in operator mode they see no
`login_user` and return nothing, and a Fedora operator profile has no `kickstart` artifact. Media
built from an operator manifest would therefore stage no installer answers and, for Fedora, omit
the Kickstart arguments the launcher requires. So `_configuration_manifest`, which `validate-config`,
`build` and `container-build` share, composes each operator profile's text (renderability) and
then refuses every profile whose distribution is not in `OPERATOR_STAGED_DISTRIBUTIONS`, which is
empty here. The refusal is a fixed reason naming the field path and ADR 0034. #127, #128 and #129
each wire their distribution's staging and add it to that set. `load_manifest_bytes` still accepts
operator manifests, so `inspect`, target composition and evidence readers parse them.
`_install_evidence` refuses a profile carrying operator text with a fixed reason until #130 wires
the verifiers, because a Fedora operator profile has no `kickstart` artifact to check.

## Tasks

1. **Field and grammar.** `InstallerProfile` gains `operator_text: str | None = None`.
   `_installer_profile` accepts optional `operator_kickstart` (fedora, rocky, rhel) or
   `operator_user_data` (ubuntu); Fedora requires exactly one of `kickstart` and
   `operator_kickstart`; openSUSE accepts neither (unknown field). `_operator_text` refuses a
   non-string, unencodable UTF-8, 0 or more than 1 MiB of bytes, a refused character and a missing
   final LF, each with `profiles.<profile>.<field>: <fixed reason>`.
   Verify: `ManifestV4Tests` grammar cases, including that no reason echoes a canary in the text.
2. **Operator-mode rules.** In `load_manifest_bytes`, after the profiles parse: if any profile
   carries text, every profile must, `operator_user_data` needs exactly one profile, and
   `login_user`, `ssh_authorized_keys` and `install` are refused, naming ADR 0034. The media-path
   uniqueness loop needs no change: operator mode admits no `kickstart` artifact.
   Verify: rules 1-4 in `ManifestV4Tests`, including a v1 target request carrying login values and
   a v2 preset request over an operator base.
3. **Round trip.** `_manifest_data` writes the text under the distribution's field name.
   Verify: `_canonical_bytes(_manifest_data(m))` equals the canonical bytes for each kind.
4. **Kickstart composition.** `_operator_kickstart(text) -> bytes` returns the fixed `%pre` guard
   (header, ADR comment, the Rocky template's `%pre` lines from `set -eu` through the `done` that
   closes the zero check, `%end`), the text unchanged, and the fixed `%post` marker; more than
   1 MiB raises `composed Kickstart exceeds 1 MiB`.
   Verify: exact guard and marker bytes, operator bytes unchanged between them, bound.
5. **User-data composition.** `_operator_user_data(text, field) -> bytes` requires the
   `#cloud-config\n` prefix and one JSON object parsed with duplicate-key, constant and
   non-integer refusals; walks decoded keys and strings under the character rule; refuses a mapping
   key longer than 1,000 characters as `json.dumps` writes it (YAML limits implicit keys to 1,024)
   and nesting deeper than 64 levels (PyYAML's parser recurses per level); requires exactly
   the `autoinstall` object key, with `early-commands`/`late-commands` arrays when present;
   prepends the template guard and appends the template marker; serialises as
   `_ubuntu_user_data` does; more than 1 MiB raises `composed user data exceeds 1 MiB`. Every
   grammar failure, including `RecursionError`, is one fixed reason.
   Verify: `UbuntuUserDataTests` cases for each refusal, injected positions and deterministic
   bytes.
6. **Menu.** `_grub_config` uses `COMPLETION_MENU` when `login_user` is set or any profile carries
   operator text. Verify: an operator manifest's `grub.cfg` holds the completion menu.
7. **Validate-config and build gate.** As in the sequencing decision; invalid or operator input
   spawns no external command and the error omits the text. Verify: `OfflineValidationTests` CLI
   runs with a canary and `BuildTests` asserting `grub2-mkrescue` is not called.
8. **Byte identity.** Unit suites keep their existing pinned `grub.cfg`, kernel-argument and staging
   assertions; a one-off script compares `grub.cfg`, kernel arguments, canonical bytes and staged
   files for every `examples/*.json` and the factory manifests between `main` and the branch.
9. **AGENTS.md.** Update the login, privilege, derived-content and `grubenv`-only bullets to state
   that they govern the manifest's login values and derived answers, that operator fields refuse
   them, and that operator-mode manifests select the completion menu.

## Guardrails

`just check`, `just check-tests`, `just check-markdown`. No media build or boot: build refuses
operator mode, and existing media is unchanged by the byte-identity check.
