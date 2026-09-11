# ADR 0008: Build the Launcher ISO in a Pinned Linux Container

## Status

Accepted

## Context

`build` stages the ISO payload and calls `grub2-mkrescue`, which drives `xorriso` internally. Both
are Linux packaging artifacts, and the module directory they consume must carry
`powerpc-ieee1275` modules for the ppc64le target. Issue #21 asks for ISO build support on macOS,
where neither tool is installed and where the repository's only declared build host, x86_64 Linux,
may not be available.

## Decision

Ship a `Containerfile` at the repository root and a `container-build` subcommand that runs the
unchanged `build` implementation inside that image.

- The image is based on `fedora:44` pinned by digest and installs `grub2-tools-extra` (which
  provides `/usr/sbin/grub2-mkrescue`), `grub2-tools` (which provides `/usr/share/grub/unicode.pf2`
  and `grub2-mkimage`), `grub2-common`, `grub2-ppc64le-modules` (the packaged `powerpc-ieee1275`
  module set), `xorriso`, and `python3.14`.
- `container-build` composes and executes one `docker run` argv. The repository tree is mounted
  read-only at its own absolute path, each input path's directory is mounted read-only at its own
  absolute path, the output path's directory is mounted read-write, and the default
  `--grub-modules` is the image's `/usr/lib/grub/powerpc-ieee1275`. Absolute host paths are
  preserved inside the container, so no argument is rewritten.
- `just build-image` builds the tagged image; `container-build` requires it to exist and names the
  build command in its error when it does not.

## Consequences

- macOS and Linux hosts run the same Python implementation over the same class of module set; only
  the host executing it differs.
- The wrapper's host prerequisites are a `docker` command and file sharing that reaches the
  repository, the kernel, the initramfs, the manifest, and the output directory. Docker's `--mount`
  syntax cannot express a path containing a comma, so such a path is rejected before any container
  starts.
- The base image is digest-pinned; the packages installed inside it are resolved by `dnf` from the
  Fedora release repositories at image-build time. Their versions and the built image's own digest
  are recorded nowhere, so the toolchain is trusted locally rather than verified. Per-run
  `--grub-modules` keeps the target module set explicit and lets an operator substitute one.
- `prepare-initramfs`, `smoke`, and `install-fedora` are not containerized and keep their existing
  platform requirements.

## Considered & rejected

- **Install the ppc64le GRUB image tooling natively on macOS.** verified: `brew info grub` reports
  `Error: No available formula with the name "grub"` (Homebrew on macOS 26, 2026-09-11). judgment:
  no other packaged source of `powerpc-ieee1275` GRUB image tooling for macOS is known to exist.
- **Install only `xorriso` natively and reuse a module directory.** verified: `brew info xorriso`
  resolves (xorriso 1.5.8.pl02, bottled, macOS 26, 2026-09-11), so xorriso alone is available — but
  `build` calls `grub2-mkrescue`, which that formula does not provide.
- **Use a generic community build image and install the tools at run time.** judgment: it makes
  every build depend on repository availability and a mutable remote tag, and it moves the toolchain
  out of the reviewable diff.
- **Build on a remote Linux host or VM.** judgment: it adds an operator-provisioned external
  service and a file transfer to what is otherwise a local build step.
- **Publish a prebuilt builder image to a registry.** judgment: it adds a supply-chain surface to a
  repository whose other artifacts are digest-verified, for a tool that only needs to exist on the
  build host.
- **Pin each RPM's version and release inside the image.** judgment: version-release pins rot as
  the Fedora release repositories advance and break `docker build` for a tool image; the residual
  trust is stated under Consequences instead of being papered over by a pin.
