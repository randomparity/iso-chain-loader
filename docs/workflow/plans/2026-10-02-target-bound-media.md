# Target-Bound Installation Media Plan

**Goal:** let hmcpctl build launcher media from a per-partition target request and check an
`iso-chain-media-v1` producer result (spec `2026-10-02-target-bound-media-design.md`, ADR 0015).

**Architecture:** `build` composes a manifest v4 from a target request and a base manifest, then
runs the existing build. It publishes by digest name and prints one canonical result line.
`container-build` forwards the same inputs, and `inspect --result` reuses the result writer.

**Tech stack:** Python 3.14 standard library only; stdlib `unittest`.

Expected implementation size: 330–420 changed lines (M) — about 120 in `scripts/iso_chain.py`,
200–260 in tests, 20–40 in README and AGENTS.md.

## Global Constraints

- Python 3.14, `scripts/` imports the standard library only; ruff line length 100.
- Every function annotated; `ValidationError` messages name fields and never echo values.
- Validation fails before any `subprocess` call; tests assert `run.assert_not_called()`.
- No existing file is replaced: `os.link` publication, `FileExistsError` becomes a validation error.
- Guardrails: `just check-tests` while iterating; `just check` before each commit (about 7 s).

## File Map

- `scripts/iso_chain.py` — owns parsing, composition, build, result, and CLI. Changed throughout.
- `tests/test_iso_chain.py` — `ManifestV4Tests`, new `TargetRequestTests`, `BuildTests`,
  `ContainerBuildTests`, `InspectTests`.
- `README.md`, `AGENTS.md` — document the new flags, the result, and operator cleanup.

No ownership move: each change extends the function that already owns the behavior.

## Task 1: Optional `operation_binding` in manifest v4

### Verification

- Contract: optional binding parsed, validated, and kept in the canonical bytes. Mode:
  focused-test. `ManifestV4Tests.test_operation_binding_is_optional_and_exact`; red:
  `manifest root: unknown field`. Green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.ManifestV4Tests`.

**Interfaces:** produces `Manifest.operation_binding: str | None` (default `None`, last field) and
`_manifest_object(value, fields, field, optional=frozenset())`.

1. Add the test:

   ```python
   def test_operation_binding_is_optional_and_exact(self):
       manifest, canonical, digest = self.load(manifest_data())
       self.assertIsNone(manifest.operation_binding)
       bound, bound_canonical, bound_digest = self.load(manifest_data(operation_binding="0" * 32))
       self.assertEqual(bound.operation_binding, "0" * 32)
       self.assertIn(b'"operation_binding":"' + b"0" * 32 + b'"', bound_canonical)
       self.assertNotEqual(digest, bound_digest)
       for value in ("A" * 32, "0" * 31, 7, "secret-binding-value"):
           with self.assertRaises(iso_chain.ValidationError) as caught:
               self.load(manifest_data(operation_binding=value))
           self.assertNotIn("secret-binding-value", str(caught.exception))
   ```

2. Run it; expect the red error above.
3. Implement: add `OPERATION_BINDING = re.compile(r"^[0-9a-f]{32}$")`; give `_manifest_object` an
   `optional: frozenset[str] = frozenset()` parameter and change its unknown check to
   `value.keys() - fields - optional`; add `operation_binding: str | None = None` to `Manifest`;
   in `load_manifest_bytes` pass `optional=frozenset({"operation_binding"})` for the root, then

   ```python
   binding = root.get("operation_binding")
   if binding is not None and (
       type(binding) is not str or OPERATION_BINDING.fullmatch(binding) is None
   ):
       _manifest_error("operation_binding", "must be 32 lower-case hex digits")
   ```

   and pass `operation_binding=binding` to `Manifest(...)`. In `_manifest_data`, add the key when
   it is not `None`.
4. Run the green command, then `just check`; commit `feat: accept an optional operation binding`.

## Task 2: Compose a manifest from a target request

### Verification

- Contract: request plus base yields a one-profile manifest v4. Mode: focused-test.
  `TargetRequestTests.test_composes_one_profile_manifest`; red: `AttributeError` for
  `compose_target_manifest`.
- Contract: request and base shape rejections, without echo. Mode: focused-test.
  `TargetRequestTests.test_rejects_bad_requests_without_echo`; red: same `AttributeError`.
  Green for both: `.venv/bin/python -m unittest -v tests.test_iso_chain.TargetRequestTests`.

**Interfaces:** consumes Task 1. Produces
`compose_target_manifest(target: Path, base: Path) -> bytes` (JSON bytes for
`load_manifest_bytes`), `TARGET_FORMAT = "iso-chain-target-v1"`, and
`_read_manifest_bytes(path, label="manifest")`.

1. Add module helpers and the class:

   ```python
   def target_request(**changes):
       data = {
           "format": "iso-chain-target-v1",
           "profile": "rocky",
           "lpar": "sys-r1",
           "mac": "52:54:00:12:34:56",
           "network": {
               "address": "10.0.2.15/24",
               "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
               "dns": ["10.0.2.3"],
           },
           "operation_binding": "0" * 32,
       }
       data.update(changes)
       return data


   def base_manifest():
       data = manifest_data()
       return {
           "version": 4,
           "source": data["source"],
           "profiles": {"rocky": rocky_profile(), "ubuntu": ubuntu_profile()},
       }


   class TargetRequestTests(unittest.TestCase):
       def setUp(self):
           self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
           self.target = self.root / "target.json"
           self.base = self.root / "base.json"
           self.base.write_text(json.dumps(base_manifest()))

       def compose(self, request):
           self.target.write_text(json.dumps(request))
           return iso_chain.load_manifest_bytes(
               iso_chain.compose_target_manifest(self.target, self.base)
           )

       def test_composes_one_profile_manifest(self):
           manifest, _, _ = self.compose(target_request())
           self.assertEqual([name for name, _ in manifest.profiles], ["rocky"])
           self.assertEqual(manifest.selected_profile, "rocky")
           self.assertEqual(manifest.network.mac, "52:54:00:12:34:56")
           self.assertEqual(manifest.operation_binding, "0" * 32)
           unbound = target_request()
           del unbound["operation_binding"]
           self.assertIsNone(self.compose(unbound)[0].operation_binding)

       def test_rejects_bad_requests_without_echo(self):
           opaque = "opaque-request-value"
           cases = [
               target_request(format="iso-chain-target-v2"),
               target_request(profile="fedora"),
               target_request(ssh_authorized_keys=[opaque]),
               target_request(network={"address": opaque, "routes": [], "dns": []}),
               target_request(mac=opaque),
               target_request(lpar=opaque.upper()),
               target_request(
                   profile="ubuntu",
                   network=dict(target_request()["network"], dns=["10.0.2.3"] * 3),
               ),
           ]
           for request in cases:
               with (
                   self.subTest(request=request),
                   self.assertRaises(iso_chain.ValidationError) as caught,
               ):
                   self.compose(request)
               self.assertNotIn(opaque, str(caught.exception))
           self.base.write_text(json.dumps(dict(base_manifest(), lpar="sys-r1")))
           with self.assertRaisesRegex(iso_chain.ValidationError, "base"):
               self.compose(target_request())
           self.target.write_text("[" * (64 * 1024 + 1))
           with self.assertRaisesRegex(iso_chain.ValidationError, "target file: exceeds 64 KiB"):
               iso_chain.compose_target_manifest(self.target, self.base)
   ```

2. Run the green command; expect the `AttributeError` reds.
3. Implement. Give `_read_manifest_bytes` a `label: str = "manifest"` parameter used in its three
   messages (`f"{label} file: ..."`) and add:

   ```python
   def _json_document(path: Path, label: str) -> object:
       encoded = _read_manifest_bytes(path, label)
       try:
           return json.loads(encoded.decode("utf-8"), object_pairs_hook=_object_pairs)
       except (UnicodeDecodeError, json.JSONDecodeError) as error:
           raise ValidationError(f"{label} JSON: invalid UTF-8 JSON") from error


   def compose_target_manifest(target: Path, base: Path) -> bytes:
       request = _manifest_object(
           _json_document(target, "target"),
           {"format", "profile", "lpar", "mac", "network"},
           "target",
           optional=frozenset({"operation_binding"}),
       )
       if request["format"] != TARGET_FORMAT:
           _manifest_error("target.format", f"must be {TARGET_FORMAT}")
       network = _manifest_object(request["network"], {"address", "routes", "dns"}, "network")
       data = _manifest_object(
           _json_document(base, "base manifest"), {"version", "source", "profiles"}, "base"
       )
       profile = _identifier(request["profile"], "target.profile")
       if type(data["profiles"]) is not dict or profile not in data["profiles"]:
           _manifest_error("target.profile", "must be listed in the base manifest profiles")
       composed = {
           "version": data["version"],
           "lpar": request["lpar"],
           "network": {"mac": request["mac"], **network},
           "source": data["source"],
           "profiles": {profile: data["profiles"][profile]},
           "selected_profile": profile,
       }
       if "operation_binding" in request:
           composed["operation_binding"] = request["operation_binding"]
       return json.dumps(composed).encode()
   ```

4. Run the green command, then `just check`; commit `feat: compose a manifest from a target request`.

## Task 3: Publish and print the producer result from `build`

### Verification

- Contract: `--output` build returns the result line. Mode: focused-test.
  `BuildTests.test_build_returns_canonical_media_result`; red: `build_iso` returns `None`.
- Contract: publish mode links `<sha>.iso` and sets `url`; a second identical publish fails.
  Mode: focused-test. `BuildTests.test_publishes_by_digest_with_url`; red: missing argument
  attributes.
- Contract: input-form and URL errors fail before any tool. Mode: focused-test.
  `BuildTests.test_rejects_input_and_publish_forms_before_tool`; red: no `ValidationError`.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.
- Contract: README/AGENTS wording. Mode: task-test-not-applicable — prose with no executable
  consumer; `just check-markdown` gates its form.

**Interfaces:** consumes Tasks 1–2. Produces `MEDIA_FORMAT = "iso-chain-media-v1"`,
`MAX_RESULT_BYTES = 64 * 1024`,
`media_result(manifest, manifest_sha256, iso_sha256, iso_size, url) -> bytes`,
`_build_manifest(args) -> tuple[Manifest, bytes, str]`, `build_iso(args) -> bytes`, and
`_validate_source(value, field="source")`. Build args gain `target`, `base_config`,
`publish_dir`, `publish_url` (all `None` when unused).

1. In `BuildTests.args`, add `"target": None, "base_config": None, "publish_dir": None,
   "publish_url": None`; change every `fake_run(command, check)` in the class to
   `fake_run(command, check, **kwargs)`. Add tests:

   ```python
   def test_build_returns_canonical_media_result(self):
       def fake_run(command, check, **kwargs):
           self.assertIs(kwargs["stdout"], sys.stderr)
           Path(command[4]).write_bytes(b"iso")

       with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
           encoded = iso_chain.build_iso(self.args())
       self.assertTrue(encoded.endswith(b"}\n"))
       result = json.loads(encoded)
       self.assertEqual(result["iso_sha256"], hashlib.sha256(b"iso").hexdigest())
       self.assertEqual(result["iso_size"], 3)
       self.assertEqual(result["manifest_sha256"], iso_chain.load_manifest(self.config)[2])
       self.assertEqual(
           sorted(result),
           [
               "architecture",
               "distribution",
               "format",
               "iso_sha256",
               "iso_size",
               "mac",
               "manifest_sha256",
               "network",
               "release",
           ],
       )
       self.assertEqual(
           result["network"]["routes"], [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}]
       )


   def test_publishes_by_digest_with_url(self):
       publish = self.root / "publish"
       publish.mkdir()
       target = self.root / "target.json"
       target.write_text(json.dumps(target_request()))
       base = self.root / "base.json"
       base.write_text(json.dumps(base_manifest()))
       args = self.args(
           output=None,
           config=None,
           target=target,
           base_config=base,
           publish_dir=publish,
           publish_url="https://media.example/iso",
       )

       def fake_run(command, check, **kwargs):
           Path(command[4]).write_bytes(b"iso")

       with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
           result = json.loads(iso_chain.build_iso(args))
           with self.assertRaisesRegex(iso_chain.ValidationError, "already exists"):
               iso_chain.build_iso(args)
       name = hashlib.sha256(b"iso").hexdigest() + ".iso"
       self.assertEqual([path.name for path in publish.iterdir()], [name])
       self.assertEqual(result["url"], "https://media.example/iso/" + name)
       self.assertEqual(result["operation_binding"], "0" * 32)
       self.assertEqual((result["distribution"], result["release"]), ("rocky", "9.8"))


   def test_rejects_input_and_publish_forms_before_tool(self):
       publish = self.root / "publish"
       publish.mkdir()
       cases = [
           {"config": None},
           {"target": self.config},
           {"output": None},
           {"publish_dir": publish},
           {"output": None, "publish_dir": publish, "publish_url": "ftp://secret-host"},
           {"output": None, "publish_dir": publish},
       ]
       with mock.patch("scripts.iso_chain.subprocess.run") as run:
           for changes in cases:
               with (
                   self.subTest(changes=changes),
                   self.assertRaises(iso_chain.ValidationError) as caught,
               ):
                   iso_chain.build_iso(self.args(**changes))
               self.assertNotIn("secret-host", str(caught.exception))
       run.assert_not_called()
   ```

2. Run the green command; expect the reds listed above.
3. Implement. Give `_validate_source` a `field: str = "source"` parameter used in place of every
   literal `"source"` in its `_manifest_error` calls and in `_validate_source_host`'s message (pass
   the field through). Add:

   ```python
   def media_result(
       manifest: Manifest, manifest_sha256: str, iso_sha256: str, iso_size: int, url: str | None
   ) -> bytes:
       profile = manifest.profile(manifest.selected_profile)
       network = _manifest_data(manifest)["network"]
       del network["mac"]
       result: dict[str, object] = {
           "format": MEDIA_FORMAT,
           "iso_sha256": iso_sha256,
           "iso_size": iso_size,
           "manifest_sha256": manifest_sha256,
           "distribution": profile.distribution,
           "release": profile.release,
           "architecture": "ppc64le",
           "mac": manifest.network.mac,
           "network": network,
       }
       if manifest.operation_binding is not None:
           result["operation_binding"] = manifest.operation_binding
       if url is not None:
           result["url"] = url
       encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
       if len(encoded) > MAX_RESULT_BYTES:
           raise ValidationError("producer result exceeds 64 KiB")
       return encoded


   def _build_manifest(args: argparse.Namespace) -> tuple[Manifest, bytes, str]:
       if (args.config is None) == (args.target is None) or (args.target is None) != (
           args.base_config is None
       ):
           raise ValidationError("give either --config or both --target and --base-config")
       if (args.output is None) == (args.publish_dir is None) or (args.publish_dir is None) != (
           args.publish_url is None
       ):
           raise ValidationError("give either --output or both --publish-dir and --publish-url")
       if args.config is not None:
           return load_manifest(Path(args.config))
       return load_manifest_bytes(compose_target_manifest(Path(args.target), Path(args.base_config)))
   ```

   In `build_iso`: replace the first line with `manifest, canonical, digest =
   _build_manifest(args)`; then
   `url_base = None if args.publish_url is None else _validate_source(args.publish_url,
   "publish URL")`. Set `parent` to `_path(args.publish_dir, "publish directory", "directory")`
   in publish mode, else today's output parent, and keep the existing-output check for `--output`
   only. Pass `stdout=sys.stderr` to the `grub2-mkrescue` call. After the `is_file` check:

   ```python
   iso_sha256 = _file_sha256(temporary_iso)
   iso_size = temporary_iso.stat().st_size
   if url_base is not None:
       output = parent / f"{iso_sha256}.iso"
   try:
       os.link(temporary_iso, output)
   except FileExistsError as error:
       raise ValidationError(f"output already exists: {output.name}") from error
   url = None if url_base is None else f"{url_base}/{output.name}"
   return media_result(manifest, digest, iso_sha256, iso_size, url)
   ```

   In `parser()`, make `build`'s `--config` and `--output` optional and add `--target`,
   `--base-config`, `--publish-dir` (`type=Path`) and `--publish-url` (string). In `main()`, write
   the result: `sys.stdout.buffer.write(build_iso(args))`.

4. Update README (a "Building media for hmcpctl" section: request example, base manifest shape,
   publish flags, result fields, operator cleanup of `<publish-dir>/*.iso`) and AGENTS.md (stage
   4 and the subcommand list). Run the green command and `just check`; commit
   `feat: publish media and print the producer result`.

## Task 4: Forward target and publish inputs through `container-build`

### Verification

- Contract: target, base, and publish directory mounts and inner arguments. Mode: focused-test.
  `ContainerBuildTests.test_forwards_target_and_publish_inputs`; red: missing argument
  attributes. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.ContainerBuildTests`.

**Interfaces:** consumes `_build_manifest`'s pairing rule. `container_build_command(args, engine)`
keeps its signature.

1. In `ContainerBuildTests.args`, add the four `None` keys. Add:

   ```python
   def test_forwards_target_and_publish_inputs(self):
       requests = self.root / "requests"
       requests.mkdir()
       target = requests / "target.json"
       target.write_text("{}")
       publish = self.root / "publish"
       publish.mkdir()
       command = iso_chain.container_build_command(
           self.args(
               config=None,
               output=None,
               target=target,
               base_config=self.manifest,
               publish_dir=publish,
               publish_url="https://media.example",
           ),
           "docker",
       )
       mounts = self.mounts(command)
       self.assertIn(f"type=bind,source={requests},target={requests},readonly", mounts)
       self.assertIn(f"type=bind,source={publish},target={publish}", mounts)
       inner = self.inner(command)
       for flag, value in (
           ("--target", target),
           ("--base-config", self.manifest),
           ("--publish-dir", publish),
           ("--publish-url", "https://media.example"),
       ):
           self.assertEqual(inner[inner.index(flag) + 1], str(value))
       self.assertNotIn("--output", inner)
       self.assertNotIn("--config", inner)
   ```

2. Run the green command; expect the red.
3. Implement: build the input list from `--config` or `--target`/`--base-config` (each `_path(...,
   "file")`, its parent mounted read-only) and the writable directory from `--output`'s parent
   (with today's existence and repository-root checks) or `_path(args.publish_dir, "publish
   directory", "directory")`. Emit only the flags in use, in the order `--config`|`--target
   --base-config`, then `--output`|`--publish-dir --publish-url`. Raise the same pairing
   `ValidationError` messages as `_build_manifest` before composing. Mirror the parser flags.
4. Run the green command and `just check`; commit `feat: forward target inputs through
   container-build`.

## Task 5: `inspect --result`

### Verification

- Contract: prepared-mode result for an existing ISO. Mode: focused-test.
  `InspectTests.test_result_binds_file_and_embedded_manifest`; red: `AttributeError` for
  `inspect_result`. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.InspectTests`.

**Interfaces:** consumes `media_result`. Produces `inspect_result(path: Path) -> bytes`.

1. Add:

   ```python
   def test_result_binds_file_and_embedded_manifest(self):
       def fake_run(command, check):
           Path(command[-1]).write_text(json.dumps(manifest_data()))

       with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
           result = json.loads(iso_chain.inspect_result(self.iso))
       self.assertEqual(result["iso_sha256"], hashlib.sha256(b"iso").hexdigest())
       self.assertEqual(result["iso_size"], 3)
       self.assertEqual(
           result["manifest_sha256"],
           iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())[2],
       )
       self.assertNotIn("url", result)
       self.assertNotIn("operation_binding", result)
   ```

2. Run; expect the red.
3. Implement: rename the body of `inspect_iso` to `_embedded_manifest(path) -> tuple[Path,
   tuple[Manifest, bytes, str]]` returning the resolved ISO path and `load_manifest(extracted)`;
   `inspect_iso` returns its canonical bytes; `inspect_result` returns
   `media_result(manifest, digest, _file_sha256(iso), iso.stat().st_size, None)`. Add
   `inspect.add_argument("--result", action="store_true")` and select in `main()`. Document it in
   the README section from Task 3.
4. Run the green command and `just check`; commit `feat: print the producer result for an ISO`.
