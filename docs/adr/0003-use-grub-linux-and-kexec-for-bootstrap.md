# ADR 0003: Use GRUB, Linux, and kexec for Bootstrap

## Status

Proposed

## Context

The ppc64le ISO needs an optical entry point compatible with POWER Open Firmware and a runtime
capable of eventually selecting and loading remote installation kernels. Issue #3 asks only for a
minimum feasibility experiment and a grounded stack decision. Native POWER9 PowerVM hardware is not
available; a POWER9-mode QEMU pSeries VM can test the architecture and interfaces but not PowerVM
firmware policy or VIOS mapping.

## Decision

Propose a `powerpc-ieee1275` GRUB image for optical bootstrap, a Linux initramfs for the future
selection runtime, and Linux `kexec` for the second-kernel transition. The issue #3 implementation
supplies a narrow experiment builder, a network-disabled QEMU smoke runner, and a boot-log verifier.
It does not implement the future selection runtime.

The experiment accepts operator-supplied ppc64le kernel, initramfs, GRUB module directory, root
arguments, disk image, and output paths. It always adds `console=hvc0 rd.neednet=0 ip=off`, rejects
conflicting network arguments and multiline GRUB input, refuses to overwrite output, runs QEMU with
`-nic none` and `-snapshot`, and reports only fixed evidence results rather than raw log content.

The redacted experiment report is the acceptance evidence for this decision. Its disposition is
determined by the following outcomes:

| Experiment outcome | Decision disposition |
| --- | --- |
| Optical handoff and authenticated second-kernel transition pass | Change this ADR to Accepted. |
| Optical handoff fails | Record the precise gap and leave this ADR Proposed or revise the firmware bridge. |
| `kexec` load or transition fails | Record the precise gap and leave this ADR Proposed or revise the runtime boundary. |
| A required artifact or tool is unavailable | Record the precise gap and leave this ADR Proposed. |

## Consequences

GRUB owns only the firmware-to-Linux handoff. Linux supplies device and future protocol support;
`kexec` is the boundary to the selected installer. The same relocatable ppc64le ELF kernel can prove
both stages in the experiment. The VM proves SLOF optical loading and ppc64le `kexec`, not native
POWER9 PowerVM boot, Secure Boot compatibility, or firmware-policy preservation. A later authorized
LPAR run must close those gaps before the stack is called hardware-proven.

## Considered & rejected

- **Bundle Petitboot as the experiment runtime.** verified: the upstream Petitboot README describes
  it as a Linux-and-kexec bootloader and QEMU's pSeries documentation describes VOF as ideal for it;
  bundling that existing application duplicates the smaller Linux/kexec feasibility boundary and
  does not prove the PowerVM optical path.
- **Use GRUB as the full selection and network runtime.** judgment: GRUB is a good firmware bridge,
  but placing future distribution discovery and operator interaction in its constrained environment
  couples product behavior to the bootloader.
- **Wait for a native LPAR before selecting any stack.** judgment: this would discard independently
  testable Open Firmware, ppc64le, and kexec evidence even though the issue explicitly allows a
  precise feasibility-gap report.
- **Do nothing.** judgment: repository documentation alone cannot reproduce or distinguish the
  optical handoff and second-kernel transition.
