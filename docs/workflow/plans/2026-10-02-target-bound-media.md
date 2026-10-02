# Target-Bound Installation Media Plan

**Goal:** let hmcpctl build launcher media from a per-partition target request and check an
`iso-chain-media-v1` producer result (spec `2026-10-02-target-bound-media-design.md`, ADR 0015).

**Architecture:** `build` composes a manifest v4 from a target request and a base manifest, then
runs the existing build, publishes by digest name, and prints one canonical result line.
`container-build` validates and forwards the same inputs; `inspect --result` reuses the result
writer for prepared media.

**Tech stack:** Python 3.14 standard library only; stdlib `unittest`.

Expected implementation size: 350–450 changed lines (M) — about 160 in `scripts/iso_chain.py`,
170–250 in tests, 20–40 in README and AGENTS.md.

## Global Constraints

- Python 3.14; `scripts/` imports the standard library only; ruff line length 100.
- Every function annotated; `ValidationError` messages name fields and never echo values.
- Input validation fails before any `subprocess` call; tests assert `run.assert_not_called()`.
  The one post-build failure is an existing publish destination.
- No existing file is replaced: `os.link`, with `FileExistsError` raised as
  `ValidationError("output appeared during build")` (today's message, kept for both modes).
- Guardrails: the focused command per task while iterating; `just check` (about 7 s) before each
  commit, which runs the shell launcher test and the whole unittest suite.

## File Map

- `scripts/iso_chain.py` — owns parsing, composition, build, result, inspect, and CLI. Each change
  extends the function that already owns the behavior; no ownership move.
- `tests/test_iso_chain.py` — `ManifestV4Tests`, new `TargetRequestTests`, `BuildTests`,
  `ContainerBuildTests`, `InspectTests`.
- `README.md`, `AGENTS.md` — new flags, request and result formats, operator cleanup.

Existing names this plan relies on, confirmed in `scripts/iso_chain.py`: `_manifest_object(value,
fields, field)`, `_read_manifest_bytes(path)`, `_object_pairs`, `_identifier(value, field)`,
`_validate_source(value)`, `_file_sha256(path)`, `_path(value, label, kind)`,
`_manifest_data(manifest)`, `load_manifest`, `load_manifest_bytes`, `build_iso(args)`,
`container_build_command(args, engine)`, `inspect_iso(path)`, `REPOSITORY_ROOT`, `Manifest`.
Test helpers: `manifest_data`, `rocky_profile`, `ubuntu_profile`, `write_profile_tree`.

## Task 1: Optional `operation_binding` in manifest v4

### Verification

- Contract: optional, exact, digest-covered binding, and `_manifest_data` round-trip. Mode:
  focused-test. `ManifestV4Tests.test_operation_binding_is_optional_and_exact`; red:
  `manifest root: unknown field`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests`.

**Interfaces:** produces `OPERATION_BINDING = re.compile(r"^[0-9a-f]{32}$")`,
`Manifest.operation_binding: str | None = None` (last field), and
`_manifest_object(value, fields, field, optional: frozenset[str] = frozenset())`.

1. Write the test. Assert: an unbound manifest has `operation_binding is None`; a manifest with
   `operation_binding="0" * 32` parses, its canonical bytes contain the field, and its digest
   differs from the unbound one; `json.dumps(iso_chain._manifest_data(bound), sort_keys=True,
   separators=(",", ":")).encode() + b"\n"` equals the bound canonical bytes; `"A" * 32`,
   `"0" * 31`, `7`, and `"opaque-binding-value"` each raise `ValidationError` whose text does not
   contain `opaque-binding-value`.
2. Run the green command; expect the red.
3. Implement: `_manifest_object` rejects `value.keys() - fields - optional`; the root passes
   `optional=frozenset({"operation_binding"})`; a present binding that is not a `str` matching
   `OPERATION_BINDING` fails `_manifest_error("operation_binding", "must be 32 lower-case hex
   digits")`; pass it to `Manifest`; `_manifest_data` emits it when not `None`.
4. Run the green command and `just check`; commit `feat: accept an optional operation binding`.

## Task 2: Compose a manifest from a target request

### Verification

- Contract: request plus base yields a one-profile manifest selected by distribution and release.
  Mode: focused-test. `TargetRequestTests.test_composes_one_profile_manifest`; red:
  `AttributeError: ... compose_target_manifest`.
- Contract: shape and selection rejections without echo, and the target size bound. Mode:
  focused-test. `TargetRequestTests.test_rejects_bad_requests_without_echo`; same red. Green for
  both: `.venv/bin/python -m unittest -v tests.test_iso_chain.TargetRequestTests`.

**Interfaces:** consumes Task 1. Produces `TARGET_FORMAT = "iso-chain-target-v1"`,
`_read_manifest_bytes(path, label: str = "manifest")` (its messages become `f"{label} file:
..."`), `_json_document(path: Path, label: str) -> object`, and
`compose_target_manifest(target: Path, base: Path) -> bytes` (JSON for `load_manifest_bytes`).

1. Add module test helpers. `target_request(**changes)` returns `{"format":
   "iso-chain-target-v1", "profile": "rocky-9.8", "lpar": "sys-r1", "mac": "52:54:00:12:34:56",
   "network": <manifest_data()["network"] without "mac">, "operation_binding": "0" * 32}` updated
   by `changes`. `base_manifest()` returns `{"version": 4, "source": "http://10.0.2.2:8000",
   "profiles": {"rocky": rocky_profile(), "ubuntu": ubuntu_profile()}}`.
2. Write the tests in `TargetRequestTests` (a temp dir with `target.json` and `base.json`, and a
   `compose(request)` helper returning `load_manifest_bytes(compose_target_manifest(...))`):
   - composes: profiles are exactly `["rocky"]`, `selected_profile == "rocky"`, the MAC and
     binding carry over; without `operation_binding` the binding is `None`.
   - rejects, each without echoing `opaque-request-value`: `format` other than
     `iso-chain-target-v1`; `profile` `"fedora-44"` (no match); an extra `ssh_authorized_keys`
     field; a bad address; a bad MAC; an upper-case `lpar`; `"ubuntu-26.04.1"` with three DNS
     servers; a base with two profiles of the same distribution and release (`"rocky2":
     rocky_profile()`, ambiguous); a base with an extra `lpar` field (message contains `base`);
     a 64 KiB + 1 byte target (message `target file: exceeds 64 KiB`).
3. Run the green command; expect the red.
4. Implement `compose_target_manifest`: read both files with `_json_document` (labels `target`
   and `base manifest`); `_manifest_object` the request with fields `format, profile, lpar, mac,
   network` and optional `operation_binding`, the request network with `address, routes, dns`
   (field `network`), and the base with `version, source, profiles` (field `base`). Check
   `format == TARGET_FORMAT` (`target.format`) and that `profile` is a `str`. Collect base keys
   whose value is a `dict` with `f"{distribution}-{release}" == profile`; anything but exactly one
   fails `_manifest_error("target.profile", "must match exactly one base profile")`. Return the
   JSON encoding of `version`, `lpar`, `network` (`mac` plus the request network), `source`,
   `profiles` (`{key: base_profile}`), `selected_profile` (`key`), and `operation_binding` when
   present.
5. Run the green command and `just check`; commit `feat: compose a manifest from a target
   request`.

## Task 3: Publish and print the producer result from `build`

### Verification

- Contract: `--output` build returns the prepared result. Mode: focused-test.
  `BuildTests.test_build_returns_canonical_media_result`; red: result is `None`.
- Contract: publish links `<sha>.iso`, sets `url` and `operation_binding`, and a second identical
  publish fails after the build. Mode: focused-test.
  `BuildTests.test_publishes_by_digest_with_url`; red: missing argument attributes.
- Contract: input-form, mode-coupling, and URL errors before any tool. Mode: focused-test.
  `BuildTests.test_rejects_input_and_publish_forms_before_tool`; red: no `ValidationError`.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Contract: README and AGENTS wording. Mode: task-test-not-applicable — prose with no executable
  consumer; `just check-markdown` gates its form.

**Interfaces:** consumes Tasks 1–2. Produces `MEDIA_FORMAT = "iso-chain-media-v1"`,
`MAX_RESULT_BYTES = 64 * 1024`, `_validate_source(value, field: str = "source")`,
`media_result(manifest: Manifest, manifest_sha256: str, iso_sha256: str, iso_size: int,
url: str | None) -> bytes`, `_build_manifest(args) -> tuple[Manifest, bytes, str]`, and
`build_iso(args) -> bytes`. Build args gain `target`, `base_config`, `publish_dir`, `publish_url`.

1. In `BuildTests.args` add the four keys as `None`. Give every `side_effect` helper in the class
   (`fake_run` and `race`) a `**kwargs` parameter.
2. Write the tests:
   - result: the fake asserts `kwargs["stdout"] is sys.stderr`; the returned bytes end in `}\n`;
     the parsed keys are exactly `architecture, distribution, format, iso_sha256, iso_size, mac,
     manifest_sha256, network, release`; `iso_sha256`/`iso_size` match the fake's `b"iso"`;
     `manifest_sha256` equals `load_manifest(self.config)[2]`; `network` has no `mac` and keeps
     routes as `{destination, gateway}`.
   - publish: target and base files from Task 2's helpers, `publish_url
     "https://media.example/iso"`; the publish directory then holds only `<sha>.iso`; `url` is
     the base plus `/<sha>.iso`; `operation_binding` is `"0" * 32`; distribution and release are
     `rocky`/`9.8`; a second identical call raises `appeared during build`.
   - rejections with `subprocess.run` patched and never called: no `--config` and no target;
     `--config` with `--target`; neither output form; `--output` with `--publish-dir`;
     `--publish-dir` without URL; URL `"ftp://opaque-host"` (message must not contain
     `opaque-host`); a bound target with `--output`; an unbound target with `--publish-*`.
3. Run the green command; expect the reds.
4. Implement:
   - `_validate_source` takes `field` and uses it in each `_manifest_error` and in
     `_validate_source_host` (pass it through).
   - `media_result` builds `format`, `iso_sha256`, `iso_size`, `manifest_sha256`, the selected
     profile's `distribution` and `release`, `architecture: "ppc64le"`, `mac`, and `network` from
     `_manifest_data(manifest)["network"]` without `mac`; adds `operation_binding` and `url` when
     not `None`; returns `json.dumps(..., sort_keys=True, separators=(",", ":")).encode() + b"\n"`,
     raising `ValidationError("producer result exceeds 64 KiB")` above `MAX_RESULT_BYTES`.
   - `_build_manifest` raises `"give either --config or both --target and --base-config"` and
     `"give either --output or both --publish-dir and --publish-url"` on bad pairings, loads or
     composes the manifest, then raises `"operation_binding requires --publish-dir and a published
     ISO requires operation_binding"` unless `(manifest.operation_binding is None) ==
     (args.publish_dir is None)`.
   - `build_iso` starts with `_build_manifest`, then validates `--publish-url` as
     `"publish URL"`; `parent` is the publish directory (`_path(..., "publish directory",
     "directory")`) or today's output parent, with today's existing-output check for `--output`
     only. `grub2-mkrescue` gets `stdout=sys.stderr`. After the `is_file` check it hashes the
     temporary ISO once, sets `output = parent / f"{iso_sha256}.iso"` in publish mode, links, and
     returns `media_result(manifest, digest, iso_sha256, size, url)` with `url` `None` for
     `--output`.
   - `parser()`: `build`'s `--config` and `--output` become optional; add `--target`,
     `--base-config`, `--publish-dir` (`type=Path`) and `--publish-url`. `main()` writes
     `build_iso(args)` to `sys.stdout.buffer`.
5. Docs. README: a "Building media for hmcpctl" section with a request example, the base shape,
   the build-entry command line, the result fields, that `smoke`, `install-fedora`, and `verify-*`
   take the embedded manifest recovered with `inspect ISO`, and that the operator removes
   `<publish-dir>/*.iso` and leftover `.iso-chain-*` directories. AGENTS.md: stage 1 (optional
   `operation_binding`, target/base composition), stage 4, and the subcommand list.
6. Run the green command and `just check`; commit `feat: publish media and print the producer
   result`.

## Task 4: Validate and forward target and publish inputs in `container-build`

### Verification

- Contract: target, base, and publish mounts and inner arguments. Mode: focused-test.
  `ContainerBuildTests.test_forwards_target_and_publish_inputs`; red: missing attributes.
- Contract: host-side validation and the root guards for the publish directory. Mode:
  focused-test. `ContainerBuildTests.test_rejects_target_and_publish_inputs_before_engine`; red:
  no `ValidationError`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.ContainerBuildTests`.

**Interfaces:** consumes `_build_manifest` and `_validate_source(value, field)`;
`container_build_command(args, engine)` keeps its signature.

1. In `ContainerBuildTests.args` add the four keys as `None`. Existing tests pass `"{}"` as the
   manifest; give them a valid manifest file (`json.dumps(manifest_data())`) now that the command
   validates it.
2. Tests:
   - forwards: a valid bound target (Task 2 helper) in its own directory, a valid base file, a
     publish directory, URL `https://media.example`; the target's directory is mounted
     `readonly`, the publish directory writable; the inner command carries `--target`,
     `--base-config`, `--publish-dir`, `--publish-url` with those values and no `--config` or
     `--output`.
   - rejects before composing the command: an invalid target, an `ftp://` URL, and
     `--publish-dir` equal to `iso_chain.REPOSITORY_ROOT`.
3. Run the green command; expect the reds.
4. Implement: call `_build_manifest(args)` and, in publish mode, validate the URL before mounts;
   input files come from `--config` or `--target`/`--base-config` (each `_path(..., "file")`, its
   directory read-only); the writable directory is `--output`'s parent or the publish directory,
   and today's filesystem-root and repository-root refusals apply to whichever it is. Emit only
   the flags in use. Mirror the four flags in the `container-build` parser.
5. Run the green command and `just check`; commit `feat: forward target inputs through
   container-build`.

## Task 5: `inspect --result`

### Verification

- Contract: prepared result for an unbound ISO; a bound ISO is refused. Mode: focused-test.
  `InspectTests.test_result_reports_prepared_and_refuses_bound_media`; red: `AttributeError`.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.InspectTests`.

**Interfaces:** consumes `media_result`. Produces `inspect_result(path: Path) -> bytes`.

1. Test: with the extraction fake writing `manifest_data()`, the result's `iso_sha256` and
   `iso_size` match `b"iso"`, `manifest_sha256` equals the canonical digest, and neither `url` nor
   `operation_binding` is present; with `manifest_data(operation_binding="0" * 32)` it raises
   `ValidationError` naming `operation_binding`.
2. Run; expect the red.
3. Implement: move `inspect_iso`'s body into `_embedded_manifest(path) -> tuple[Path,
   tuple[Manifest, bytes, str]]`; `inspect_iso` returns the canonical bytes; `inspect_result`
   refuses a bound manifest with `_manifest_error("operation_binding", "is bound; inspect reports
   prepared media only")` and returns `media_result(manifest, digest, _file_sha256(iso),
   iso.stat().st_size, None)`. Add `--result` (`store_true`) to `inspect`, select in `main()`, and
   document it in the README section from Task 3.
4. Run the green command and `just check`; commit `feat: print the producer result for an ISO`.
