# SSH Keys and Login User Implementation Plan

Goal: accept `ssh_authorized_keys` and `login_user` in `iso-chain-target-v1` requests and manifest
v4, bind them by the manifest digest, and refuse to build media with them until a profile applies
them. Spec: `docs/workflow/specs/2026-10-02-login-values-design.md`; ADR 0017.

Architecture: two optional root fields validated in `load_manifest_bytes`, copied through by
`compose_target_manifest`, modelled on `Manifest`, emitted by `_manifest_data`, refused by
`_build_manifest`. No guest, kernel-argument, or producer-result change.

Tech stack: Python 3.14 standard library; stdlib `unittest`.

Expected implementation size: 170–240 changed lines (M) — two code tasks of about 50 source and
120 test lines, plus README, ADR 0015, and AGENTS.md edits.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function.
- Raise `ValidationError`; messages never contain the submitted value.
- Bounds exactly as hmcpctl: 1 to 16 keys; each key 1 to 8,192 characters and
  `str.isprintable()`; `login_user` fullmatches `[a-z_][a-z0-9_-]{0,31}`.
- `.secrets.baseline` records line numbers; if `just check-secrets` fails, refresh only line
  numbers. Key fixtures use the low-entropy text `ssh-ed25519 AAAA test-key` to avoid detection.

## File map

- `scripts/iso_chain.py` — owner of request composition, manifest validation, and build gating;
  extended, no owner change.
- `tests/test_iso_chain.py` — `TargetRequestTests`, `ManifestV4Tests`, `BuildTests`,
  `ContainerBuildTests`, `InstallerEvidenceTests`, `InspectTests` cases.
- `README.md`, `docs/adr/0015-emit-a-target-bound-producer-result.md` (consequence line only),
  `AGENTS.md`.

## Task 1: Validate, compose, and model the fields

Files: modify `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: produces `Manifest.ssh_authorized_keys: tuple[str, ...]`, `Manifest.login_user: str |
None`, constant `LOGIN_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")`, `MAX_KEYS = 16`,
`MAX_KEY_LENGTH = 8192`, helpers `_login(root: dict[str, object]) -> tuple[tuple[str, ...], str |
None]` and `_canonical_bytes(data: object) -> bytes` (the existing `json.dumps(...,
ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"`).
Consumes existing `_manifest_error`, `_manifest_object`, `_read_manifest_bytes`.

Verification:

- Mode: focused-test. Contract: bounds and no-echo. Test
  `ManifestV4Tests.test_login_values_are_optional_bounded_and_not_echoed`; red: `unknown field`
  for a valid pair. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests`.
- Mode: focused-test. Contract: canonical round trip and unchanged keyless digest. Same test
  asserts `_manifest_data` re-serialization equals the canonical bytes for a non-ASCII key and
  that `manifest_data()` canonical bytes contain neither field name.
- Mode: focused-test. Contract: composition copies both fields. Test
  `TargetRequestTests.test_composes_login_values`; red: `unknown field`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.TargetRequestTests`.
- Mode: focused-test. Contract: 2 MiB bound. Update the three `64 KiB` tests to write
  `iso_chain.MAX_MANIFEST_BYTES + 1` bytes and expect `exceeds 2 MiB`. Add
  `TargetRequestTests.test_accepts_maximal_escaped_request`: write with `json.dumps` defaults a
  request holding sixteen keys of `"\U0001f600" * 8192` and `login_user="core"`, compose and load
  it, and assert the sixteen keys round-trip. Red: `target file: exceeds 64 KiB`.
- Mode: focused-test. Contract: `verify_installer_evidence` reads manifests up to 2 MiB. Add
  `InstallerEvidenceTests.test_reads_manifest_above_64_kib`: patch
  `scripts.iso_chain._read_evidence_file` with a wrapper recording `(label, maximum)` and raising
  `ValidationError("stop")` after the manifest read; assert the manifest maximum equals
  `iso_chain.MAX_MANIFEST_BYTES`. Red: recorded maximum is 65536. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.InstallerEvidenceTests`.
- Mode: focused-test. Contract: `verify_launcher_log` digest parity. The round-trip assertion calls
  `iso_chain._canonical_bytes(iso_chain._manifest_data(manifest))`, the exact expression
  `verify_launcher_log` uses after this task, and compares it with the loaded canonical bytes for a
  non-ASCII key. Red: `_canonical_bytes` does not exist.

Steps:

1. Write the tests. The manifest test loads `manifest_data(ssh_authorized_keys=[KEY, "ssh-ed25519
   AAAA ключ"], login_user="core")`, asserts the model values and round trip, then loops over
   invalid cases with `assertRaisesRegex` on the field name and `assertNotIn("opaque-login",
   message)`: keys without user, user without keys, `[]`, 17 keys, `"x"` (not a list), `[7]`,
   `[""]`, `["a" * 8193]`, `["opaque-login\nb"]`, `["opaque-login "]`, users `"Opaque-login"`,
   `"0opaque"`, `"a" * 33`, `7`, `"opaque-login\n"`.
2. Run the focused commands; expect the red failures named above.
3. Implement: the constants; `MAX_MANIFEST_BYTES = 2 * 1024 * 1024` and message `exceeds 2 MiB`;
   `optional=frozenset({"operation_binding", "ssh_authorized_keys", "login_user"})` for both the
   target request and the manifest root; in `compose_target_manifest`, copy each of the three
   optional fields present in the request; `_login` validating in the spec's order; the two
   `Manifest` fields; `_manifest_data` emitting both when `login_user is not None`;
   `ensure_ascii=False` in `verify_launcher_log`'s `json.dumps`.
   Replace `64 * 1024` with `MAX_MANIFEST_BYTES` for the manifest read in
   `verify_installer_evidence`; make `load_manifest_bytes` return `_canonical_bytes(data)` and
   `verify_launcher_log` compute `canonical = _canonical_bytes(_manifest_data(manifest))`.
4. Run the focused commands and `just check-tests`; expect `OK` and `launcher shell tests:
   passed`. Commit `feat: accept SSH keys and a login user in manifest v4`.

## Task 2: Refuse builds that carry the values

Files: modify `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: consumes `Manifest.login_user` from Task 1; changes `_build_manifest(args:
argparse.Namespace) -> tuple[Manifest, bytes, str]` behaviour only.

Verification:

- Mode: focused-test. Contract: refusal before any external command. Tests
  `BuildTests.test_refuses_login_values_before_grub` and
  `ContainerBuildTests.test_refuses_login_values_before_engine`. The build test patches
  `scripts.iso_chain.subprocess.run`, expects `no installer profile applies them yet`, and asserts
  `run.assert_not_called()`; red: the grub2-mkrescue mock is called. The container test calls
  `container_build_command` and expects the same message; red: no `ValidationError` is raised. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests
  tests.test_iso_chain.ContainerBuildTests`.

Steps:

1. Write both tests using the class's existing `args` builder with a config or target carrying
   `ssh_authorized_keys` and `login_user`.
2. Run; expect the red observation.
3. In `_build_manifest`, after loading, raise `ValidationError("login_user and
   ssh_authorized_keys: no installer profile applies them yet (ADR 0017)")` when
   `loaded[0].login_user is not None`.
4. Run the focused command and `just check-tests`; commit `feat: refuse media carrying login values
   until a profile applies them`.

## Task 3: Documentation

Files: `README.md`, `docs/adr/0015-emit-a-target-bound-producer-result.md`, `AGENTS.md`.

Verification:

- Mode: task-test-not-applicable. Surface: prose in README, ADR 0015's consequence line, and
  AGENTS.md. Reason: no executable consumer reads these files; `just check-markdown` checks only
  formatting.

Steps:

1. README "Target-bound media for hmcpctl": replace "SSH keys and a login user are not accepted
   yet." with the two fields, their bounds, that the manifest digest binds them, and that `build`
   refuses them until #24/#25; note the 2 MiB request bound.
2. ADR 0015 consequence line: state that ADR 0017 accepts both fields and that `build` refuses them
   until a profile applies them.
3. AGENTS.md: list the optional fields beside `operation_binding`, the 2 MiB bound, seventeen ADRs
   (0001–0017), and ADR 0017 under Important Files.
4. Run `just check`; expect exit 0. Commit `docs: describe SSH key and login user fields`.
