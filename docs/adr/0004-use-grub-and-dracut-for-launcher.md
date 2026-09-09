# ADR 0004: Use GRUB and Dracut for the Launcher

## Status

Accepted

## Context

Issue #4 needs a ppc64le ISO that embeds per-LPAR static IPv4 configuration, selects a launcher
profile automatically or through a console menu, and fails before network activity when its
configuration or adapter identity is unusable. ADR 0003 already assigns the optical handoff to
GRUB, the runtime to Linux, and the eventual installer transition to kexec.

The operator asked us to investigate iPXE before implementing a custom runtime. Current iPXE has
HTTP, scripting, and menu support but no PowerPC architecture backend or ppc64le IEEE1275 build
target. Petitboot supplies a POWER-oriented Linux/kexec runtime, but its POWER integration is aimed
at OPAL and reads configuration from NVRAM or IPMI rather than a read-only per-ISO manifest.

## Decision

Keep GRUB as the optical menu and use a small repository-owned dracut hook as the Linux launcher.
The hook delegates device discovery and lifecycle to dracut and uses its installed networking
tools only after an exact MAC match is established. It configures static IPv4, routes, and optional
DNS, performs one bounded HTTP probe, and emits fixed evidence markers. It includes and invokes no
DHCP client.

A versioned JSON manifest is the per-LPAR contract. The host builder validates and canonicalizes it,
embeds it in the ISO, and converts it to restricted kernel arguments. GRUB creates one entry per
allowed profile and selects the configured default after a visible timeout. A ppc64le environment
builds one generic kernel/initramfs payload, which all per-LPAR ISOs reuse.

## Consequences

The change reuses the existing POWER optical path and dracut environment without carrying an iPXE
port, Petitboot fork, or new Python dependency. The repository owns a small amount of shell glue,
so its fail-closed adapter and network behavior needs focused tests and packet-capture evidence.
The launcher payload must be prepared on ppc64le; an x86_64 host cannot substitute its binaries.

GRUB remains a menu and handoff layer, not the installer download runtime. The HTTP probe establishes
bootstrap reachability only. Issue #5 still owns verified installer artifacts and the kexec handoff.

## Considered & rejected

- **Use iPXE.** verified: the upstream source tree at commit
  `ff6e52063e0b37062394fe37b9788af25175e7af` has architecture directories for ARM, x86, RISC-V,
  LoongArch, and s390x, but none for PowerPC; adoption would require a bootloader port.
- **Use Petitboot.** verified: upstream commit `96063aa2d2d8795389024d05967c3f4bcbbf9aab`
  provides MAC-based static configuration, HTTP, menus, and kexec, but documents its POWER platform
  for OPAL and sources POWER configuration from NVRAM/IPMI. Adapting immutable ISO configuration
  would require a maintained integration patch and a larger runtime dependency set.
- **Implement networking directly in GRUB.** judgment: GRUB supports static addresses, routes, HTTP,
  and menus, but making it own adapter policy and downloads contradicts ADR 0003's Linux runtime
  boundary and makes runtime diagnostics harder to test.
- **Write a standalone initramfs runtime.** judgment: duplicating dracut's device lifecycle and image
  construction adds code without improving the required behavior.
- **Do nothing.** judgment: the issue's configuration, selection, and network evidence do not exist.
