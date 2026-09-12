# macOS Host Support Implementation Plan

Goal: make a macOS host a supported development environment and launcher-ISO build host while
leaving the manifest, ISO, launcher, and evidence contracts unchanged.

Architecture: the Python 3.14 standard-library CLI keeps every build decision. The unchanged
hash-pinned development lock, installed by uv, provisions the guardrail tools on macOS and Linux
alike; four host-sensitive paths become portable; a digest-pinned Fedora image carries the GRUB and
`xorriso` toolchain, and a new `container-build` subcommand runs the existing `build` implementation
inside it by composing one `docker run` argv.

Tech stack: Python 3.14 standard library, uv, just, POSIX shell with Bash 3.2 compatibility in the
test harness, a Fedora 44 container image, the Docker CLI, and GitHub Actions on `ubuntu-latest` and
`macos-latest`. No new Python runtime dependency.

Expected implementation size: 560–680 changed lines (M) — file map: 120 in `scripts/iso_chain.py`,
140 in `tests/test_iso_chain.py`, 30 in `tests/test_iso_chain_launch.sh`, 15 in `Containerfile`, 10
in `Justfile`, 20 in the workflow, 45 in `README.md`, and about 255 for `AGENTS.md` (211 adopted
lines plus edits). The `AGENTS.md` adoption is mechanical; the ≈380 hand-written lines are the basis
for the frozen M band. `requirements-dev.lock` is unchanged.

## Global Constraints

- Hosts that must work: macOS arm64 and Linux x86_64. The target architecture stays ppc64le, which
  is not a host. The declared interpreter is CPython 3.14 from `.python-version`.
- `uv` release `0.12.12` is the verified development toolchain and what CI pins; `just` >= 1.57
  stays required; the container path requires a `docker` command whose file sharing reaches the
  repository and every path argument.
- The lock stays hash-verified: `uv pip install --require-hashes` remains the only installation
  command, `requirements-dev.in` remains the requested-tool list, and
  `requirements-dev.lock` is unchanged by this change.
- No manifest field, canonicalization rule, ISO layout, kernel argument, launcher behavior, or
  evidence contract changes.
- `prepare-initramfs` keeps its `platform.machine() == "ppc64le"` gate; `smoke` and `install-fedora`
  keep their platform requirements; only `build` gains a container path.
- Public content stays free of host names, private paths, addresses, usernames, and credentials,
  including what this plan's verification steps record publicly.
- Guardrails: `just check`; `.venv/bin/pre-commit run --all-files` before delivery.
- Container base: `fedora:44` pinned by digest
  `sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80` (resolved by
  `docker pull fedora:44` on 2026-09-11). Packages: `grub2-tools-extra`, `grub2-tools`,
  `grub2-common`, `grub2-ppc64le-modules`, `xorriso`, `python3.14`.
- CI keeps `permissions: contents: read` and pins every action by commit SHA:
  `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1),
  `extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3` (v4),
  `astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4` (v10.1.0, resolved 2026-09-11).

## Task 1: Bootstrap the development environment with uv

Files: modify `Justfile`.

### Interfaces

- The unchanged `requirements-dev.lock` stays the only pinned artifact and is consumed on every
  supported host by `uv pip install --require-hashes`; `requirements-dev.in` stays its source.
- `just setup` consumes `uv`, `.python-version`, and that lock; it produces `.venv` containing
  `ruff`, `rumdl`, `detect-secrets`, and `pre-commit`, and installs `.githooks/pre-commit` into the
  resolved Git hooks path exactly as today. The check recipes keep invoking `.venv/bin/<tool>`.

### Verification

- Mode: focused-test — provisioning on macOS; `just setup` installs the four tools from the
  unchanged lock. Expected red: the current recipe builds `.venv` from the host `python3` (3.9 on
  macOS) and fails with `ERROR: Could not find a version that satisfies the requirement
  cfgv==3.5.0`. Green command: `just setup && .venv/bin/ruff --version && .venv/bin/rumdl --version
  && .venv/bin/detect-secrets --version`, printing 0.16.6, 0.2.66, and 1.5.0.
- Mode: focused-test — repeatability; a second `just setup` exits 0. Expected red: `uv venv` without
  `--allow-existing` exits 2 with `A virtual environment already exists at: .venv`. Green command:
  `just setup; just setup; echo $?` printing `0`.

### Steps

1. Rewrite the `setup` recipe body, keeping the `#!/bin/sh` script form and `set -eu`: require
   `command -v uv` and exit 1 with `error: uv 0.12.12 or a compatible release is required` when
   absent; run `uv venv --allow-existing --python 3.14 .venv`; run
   `uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock`; keep the
   existing `hook_path` comparison, its refusal message, and the `install -m 0755` line unchanged.
2. Run `just setup` twice, then `just check-justfile` and `just check-python-lint`. Expect exit 0
   twice, `just --fmt --check` passing, and ruff reporting `All checks passed!`.

Acceptance: `.venv` is provisioned by uv from the unchanged lock on macOS and Linux, the recipe is
idempotent, and no check command changed.
Rollback: restore the `setup` recipe from Git.

## Task 2: Publish directories portably and discover the macOS CA bundle

Files: modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`.

### Interfaces

- `_publish_directory(source: Path, destination: Path) -> None` keeps its signature and messages and
  selects `renameat2` with `RENAME_NOREPLACE` on Linux or `renamex_np` with `RENAME_EXCL` (`0x4`) on
  Darwin. Both branches map `EEXIST` to `output appeared during Fedora source preparation` and keep
  `no-replace directory publication is unsupported` for an unavailable or refusing primitive.
- `CA_BUNDLE_CANDIDATES` gains `/etc/ssl/cert.pem`; its two consumers keep the same tuple and
  failure message.

### Verification

- Mode: focused-test — Darwin publication; `FedoraSourceTests` and `InstallTests` cover successful
  publication, the no-replace race, and the unsupported-primitive error. Expected red on macOS:
  `ValidationError: no-replace directory publication is unsupported` from
  `test_publication_race_does_not_replace_destination` plus four errors in those two classes. Green
  commands: `.venv/bin/python -m unittest tests.test_iso_chain.FedoraSourceTests -v` and
  `.venv/bin/python -m unittest tests.test_iso_chain.InstallTests -v`, all cases `ok`.
- Mode: focused-test — CA discovery; `PrepareTests` requires a system bundle for an HTTPS source.
  Expected red on macOS: `ValidationError: a system CA bundle is required for HTTPS sources`. Green
  command: `.venv/bin/python -m unittest tests.test_iso_chain.PrepareTests -v`, all cases `ok`.
- Mode: task-test-not-applicable — Linux `renameat2` behavior; that branch is untouched and its
  existing focused tests already cover it.

### Steps

1. Extend `_publish_directory` with a platform dispatch. On Darwin, resolve `renamex_np` from
   `ctypes.CDLL(None, use_errno=True)`, set `argtypes = [ctypes.c_char_p, ctypes.c_char_p,
   ctypes.c_uint]` and `restype = ctypes.c_int`, and call it with `os.fsencode` of both paths and the
   `RENAME_EXCL` constant, keeping the existing `ctypes.get_errno()` mapping for `EEXIST`, `ENOSYS`,
   `EINVAL`, and `ENOTSUP`. Every other platform keeps the current `renameat2` branch verbatim.
2. Append `/etc/ssl/cert.pem` to `CA_BUNDLE_CANDIDATES` after the Linux candidates, so a Linux host
   keeps its existing preference.
3. Run the three focused commands on macOS and retain the transition from red to green, then run
   `.venv/bin/python -m unittest tests.test_iso_chain -v` and confirm no passing case changes status.

Acceptance: publication never replaces an existing destination on either supported host, the Darwin
branch reports the same messages as the Linux one, and the HTTPS source check accepts the macOS
system bundle.
Rollback: revert `scripts/iso_chain.py`; no test change belongs to this task.

## Task 3: Make the test suite pass on macOS

Files: modify `tests/test_iso_chain_launch.sh`; modify `tests/test_iso_chain.py`.

### Interfaces

- The shell harness exports `LC_ALL=C` before running the launcher, so it sees the locale the guest
  initramfs uses rather than the developer host's; the launcher validates hex and identifier grammar
  with bracket ranges whose matching follows the locale.
- `write_fake_commands` also installs fake `stat` and `sha256sum`. The fake `stat` answers
  `stat -f -c '%a:%S' <dir>` and `stat -c '%s' <file>` from its own arguments, returns `1:1` when
  `ISO_CHAIN_FAULT=space`, and strips the padding `wc -c` prints on BSD systems. The fake `sha256sum`
  prints `<digest>  <path>` through `/usr/bin/sha256sum` or `/sbin/sha256sum` when either exists and
  `/usr/bin/shasum -a 256` otherwise, so the harness does not depend on which SHA-256 tool the host
  exposes.
- `EvidenceTests.test_tcpdump_is_bounded_captured_and_filters_dhcp_or_ipv6` compares
  `str(self.pcap.resolve())`, the form `verify_pcap` passes through `_path`.
- The launcher under test, the fake `curl`, and every existing assertion stay unchanged.

### Verification

- Mode: focused-test — harness portability under Bash 3.2 on macOS and Bash 5 on Linux, and under a
  UTF-8 host locale. Expected red on macOS with the host locale: first `run-space-check: failed`
  (the delegated BSD `stat`), then, once the fakes exist,
  `test failure: invalid Kickstart argument missed fixed marker` from the uppercase-digest case the
  launcher wrongly accepts under the host locale. Green commands:
  `/bin/bash tests/test_iso_chain_launch.sh` and `env LC_ALL=en_US.UTF-8 /bin/bash
  tests/test_iso_chain_launch.sh`, both printing `launcher shell tests: passed`.
- Mode: focused-test — capture-path assertion. Expected red on macOS: a difference between
  `/var/folders/.../capture.pcap` and `/private/var/folders/.../capture.pcap`. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.EvidenceTests -v`, all cases `ok`.

### Steps

1. Add `export LC_ALL=C` after `set -euo pipefail`, commented with the reason above.
2. Replace the fake `stat` body so it dispatches on its own arguments: for `-f` with a `-c` format,
   print `1:1` when `ISO_CHAIN_FAULT=space` and a large fixed `blocks:block_size` otherwise; for `-c`
   with format `%s`, print the byte count of `${3}` with `wc -c` padding removed; any other form exits
   1.
3. Add the fake `sha256sum` with the two absolute-path probes above, and add it to the existing
   `chmod` list.
4. Change the tcpdump assertion to the resolved path.
5. Run both green commands above and `.venv/bin/python -m unittest discover -s tests -v`.

Acceptance: the launcher test and the unit suite pass on macOS arm64 without host GNU coreutils,
under Bash 3.2, and independent of the host locale, while every existing assertion still holds.
Rollback: revert both test files.

## Task 4: Add the pinned build container and `container-build`

Files: create `Containerfile`; modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`;
modify `Justfile`.

### Interfaces

- `Containerfile` builds the `iso-chain-builder:44` image from the digest-pinned base and the six
  packages in Global Constraints, and installs nothing else.
- `container_build_command(args) -> list[str]` returns the exact `docker run` argv described in ADR
  0008; `container_build(args) -> None` resolves the engine, verifies the image, and calls
  `os.execvp`.
- New constants: `CONTAINER_IMAGE = "iso-chain-builder:44"`,
  `CONTAINER_MODULE_DIRECTORY = "/usr/lib/grub/powerpc-ieee1275"`, `CONTAINER_PYTHON = "python3"`,
  `REPOSITORY_ROOT = Path(__file__).resolve().parent.parent`.
- `parser()` gains `container-build` with required `--config`, `--kernel`, `--initramfs`, and
  `--output`, plus optional `--grub-modules`, `--engine` (unset means detect `podman` then `docker`,
  later extended), and `--image` (default `CONTAINER_IMAGE`); `main()` dispatches it to
  `container_build`.
- `just build-image` builds `iso-chain-builder:44` from the repository `Containerfile`.

### Verification

- Mode: focused-test — argv composition in a new `ContainerBuildTests`: every path argument is
  resolved to absolute before composition; the repository is mounted read-only at its own path; one
  mount appears per distinct directory when several arguments share one; the output directory's mount
  is read-write and wins over a read-only request for the same directory; `--grub-modules` is passed
  through when supplied and defaults to `CONTAINER_MODULE_DIRECTORY` otherwise; the inner command is
  `python3 <repo>/scripts/iso_chain.py build` with the build's own flags. Expected red:
  `container-build` is not a parser command. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.ContainerBuildTests -v`, all cases `ok`.
- Mode: focused-test — rejections before execution: an unavailable engine, a missing image, a
  comma-bearing path, the filesystem root as a mount source, an existing output path, and a missing
  input each raise `ValidationError` and never call `subprocess.run` for the container. Green command:
  the `ContainerBuildTests` command above.
- Mode: focused-test — end-to-end build on a macOS host, not part of `just check` and not in CI. After
  `just build-image`, run `.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST
  --kernel KERNEL --initramfs INITRAMFS --output launcher.iso` against a fixture manifest whose
  kernel and initramfs digests match fixture files, expecting exit 0 and a non-empty ISO. Then run
  `docker run --rm --mount type=bind,source=<repo>,target=<repo>,readonly --mount
  type=bind,source=<iso-dir>,target=<iso-dir> iso-chain-builder:44 python3
  <repo>/scripts/iso_chain.py inspect <iso-dir>/launcher.iso`, expecting the canonical manifest JSON.
  Record publicly only the exit status, the ISO's SHA-256, and whether the inspection matched.

### Steps

1. Write `Containerfile` with
   `FROM fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80` and one
   `RUN dnf --assumeyes --setopt=install_weak_deps=False install grub2-tools-extra grub2-tools
   grub2-common grub2-ppc64le-modules xorriso python3.14 && dnf clean all`.
2. Add the constants and `container_build_command`: validate inputs with the existing `_path` and
   `_regular_file` helpers, resolve the output to `resolved_parent/name`, reject a comma-bearing mount
   source, the filesystem root, an existing output, and an engine or image that does not resolve, and
   return the argv with mounts composed as
   `--mount type=bind,source=<dir>,target=<dir>[,readonly]`.
3. Add `container_build`: resolve the engine with `shutil.which`, verify the image with
   `subprocess.run([engine, "image", "inspect", image], check=False, capture_output=True)`, and exec
   the composed argv.
4. Wire `parser()` and `main()`, then add `just build-image` to the Justfile.
5. Add `ContainerBuildTests` covering composition, the de-duplication rule, and each rejection, and
   run the focused commands to green.
6. Build the image and run the end-to-end build and inspection, keeping fixtures in a private
   temporary directory and recording only the bounded evidence named above.

Acceptance: `container-build` builds an ISO with the unchanged `build` implementation, imports
nothing outside the standard library, and fails before starting a container for every rejected input.
Rollback: delete `Containerfile`, the constants, the three functions, the parser entry, the test
class, and the `build-image` recipe.

## Task 5: Run the guardrail suite on both CI hosts

Files: modify `.github/workflows/checks.yml`.

### Interfaces

- One `checks` job, `permissions: contents: read`, and the same `just setup` then `just check` steps,
  parameterized by a matrix of `ubuntu-latest` and `macos-latest`.
- `astral-sh/setup-uv` replaces `actions/setup-python` and supplies CPython 3.14 through its
  `python-version` input; `extractions/setup-just` and `actions/checkout` keep their pinned
  references.

### Verification

- Mode: task-test-not-applicable — the workflow's only consumer is GitHub Actions on GitHub-hosted
  runners, and no repository-local executable observes it, so its observable contract is the first
  workflow run for this branch, recorded in Step 3.
- Mode: focused-test — the workflow stays parseable YAML; expected red is a syntax error introduced
  by the edit. Green command: `.venv/bin/python -c "import pathlib, yaml;
  yaml.safe_load(pathlib.Path('.github/workflows/checks.yml').read_text())"` printing nothing.

### Steps

1. Replace the `Set up Python` step with the pinned `astral-sh/setup-uv` step, passing
   `version: "0.12.12"`, `python-version: "3.14"`, and `enable-cache: true`.
2. Add `strategy: {fail-fast: false, matrix: {os: [ubuntu-latest, macos-latest]}}` to the `checks`
   job and set `runs-on: ${{ matrix.os }}`, leaving the checkout and setup-just steps unchanged.
3. Run the YAML parse command, and after the branch is pushed confirm both matrix jobs passed,
   recording only the runner names and the exit status.

Acceptance: one workflow definition runs the identical guardrail recipes on both hosts, and the
repository keeps its read-only CI permissions.
Rollback: restore the previous workflow file.

## Task 6: Document the macOS host path

Files: modify `README.md`; add `AGENTS.md` to version control and modify it.

### Interfaces

- README states the supported hosts, the `uv` release and `just` prerequisites, the unchanged
  `just setup` and `just check` contract, the `build-image` and `container-build` commands with a
  worked macOS example, the writable-directory requirement for inspecting an ISO, and that
  `prepare-initramfs`, `smoke`, and `install-fedora` keep their ppc64le Linux or emulator
  requirements.
- `AGENTS.md` is updated wherever Tasks 1 through 6 invalidate it: the host prerequisites, the uv
  and lock description, the development-command list, the CI description, the subcommand list, the
  ADR list and count, the test-class list and count, the fake-command list, the specs/plans
  date-slug count, and the container-build entry. Statements this change does not invalidate stay.

### Verification

- Mode: task-test-not-applicable — prose readability; no executable assertion establishes that a
  human can follow the narrative, so review checks it against the already-executed commands while the
  Markdown guardrail checks structure, line length, and references to implemented interfaces.
- Mode: focused-test — documented commands exist; every command the new README section names resolves
  in `parser()` or the Justfile. Expected red: the `container-build` subcommand or the `build-image`
  recipe is absent, so its help or list command fails. Green commands:
  `.venv/bin/python scripts/iso_chain.py container-build --help` exiting 0 with a usage line (the
  bare `scripts/iso_chain.py` entry point runs the host `python3`, which is 3.9 on macOS), and
  `just --list` listing `build-image`.

### Steps

1. Update README's development section for the two supported host families, the uv prerequisite, and
   the unchanged check contract.
2. Add a macOS build subsection naming the image build command, the `container-build` example, the
   default module directory, the inspection command with its writable directory, and the path
   restrictions.
3. Update `AGENTS.md` to match and stage it with `git add AGENTS.md`.
4. Run `just check` and `.venv/bin/pre-commit run --all-files`.

Acceptance: a macOS reader can provision the environment and build an ISO from the documented
commands alone, and no documented interface is absent from the implementation.
Rollback: revert both documents; `AGENTS.md` returns to untracked.
