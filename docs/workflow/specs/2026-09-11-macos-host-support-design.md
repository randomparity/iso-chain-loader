# macOS Host Support Design

Issue: [#21](https://github.com/randomparity/iso-chain-loader/issues/21)

Decision: [ADR 0008](../../adr/0008-build-launcher-iso-in-linux-container.md),
[ADR 0009](../../adr/0009-manage-development-environment-with-uv.md),
[ADR 0010](../../adr/0010-portable-no-replace-publication.md)

## Problem

The repository declares an x86_64 Linux development host. On macOS `just setup` builds `.venv` from
the host `python3`, which is 3.9 there, and then installs a lock resolved only for CPython 3.14 on
Linux x86_64, so no development tool is installed at all. `just check` cannot pass either: the lock
pins Linux-only `ruff` and `rumdl` artifacts, `_publish_directory` needs Linux `renameat2`, HTTPS
source validation looks for Linux CA bundles, the Bash launcher test uses a Bash-4 expansion and
delegates GNU `stat` to the host, and one unit test compares an unresolved `/var` path. `build` then
shells out to `grub2-mkrescue` and `xorriso`, which macOS does not provide for
`powerpc-ieee1275`.

## Scope and architecture

The change is additive and host-facing. It replaces the development-environment bootstrap, makes
four host-sensitive paths portable, and adds one build path for hosts that cannot install the Linux
media toolchain. It changes no manifest field, no ISO layout, no kernel argument, no launcher
behavior, and no evidence contract.

### Development environment

`requirements-dev.in` remains the requested-tool list and `requirements-dev.lock` remains the only
pinned artifact, regenerated as a universal uv lock (ADR 0009). `just setup` becomes
`uv venv --allow-existing --python 3.14 .venv`, then
`uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock`, then the
existing Git-hook installation. `uv` joins `just` as a documented host prerequisite, and
`.python-version` keeps declaring the interpreter version for both.

### Host-portable primitives

- `_publish_directory` gains a Darwin branch calling `renamex_np(..., RENAME_EXCL)`; Linux keeps
  `renameat2`, and both map `EEXIST` to the existing "output appeared" message (ADR 0010).
  Publication therefore never replaces an existing destination on either supported host.
- `CA_BUNDLE_CANDIDATES` gains macOS's `/etc/ssl/cert.pem`, so the existing HTTPS-source check
  accepts a real system bundle on Darwin without a new failure mode.
- The Bash launcher test stops depending on host GNU tools: its fake `stat` answers the launcher's
  GNU-form `stat -f -c '%a:%S'` and `stat -c '%s'` calls itself, a fake `sha256sum` produces the
  digest the launcher compares, and the fake `curl` reads its last argument without the Bash-4
  `${!#}` expansion. The test's assertions and the launcher under test are unchanged.
- The tcpdump unit test compares the resolved capture path, which is the form the implementation
  passes on every platform.

### Container build path

A `Containerfile` at the repository root defines the build image from a digest-pinned `fedora:44`
base with `grub2-tools-extra`, `grub2-common`, `grub2-efi-aa64`, `grub2-ppc64le-modules`, `xorriso`,
and `python3.14`. `scripts/iso_chain.py` gains `container-build`, which composes and executes one
`docker run` argv for the unchanged `build` implementation: the repository is mounted read-only at
its own absolute path, each input path's directory is mounted read-only at its own absolute path,
the output directory is mounted read-write, and `--grub-modules` defaults to the image's
`/usr/lib/grub/powerpc-ieee1275`. Every path argument is resolved to an absolute host path before
composition, and composition performs no shell interpretation. `just build-image` builds and tags
the image.

### Continuous integration

`.github/workflows/checks.yml` runs the same `just setup` and `just check` on a matrix of
`ubuntu-latest` and `macos-latest`. uv replaces the separate Python setup step and is pinned by
release, as are the actions, which keep `permissions: contents: read`.

### Documentation

README and `AGENTS.md` record the supported hosts, the uv prerequisite, the image and
`container-build` recipe, and the unchanged platform limits of `prepare-initramfs`, `smoke`, and
`install-fedora`.

## Success

- On macOS arm64 and on Linux x86_64, `just setup` installs the same pinned tool set and `just check`
  exits 0.
- On a macOS host with a `docker` command, `container-build` produces a launcher ISO from the same
  inputs the `build` command consumes, and the resulting image's embedded manifest parses back to
  the canonical manifest bytes.
- CI runs the guardrail suite on both an Ubuntu and a macOS runner.
- No manifest, ISO, launcher, kernel-argument, or evidence contract changes, and every existing
  focused test keeps its existing assertions except where a platform-specific path comparison is
  corrected.

## Validation

- `bash tests/test_iso_chain_launch.sh` prints `launcher shell tests: passed` under both Bash 3.2
  and Bash 5.
- `.venv/bin/python -m unittest discover -s tests -v` passes on macOS arm64 and Linux x86_64.
- `just check` passes on both CI runners.
- A new focused test class covers `container-build` argv composition: absolute-path resolution,
  mount de-duplication with the output directory winning, the default module directory, rejection
  of a comma-bearing path, and rejection of the filesystem root as a mount source.
- The container path is exercised end to end on this host with the image built from the
  `Containerfile`, a fixture manifest, fixture kernel and initramfs files, and the image's packaged
  `powerpc-ieee1275` modules; `inspect` must then return the canonical manifest. This run is
  recorded in the pull request and is not part of CI.

## Failure model

1. **Actors and deployments** — A local operator at a terminal on macOS or Linux runs `just setup`,
   `just check`, and `container-build`; a CI job on a GitHub-hosted Ubuntu or macOS runner runs
   `just setup` and `just check`. No other deployment is supported by this change.
2. **Invariants and assets at stake** — The ISO build inputs (kernel, initramfs, module directory,
   manifest) and the published output remain byte-exact and no-replace; the dependency lock remains
   hash-verified; the CI job remains read-only against repository content; the container cannot
   reach a path the operator did not name.
3. **Accepted failure classes** — A macOS host without a `docker` command cannot build an ISO: the
   container is the only supported macOS build mechanism (ADR 0008), and the failure is an explicit
   command-not-found error raised before any container starts. Rebuilding the image after Fedora
   repository updates changes the toolchain: accepted, because the produced ISO's integrity is bound
   by the manifest's own digests. Hosts other than macOS and Linux remain unsupported. First-use
   image builds are slower than later ones: accepted and bounded by the operator's own build step.
4. **Covered elsewhere** — ppc64le execution, emulator runs, and native POWER9 evidence stay with
   issue #6 and the epic's platform work; `prepare-initramfs`, `smoke`, and `install-fedora` keep
   their existing host requirements and are unchanged here.

## Threat model

1. **Boundary inventory** — Added: the container runtime boundary, where a host command is executed
   inside a Linux image, and the image content boundary, where a digest-pinned base plus Fedora
   packages become the build toolchain. Widened: the build host's dependency surface gains a
   container runtime, and CI gains one pinned action and one additional runner. No boundary is added
   that faces an untrusted network peer.
2. **Actor model** — The trusted actors are the local operator and the CI job. The operator owns
   every path the container mounts. No untrusted party supplies input to `container-build`: its
   arguments are operator-supplied paths, and the manifest, kernel, initramfs, and module directory
   are validated by the existing `build` code inside the container exactly as they are today.
3. **Control per boundary** — The image is pinned by base digest, and the CI actions by commit SHA.
   Path arguments are resolved, then checked for existence, for a comma, and against the filesystem
   root before composition, and the argv is executed without a shell, so no path value can become a
   command. Mounts are read-only except the output directory. The CI job keeps
   `permissions: contents: read`, and the dependency lock keeps `--require-hashes`.
4. **Explicitly out of scope** — The contents of the Fedora packages inside the image are trusted
   through the digest-pinned base and Fedora's own repositories. The security of the host's
   container runtime and its file-sharing configuration is the operator's platform, not this
   change. The runtime behavior of the produced ppc64le media remains covered by the existing
   emulator and LPAR evidence paths.
