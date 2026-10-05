# ADR 0025: Keep the `grubenv`-Only Installed-Disk Rule on Unkeyed Media

## Status

Accepted

## Context

ADR 0021 requires `iso_chain_installed=1` in the found `grubenv` only on keyed media, whose install
answers `build` renders, and records that an unkeyed ISO still boots an interrupted install's disk
by default when the installer wrote `grubenv`. Issue #62 asks whether unkeyed media should also
require a marker, in particular unkeyed Fedora media, whose Kickstart the operator writes.

- `build` refuses login values unless every profile is Rocky or every profile is Ubuntu
  (`scripts/iso_chain.py`, `build`), so a Fedora or openSUSE ISO is always unkeyed, and an unkeyed
  ISO may carry several distributions' profiles.
- `_grub_config` chooses one menu per ISO from `manifest.login_user`; the search cannot tell which
  profile installed the disk it finds.
- A Fedora profile's Kickstart is operator bytes that `build` stages after checking their size and
  digest; it does not parse or render them. The repository's Fedora Kickstarts are fixtures.
- Both fixtures write the `iso-chain-installed` service in their only `%post`, and
  `verify-fedora-install-evidence` requires its `installed-boot: passed` line, so an emulator
  install interrupted before `%post` already fails verification.
- Fedora disks installed from unkeyed media exist without a marker: the QEMU runs and the PowerVM
  test partition of [the PowerVM record](../experiments/2026-10-01-powervm-iso-carried-kickstart.md).

## Decision

- **Scope.** An ISO without login values keeps ADR 0018's rule: any disk with a `grubenv` in the
  four searched directories is the menu default. ADR 0021's consequence for unkeyed Fedora, Rocky,
  Ubuntu, and openSUSE media is accepted as stated; `_grub_config`, the assets, and the launcher are
  unchanged.
- **Reason.** On unkeyed media the ISO cannot promise the marker: interactive installs are
  answered at the console, and a Fedora Kickstart is the operator's. Requiring the marker there
  would send every finished install whose answers lack it back to the installer entry, which the
  guard refuses: a fault on the ordinary path traded for one on the interrupted path. Either way
  the blank-disk guard refuses to reinstall over the interrupted disk, so the gap affects which
  system boots, not whether data is overwritten.
- **Reconsideration.** If `build` comes to render a Fedora or openSUSE profile's install answers
  from login values, that media is keyed, and ADR 0021 requires the marker without a new decision.

## Consequences

- An unkeyed install interrupted after its installer wrote `grubenv` boots that disk by default;
  the operator sees the incomplete system or its boot failure, and reinstalls by zeroing the
  disk's first and last MiB.
- This decision leaves the menu unchanged for disks already installed from unkeyed media: ADR
  0018's rule still selects them, and nothing needs migrating. Booting the PowerVM test disk
  through the ISO's GRUB is unproven (hmc-mcp#1230).
- The Fedora fixtures, the media digest of every unkeyed ISO, and `grub.cfg` are unchanged.

## Considered & rejected

- **Require the marker on unkeyed media whose profiles are all Fedora.** judgment: fit; `build`
  cannot check that an operator Kickstart sets the marker last, so a Kickstart without it would
  lose the installed-disk default on every finished install, and the menu would gain a third
  selection rule. Existing Fedora disks, all test artifacts, would need ADR 0021's `grub2-editenv`
  remedy; that cost alone, accepted for keyed Rocky media, would not sink it.
- **Require the marker on every unkeyed ISO.** judgment: fit; rejected by ADR 0021, because no
  interactive installer writes it.
- **Refuse an unkeyed Fedora Kickstart that lacks a marker command.** judgment: fit; a text match
  on operator bytes cannot show that the command runs, or runs last.
- **Add a manifest field that opts unkeyed media into the marker.** judgment: complexity; a new
  manifest contract that no operator has asked for.
- **Do nothing: close issue #62 with a pointer to ADR 0021.** judgment: fit; ADR 0021 rejects only
  the every-ISO rule and gives no reason why the unkeyed gap is acceptable or when to revisit it.

Specification: [Unkeyed completion marker](../workflow/specs/2026-10-04-unkeyed-completion-marker-design.md).
