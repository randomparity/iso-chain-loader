# macOS Host Support Implementation Plan

Goal: make a macOS host a supported development environment and launcher-ISO build host while
leaving the manifest, ISO, launcher, and evidence contracts unchanged.

Architecture: the Python 3.14 standard-library CLI keeps every build decision. A uv-managed,
universally resolved development lock provisions the guardrail tools on macOS and Linux alike; four
host-sensitive paths become portable; a digest-pinned Fedora container image carries the
`grub2-mkrescue` and `xorriso` toolchain, and a new `container-build` subcommand runs the existing
`build` implementation inside it by composing one `docker run` argv.

Tech stack: Python 3.14 standard library, uv, just, POSIX shell with Bash 3.2 compatibility in the
test harness, a Fedora 44 container image, the Docker CLI, and GitHub Actions on `ubuntu-latest` and
`macos-latest`. No new Python runtime dependency.

Expected implementation size: 620–900 changed lines (M) — about 175 Python implementation and
focused tests, 60 shell-test and Justfile lines, 45 workflow lines, 25 container-definition lines,
and 225 documentation lines, plus the regenerated lock's mechanical churn. The frozen complexity is
M; the range is dominated by documentation and focused tests rather than by new runtime branching.

## Global Constraints

- Hosts that must work: macOS arm64 and Linux x86_64. The target architecture stays ppc64le, which
  is not a host. The declared interpreter is CPython 3.14 from `.python-version`.
- `uv` is required on a development host; `just` >= 1.57 stays required; the container path requires
  a `docker` command whose file sharing reaches the repository and every path argument.
- The lock stays hash-verified: `uv pip install --require-hashes` remains the only installation
  command, and `requirements-dev.in` remains the requested-tool list.
- No manifest field, canonicalization rule, ISO layout, kernel argument, launcher behavior, or
  evidence contract changes.
- `prepare-initramfs` keeps its `platform.machine() == "ppc64le"` gate; `smoke` and `install-fedora`
  keep their platform requirements; only `build` gains a container path.
- Public repository content stays free of host names, private paths, addresses, and credentials.
- Guardrails: `just check`; `.venv/bin/pre-commit run --all-files` before delivery.
- Container base: `fedora:44` pinned by digest
  `sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80` (resolved by
  `docker pull fedora:44` on 2026-09-11). Packages: `grub2-tools-extra`, `grub2-common`,
  `grub2-efi-aa64`, `grub2-ppc64le-modules`, `xorriso`, `python3.14`.
- CI keeps `permissions: contents: read` and pins every action by commit SHA:
  `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1),
  `extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3` (v4), and
  `astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4` (v10.1.0, both resolved 2026-09-11).
  uv is pinned to release `0.12.12`.

## Task 1: Bootstrap the development environment with uv

Files: modify `requirements-dev.lock`; modify `Justfile`.

### Interfaces

- `requirements-dev.lock` is consumed by `uv pip install --require-hashes` on every supported host
  and stays the only pinned artifact, with `requirements-dev.in` as its source.
- `just setup` consumes `uv`, `.python-version`, and `requirements-dev.lock`; it produces `.venv`
  containing `ruff`, `rumdl`, `detect-secrets`, and `pre-commit`, and installs `.githooks/pre-commit`
  into the resolved Git hooks path exactly as today.
- No check recipe changes: `check-python-lint`, `check-python-format`, `check-markdown`, and
  `check-secrets` keep invoking `.venv/bin/<tool>`.

### Verification

- Mode: focused-test — lock portability and provisioning; `just setup` installs the four tools from
  the universal lock on macOS arm64. Expected red: the current `setup` recipe builds `.venv` from
  the host `python3` (3.9 on macOS) and fails with
  `ERROR: Could not find a version that satisfies the requirement cfgv==3.5.0`. Green command:
  `just setup && .venv/bin/ruff --version && .venv/bin/rumdl --version && .venv/bin/detect-secrets --version`.
- Mode: focused-test — setup is repeatable; a second `just setup` exits 0. Expected red: `uv venv`
  without `--allow-existing` exits 2 with `A virtual environment already exists at: .venv`. Green
  command: `just setup; just setup; echo $?` printing `0`.

### Steps

1. Regenerate the lock:
   `uv pip compile --universal --generate-hashes --python-version 3.14 requirements-dev.in -o requirements-dev.lock`.
   Expected: exit 0; the regenerated header names the `--universal` command; `ruff`, `rumdl`,
   `detect-secrets`, and `pre-commit` each carry macOS arm64, macOS x86_64, and Linux x86_64 hashes.
2. Rewrite the `setup` recipe body, keeping the `#!/bin/sh` script form and `set -eu`: require
   `command -v uv` and exit 1 with `error: uv is required; install it from https://docs.astral.sh/uv/`
   when absent; run `uv venv --allow-existing --python 3.14 .venv`; run
   `uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock`; keep the
   existing `hook_path` comparison, its refusal message, and the `install -m 0755` line unchanged.
3. Run `just setup` twice and confirm both exit 0.
4. Run `just check-justfile` and `just check-python-lint`, then the three version commands in the
   focused verification entry. Expected: `just --fmt --check` passes, ruff reports
   `All checks passed!`, and the versions print `ruff 0.16.6`, `rumdl 0.2.66`, and the detect-secrets
   version.

Acceptance: `.venv` is provisioned by uv from the universal lock on macOS and Linux, the recipe is
idempotent, and no check command changed.
Rollback: restore the `setup` recipe and `requirements-dev.lock` from Git.

## Task 2: Publish directories portably and discover the macOS CA bundle

Files: modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`.

### Interfaces

- `_publish_directory(source: Path, destination: Path) -> None` keeps its signature and its
  `ValidationError` messages, and now selects the libc primitive by platform: `renameat2` with
  `RENAME_NOREPLACE` on Linux, `renamex_np` with `RENAME_EXCL` (`0x4`) on Darwin. Both branches map
  `EEXIST` to `output appeared during Fedora source preparation` and keep the
  `no-replace directory publication is unsupported` message for an unavailable or refusing
  primitive.
- `CA_BUNDLE_CANDIDATES` gains `/etc/ssl/cert.pem`; `prepare_initramfs` and the HTTPS source path in
  `validate_external_source` keep consuming the same tuple and the same failure message.

### Verification

- Mode: focused-test — publication on Darwin; `FedoraSourceTests` and `InstallTests` exercise
  successful publication, the no-replace race, and the unsupported-primitive error. Expected red on
  macOS: `ValidationError: no-replace directory publication is unsupported` from
  `test_publication_race_does_not_replace_destination` and four errors in
  `FedoraSourceTests`/`InstallTests`. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.FedoraSourceTests` and
  `tests.test_iso_chain.InstallTests -v`, all cases `ok`.
- Mode: focused-test — CA discovery; `PrepareTests` requires a system bundle for an HTTPS source.
  Expected red on macOS: `ValidationError: a system CA bundle is required for HTTPS sources`. Green
  command: `.venv/bin/python -m unittest tests.test_iso_chain.PrepareTests -v`, all cases `ok`.
- Mode: task-test-not-applicable — Linux `renameat2` behavior; the branch is untouched and its
  existing focused tests already cover it, so no new Linux-specific observation is added.

### Steps

1. Extend `_publish_directory` with a platform dispatch. On Darwin, resolve `renamex_np` from
   `ctypes.CDLL(None, use_errno=True)`, set `argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]`
   and `restype = ctypes.c_int`, and call it with `os.fsencode(source)`, `os.fsencode(destination)`,
   and the `RENAME_EXCL` constant; keep the existing `ctypes.get_errno()` mapping for `EEXIST`,
   `ENOSYS`, and `EINVAL`. On every other platform keep the current `renameat2` branch verbatim.
2. Add `/etc/ssl/cert.pem` to `CA_BUNDLE_CANDIDATES` ahead of the Linux paths.
3. Run both focused commands in the verification entries on macOS and retain the transition from
   red to green.
4. Run `.venv/bin/python -m unittest tests.test_iso_chain -v` and confirm no previously passing case
   changes status.

Acceptance: publication never replaces an existing destination on either supported host, the
Darwin branch reports the same messages as the Linux one, and the HTTPS source check accepts the
macOS system bundle.
Rollback: revert `scripts/iso_chain.py`; no test change belongs to this task.

## Task 3: Make the test suite pass on macOS

Files: modify `tests/test_iso_chain_launch.sh`; modify `tests/test_iso_chain.py`.

### Interfaces

- `write_fake_commands` installs fake `stat` and `sha256sum` beside the existing fakes, and the fake
  `curl` derives its URL without the Bash-4 `${!#}` expansion.
- The fake `stat` answers the two GNU forms the launcher uses — `stat -f -c '%a:%S' <dir>` and
  `stat -c '%s' <file>` — and returns `1:1` when `ISO_CHAIN_FAULT=space`, replacing its previous
  delegation to the host's `stat`.
- `EvidenceTests.test_tcpdump_is_bounded_captured_and_filters_dhcp_or_ipv6` compares
  `str(self.pcap.resolve())`, matching the resolved path `verify_pcap` passes through `_path`.
- The launcher under test and every existing assertion stay unchanged.

### Verification

- Mode: focused-test — launcher test portability; the suite runs under Bash 3.2. Expected red on
  macOS: `test failure: HTTPS artifact request was not preserved`, preceded by
  `run-space-check: failed`. Green command: `/bin/bash tests/test_iso_chain_launch.sh`, printing
  `launcher shell tests: passed` (the same command must stay green under Bash 5 on Linux).
- Mode: focused-test — capture-path assertion. Expected red on macOS: an assertion difference between
  `/var/folders/.../capture.pcap` and `/private/var/folders/.../capture.pcap`. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.EvidenceTests -v`, all cases `ok`.

### Steps

1. In `write_fake_commands`, replace `url=${!#}` with a capture of the last positional argument
   before the argument loop, using only POSIX shell syntax.
2. Replace the fake `stat` script body so it dispatches on its own arguments: for `-f` with a
   `-c '%a:%S'` form, print `1:1` when `ISO_CHAIN_FAULT=space` and a large fixed
   `blocks:block_size` value otherwise; for `-c '%s'`, print the byte size of its path argument with
   surrounding whitespace removed. Any other form exits 1. Update the `chmod` list to include the new
   fake `sha256sum`, and add that fake: it prints `<digest>  <path>`, using `/usr/bin/sha256sum`
   when that path is executable and `/usr/bin/shasum -a 256` otherwise, so the test never depends on
   host GNU coreutils.
3. Change the tcpdump assertion to the resolved path.
4. Run `/bin/bash tests/test_iso_chain_launch.sh` and
   `.venv/bin/python -m unittest discover -s tests -v` on macOS; expect
   `launcher shell tests: passed` and a fully passing suite.

Acceptance: the launcher test and the unit suite pass on macOS arm64 without host GNU coreutils and
under Bash 3.2, while every existing assertion still holds.
Rollback: revert both test files.

## Task 4: Add the pinned build container and `container-build`

Files: create `Containerfile`; modify `scripts/iso_chain.py`; modify `tests/test_iso_chain.py`;
modify `Justfile`.

### Interfaces

- `Containerfile` builds the `iso-chain-builder:44` image from the digest-pinned base and the six
  packages named in Global Constraints, and installs nothing else.
- `container_build_command(args: argparse.Namespace) -> list[str]` returns the exact `docker run`
  argv; `container_build(args: argparse.Namespace) -> None` resolves the engine, verifies the image
  exists, and calls `os.execvp`.
- New module constants: `CONTAINER_IMAGE = "iso-chain-builder:44"`,
  `CONTAINER_MODULE_DIRECTORY = "/usr/lib/grub/powerpc-ieee1275"`, `CONTAINER_PYTHON = "python3"`,
  and `REPOSITORY_ROOT = Path(__file__).resolve().parent.parent`.
- `parser()` gains `container-build` with required `--config`, `--kernel`, `--initramfs`, and
  `--output`, plus optional `--grub-modules`, `--engine` (default `docker`), and `--image` (default
  `CONTAINER_IMAGE`). `main()` dispatches it to `container_build`.
- `just build-image` runs `docker build --file Containerfile --tag iso-chain-builder:44 .`.

### Verification

- Mode: focused-test — argv composition in a new `ContainerBuildTests` class: every path argument is
  resolved to an absolute host path before composition; the repository tree is mounted read-only at
  its own path; one mount appears per distinct directory even when several arguments share it; the
  output directory's mount is read-write and wins over a read-only request for the same directory;
  `--grub-modules` is passed through when supplied and defaults to `CONTAINER_MODULE_DIRECTORY`
  otherwise; the inner command is `python3 <repo>/scripts/iso_chain.py build` with the build's own
  flags. Expected red: `container-build` is not a parser command. Green command:
  `.venv/bin/python -m unittest tests.test_iso_chain.ContainerBuildTests -v`, all cases `ok`.
- Mode: focused-test — rejections before execution: an unavailable engine, a missing image, a path
  containing a comma, the filesystem root as a mount source, an existing output path, and a missing
  input each raise `ValidationError` and never call `subprocess.run` for the container. Expected red:
  no such subcommand exists. Green command: the `ContainerBuildTests` command above.
- Mode: focused-test — end-to-end container build on this host (not part of `just check` and not in
  CI): build the image, then run
  `.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST --kernel KERNEL`
  `--initramfs INITRAMFS --output launcher.iso` against a fixture manifest whose kernel and
  initramfs digests match fixture files. Expected: exit
  0, a non-empty `launcher.iso`, and
  `.venv/bin/python scripts/iso_chain.py inspect launcher.iso` returning the canonical manifest JSON.
  Run `inspect` on a host with `xorriso`, or inside the built image.

### Steps

1. Write `Containerfile` with `FROM fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80`
   and one `RUN dnf --assumeyes --setopt=install_weak_deps=False install grub2-tools-extra
   grub2-common grub2-efi-aa64 grub2-ppc64le-modules xorriso python3.14 && dnf clean all`.
2. Add the constants and `container_build_command`, which validates inputs with the existing
   `_path` and `_regular_file` helpers, resolves the output to `resolved_parent/name`, rejects a
   comma-bearing mount source, the filesystem root, and an engine or image that does not resolve, and
   returns the argv. Compose mounts as `--mount type=bind,source=<dir>,target=<dir>[,readonly]`.
3. Add `container_build`, which resolves the engine with `shutil.which`, verifies the image with
   `subprocess.run([engine, "image", "inspect", image], check=False, capture_output=True)`, and
   execs the composed argv.
4. Wire `parser()` and `main()`, then add `just build-image` to the Justfile.
5. Add `ContainerBuildTests` covering the composition, the de-duplication rule, and each rejection,
   then run the focused commands to green.
6. Build the image and run the end-to-end container build and inspection from the verification
   entry, with fixtures kept in a private temporary directory.

Acceptance: `container-build` builds an ISO with the unchanged `build` implementation, imports
nothing outside the standard library, and fails before starting a container for every rejected
input.
Rollback: delete `Containerfile`, the three functions, the constants, the parser entry, the test
class, and the `build-image` recipe.

## Task 5: Run the guardrail suite on both CI hosts

Files: modify `.github/workflows/checks.yml`.

### Interfaces

- The workflow keeps one `checks` job, `permissions: contents: read`, and the same
  `just setup` then `just check` steps, now parameterized by a matrix of `ubuntu-latest` and
  `macos-latest`.
- `astral-sh/setup-uv` replaces `actions/setup-python` and supplies CPython 3.14 through its
  `python-version` input; `extractions/setup-just` and `actions/checkout` keep their pinned
  references.

### Verification

- Mode: task-test-not-applicable — the workflow's only consumer is GitHub Actions on GitHub-hosted
  runners; no repository-local executable observes it, and its observable contract (both runners
  running the same recipes to green) is established by the first workflow run for this branch, which
  Step 3 records.
- Mode: focused-test — the workflow stays parseable YAML while the file changes; expected red is a
  syntax error introduced by the edit. Green command:
  `.venv/bin/python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/checks.yml').read_text())"`
  printing nothing and exiting 0.

### Steps

1. Replace the `Set up Python` step with the pinned `astral-sh/setup-uv` step, passing
   `version: "0.12.12"`, `python-version: "3.14"`, and `enable-cache: true`.
2. Add `strategy: {fail-fast: false, matrix: {os: [ubuntu-latest, macos-latest]}}` to the `checks`
   job and set `runs-on: ${{ matrix.os }}`, leaving the checkout and setup-just steps unchanged.
3. Run the YAML parse command from the verification entry.
4. After the branch is pushed, confirm both jobs in the workflow run appear and pass, and record the
   run in the pull request.

Acceptance: one workflow definition runs the identical guardrail recipes on both hosts, and the
repository keeps its read-only CI permissions.
Rollback: restore the previous workflow file.

## Task 6: Document the macOS host path

Files: modify `README.md`; add `AGENTS.md` to version control and modify it.

### Interfaces

- README states the supported development hosts, the `uv` and `just` prerequisites, the unchanged
  `just setup` and `just check` contract, the `build-image` and `container-build` commands with a
  worked macOS example, and that `prepare-initramfs`, `smoke`, and `install-fedora` keep their
  ppc64le Linux or emulator requirements.
- `AGENTS.md` updates its host prerequisites, its uv and lock description, its development-command
  list, its CI description, and its subcommand list to match Tasks 1 through 5, and keeps every
  other statement as it stands.

### Verification

- Mode: task-test-not-applicable — prose readability; no executable assertion establishes that a
  human can follow the narrative, so review checks it against the already-executed commands while
  the Markdown guardrail checks structure, line length, and references to implemented interfaces.
- Mode: focused-test — documented commands exist; every command the new README section names
  resolves in `parser()` or the Justfile. Expected red: the `container-build` subcommand or the
  `build-image` recipe is absent, so its help or list command fails. Green commands:
  `scripts/iso_chain.py container-build --help` exiting 0 with a usage line, and `just --list`
  listing `build-image`.

### Steps

1. Update README's development section for the two supported host families, the uv prerequisite, and
   the unchanged check contract.
2. Add a macOS build subsection that names the image build command, the `container-build` example,
   the default module directory, and the path restrictions.
3. Update `AGENTS.md` to match, and stage it with `git add AGENTS.md`.
4. Run `just check` and `.venv/bin/pre-commit run --all-files`.

Acceptance: a macOS reader can provision the environment and build an ISO from the documented
commands alone, and no documented interface is absent from the implementation.
Rollback: revert both documents; `AGENTS.md` returns to untracked.
