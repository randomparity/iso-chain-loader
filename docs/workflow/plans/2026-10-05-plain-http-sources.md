# Plain-HTTP Source Restriction Implementation Plan

Goal: `http://` sources pass only on loopback or RFC 1918 IPv4 literals, in the manifest
validator and the launcher alike; `--publish-url` keeps today's grammar. Spec:
`docs/workflow/specs/2026-10-05-plain-http-sources-design.md`; ADR 0026.

Architecture: `_validate_source` splits into grammar (`_validate_origin`, also used by
`--publish-url`) plus one check; the launcher's
`valid_source` gains the same check through a new `plain_http_host`. A Python parity test runs the
launcher's function definitions under `sh` against the Python validator's case table.

Tech stack: Python 3.14 stdlib (`ipaddress`), POSIX `sh` launcher, Bash test harness, `unittest`.

Expected implementation size: 110–150 changed lines (M) — about 10 Python, 12 launcher, 55 Python
test, 25 shell test (mostly fixture address swaps), and 25 README, spec, and AGENTS.md lines.

## Global Constraints

- `scripts/` imports the standard library only; the launcher uses only shell builtins here.
- Errors never echo the input (AGENTS.md); validation fails before any external command.
- ruff line length 100; rumdl line length 100. `.secrets.baseline` covers only `Justfile`, which
  this change does not touch.
- Guardrails: `just check-tests`, `just check`.

## File map

- `assets/dracut/iso-chain-launch.sh` — owns guest argument validation; gains `plain_http_host`.
- `tests/test_iso_chain_launch.sh` — fixture source `http://192.0.2.2` becomes `http://10.0.2.2`.
- `scripts/iso_chain.py` — owns manifest and publish-URL validation; gains `PLAIN_HTTP_NETWORKS`,
  `_validate_origin`, and `_plain_http_host`.
- `tests/test_iso_chain.py` — rule, error, unchanged publish-URL, and parity cases.
- `README.md`, `AGENTS.md`, `docs/workflow/specs/2026-10-01-iso-carried-artifacts-design.md` —
  the plain-HTTP sentences point at ADR 0026.

## Task 1: Launcher rule

Interfaces: provides `plain_http_host HOST` (exit 0 when allowed) and a `scheme` variable set by
`valid_source`; Task 2's parity test calls `valid_source` with `source` set.

Verification:

- Mode: focused-test. Contract: spec Success 3. Case "plain HTTP public source" in
  `tests/test_iso_chain_launch.sh`; red before step 3 with `test failure: plain HTTP public source
  unexpectedly succeeded`; green: `bash tests/test_iso_chain_launch.sh` prints
  `launcher shell tests: passed`.

Steps:

1. In `tests/test_iso_chain_launch.sh`, replace every `192.0.2.2` with `10.0.2.2` and every
   `192\.0\.2\.2`-escaped substitution pattern accordingly (`sed -i 's/192\.0\.2\.2/10.0.2.2/g'`),
   then confirm `rg -n 192.0.2.2 tests/test_iso_chain_launch.sh` prints nothing.
2. After the "non-canonical HTTP scheme" case add:

   ```bash
   for refused_source in http://192.0.2.2 http://mirror.example http://172.32.0.1; do
       invalid_cmdline=$(command_line)
       invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/10.0.2.2/iso_chain.source=$refused_source}
       assert_configuration_rejected "plain HTTP public source" "$invalid_cmdline"
   done
   ```

   Run `bash tests/test_iso_chain_launch.sh`; expect the red failure above.
3. In `assets/dracut/iso-chain-launch.sh`, add before `valid_source`:

   ```sh
   plain_http_host() {
       valid_ipv4 "$1" || return 1
       old_ifs=$IFS
       IFS=.
       set -f
       # shellcheck disable=SC2086 # Address passed strict IPv4 validation above.
       set -- $1
       set +f
       IFS=$old_ifs
       case "$1.$2" in 10.* | 127.* | 192.168) return 0 ;; esac
       [ "$1" = 172 ] && [ "$2" -ge 16 ] && [ "$2" -le 31 ]
   }
   ```

   and in `valid_source` set `scheme=http` / `scheme=https` in the two scheme arms, and replace
   the final `valid_source_host "$host"` with:

   ```sh
   valid_source_host "$host" || return 1
   [ "$scheme" = https ] || plain_http_host "$host"
   ```

4. Run `bash tests/test_iso_chain_launch.sh`; expect `launcher shell tests: passed`. Commit.

## Task 2: Manifest rule

Interfaces: consumes Task 1's `valid_source`. Provides `PLAIN_HTTP_NETWORKS:
tuple[ipaddress.IPv4Network, ...]`, `_validate_origin(value: object, field: str) -> str`,
`_plain_http_host(host: str) -> bool`, and the error text in the spec.

Verification:

- Mode: focused-test. Contract: spec Success 1. `ManifestV4Tests.
  test_plain_http_source_rule_matches_launcher`; red: refused cases load in Python; green:
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests -v`.
- Mode: focused-test. Contract: spec Success 2 (refusal). `ManifestV4Tests.
  test_rejects_plain_http_public_source_without_echoing_host`; red: no `ValidationError`; green:
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests -v`.
- Mode: focused-test. Contract: spec Success 2 (`--publish-url` unchanged). `ContainerBuildTests.
  test_accepts_plain_http_publish_url_on_any_host`; it passes before the change, so its red is a
  controlled fault: point `container_build_command` at `_validate_source` and expect
  `ValidationError`, then revert; green:
  `.venv/bin/python -m unittest tests.test_iso_chain.ContainerBuildTests -v`.

Steps:

1. In `ManifestV4Tests` add, with module constants `PLAIN_HTTP_ACCEPTED = ("http://127.0.0.1:8000",
   "http://10.0.2.2", "http://172.16.0.1", "http://172.31.255.254/a", "http://192.168.1.10",
   "https://mirror.example", "https://192.0.2.2")` and `PLAIN_HTTP_REFUSED = ("http://172.15.0.1",
   "http://172.32.0.1", "http://192.0.2.2", "http://11.0.0.1", "http://192.169.0.1",
   "http://010.0.2.2", "http://mirror.example", "http://localhost")`:

   ```python
   def test_plain_http_source_rule_matches_launcher(self):
       launcher = (REPOSITORY / "assets/dracut/iso-chain-launch.sh").read_text()
       functions = self.root / "launcher-functions.sh"
       functions.write_text(launcher.rpartition('main "$@"')[0])
       script = '. "$1"; source=$2; if valid_source; then exit 0; fi; exit 1'
       for source in PLAIN_HTTP_ACCEPTED + PLAIN_HTTP_REFUSED:
           expected = source in PLAIN_HTTP_ACCEPTED
           with self.subTest(source=source):
               try:
                   iso_chain._validate_source(source)
                   python = True
               except iso_chain.ValidationError:
                   python = False
               shell = (
                   subprocess.run(
                       ["sh", "-c", script, "sh", str(functions), source],
                       env={**os.environ, "ISO_CHAIN_CMDLINE": "unused"},
                       check=False,
                   ).returncode
                   == 0
               )
               self.assertEqual((python, shell), (expected, expected))


   def test_rejects_plain_http_public_source_without_echoing_host(self):
       for source in PLAIN_HTTP_REFUSED:
           with (
               self.subTest(source=source),
               self.assertRaisesRegex(
                   iso_chain.ValidationError, "manifest source: plain http://"
               ) as caught,
           ):
               self.load(manifest_data(source=source))
           self.assertNotIn(source.removeprefix("http://"), str(caught.exception))
   ```

2. In `ContainerBuildTests` add:

   ```python
   def test_accepts_plain_http_publish_url_on_any_host(self):
       args = self.publish_args(target_request(), publish_url="http://media.example/iso")
       command = iso_chain.container_build_command(args, "docker")
       self.assertIn("http://media.example/iso", command)
   ```

   Run the focused commands; expect the red failures above for step 1's tests.
3. In `scripts/iso_chain.py`, beside the other module constants add:

   ```python
   PLAIN_HTTP_NETWORKS = tuple(
       ipaddress.IPv4Network(network)
       for network in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
   )
   ```

   rename today's `_validate_source(value, field="source")` to `_validate_origin(value, field)`,
   unchanged, point the two `--publish-url` calls (`build_iso`, `container_build_command`) at
   `_validate_origin(args.publish_url, "publish_url")`, and add:

   ```python
   def _validate_source(value: object, field: str = "source") -> str:
       source = _validate_origin(value, field)
       if source.startswith("http://") and not _plain_http_host(urlsplit(source).hostname):
           _manifest_error(
               field,
               "plain http:// requires a loopback or RFC 1918 IPv4 address; "
               "use https:// for any other host",
           )
       return source
   ```

   with the helper:

   ```python
   def _plain_http_host(host: str) -> bool:
       try:
           address = ipaddress.IPv4Address(host)
       except ipaddress.AddressValueError:
           return False
       return any(address in network for network in PLAIN_HTTP_NETWORKS)
   ```

4. Run the focused commands; expect green. Run `just check-tests`; expect exit 0. Commit.

## Task 3: Documentation

Verification:

- Mode: task-test-not-applicable. Surface: README, AGENTS.md, v4 spec prose. Reason: no executable
  consumer reads these sentences; `just check-markdown` covers their format.

Steps:

1. README (`install.img` paragraph and the `source` grammar sentence after the mirror list):
   state that `http://` needs a loopback or RFC 1918 IPv4 host (ADR 0026).
2. v4 spec `source` bullet and failure-model deployment line: the same sentence and link.
3. AGENTS.md security-invariant line: "HTTP only for loopback and RFC 1918 IPv4 hosts (ADR 0026)";
   add ADR 0026 to the ADR list and bump "twenty-five accepted" to "twenty-six" and the range.
4. Run `just check`; expect exit 0. Commit.
