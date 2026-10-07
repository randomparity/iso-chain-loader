# FTP Source Implementation Plan

Goal: `build` and the launcher accept ADR 0027's `ftp://<user>:<password>@<host>[:<port>][/<path>]`
`source` under one rule and name no part of it when refusing. Spec:
`docs/workflow/specs/2026-10-07-ftp-sources-design.md`.

Architecture: `_validate_source` peels `ftp://` and the userinfo, checks the userinfo, then
validates `https://<rest>` through itself; the launcher's `valid_source` mirrors it in POSIX `sh`.
A parity test runs both against one case table.

Tech stack: Python 3.14 stdlib (`re`), POSIX `sh` launcher, Bash test harness, `unittest`.

Expected implementation size: 150–200 changed lines (M) — about 25 Python, 35 launcher, 110 Python
test, 20 shell test, and 15 README, AGENTS.md, and v4 spec lines.

## Global Constraints

- `scripts/` imports the standard library only; the launcher uses shell builtins only here.
- Errors and launcher markers never echo the source; validation fails before any external command.
- ruff and rumdl line length 100. `.secrets.baseline` covers only `Justfile`, untouched here.
  detect-secrets' Basic Auth detector flags a literal `scheme://a:b@` string, so tests build FTP
  URLs from `FTP_USERINFO` with f-strings or shell `${...}` and never write one literally.
- Guardrails: `just check-tests`, `just check`.

## File map

- `scripts/iso_chain.py` — owns manifest validation; gains `MAX_FTP_USERINFO_BYTES`,
  `FTP_USERINFO_PART`, `_validate_ftp_userinfo`, and the `ftp://` branch of `_validate_source`.
- `assets/dracut/iso-chain-launch.sh` — owns guest validation; gains `valid_userinfo_part`,
  `valid_ftp_userinfo`, and the `ftp://*@*` arm of `valid_source`.
- `tests/test_iso_chain.py`, `tests/test_iso_chain_launch.sh` — cases below.
- `README.md`, `AGENTS.md`, `docs/workflow/specs/2026-10-01-iso-carried-artifacts-design.md`.

## Task 1: One FTP rule in both validators

Interfaces: consumes existing `_string`, `_manifest_error`, `_validate_origin`, `ValidationError`,
`valid_path`, `valid_port`, `valid_source_host`, `plain_http_host`. Provides
`_validate_ftp_userinfo(userinfo: str, field: str) -> None` and shell
`valid_ftp_userinfo USERINFO` (exit 0 when valid).

Verification:

- Mode: focused-test. Contract: spec Success 1. `test_source_rule_matches_launcher`; red before
  steps 3–4 with an `AssertionError` such as `(False, False) != (True, True)` on the first
  `FTP_ACCEPTED` row; green:
  `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests.test_source_rule_matches_launcher`.
- Mode: focused-test. Contract: spec Success 2 (manifest). `test_rejects_ftp_source_without_echoing_it`;
  red before step 3 with a regex mismatch on the FTP message; green with the same command naming it.

Steps:

1. In `tests/test_iso_chain.py`, after `PLAIN_HTTP_REFUSED`, add:

   ```python
   FTP_USERINFO = "fake-user:fake-pass"


   def ftp_source(userinfo=FTP_USERINFO, location="mirror.example"):
       return f"ftp://{userinfo}@{location}"


   FTP_ACCEPTED = (
       ftp_source(),
       ftp_source(location="192.0.2.2:2121/pub/fedora"),
       ftp_source(location="10.0.2.2"),
       ftp_source("a.b_c~d-e:F.G_h~i-j"),
       ftp_source("fake-user:p%80%FF%25%20%3A%40"),
       ftp_source("u:" + "p" * 126),
   )
   FTP_REFUSED = (
       ("ftps" + ftp_source()[3:], "scheme"),
       ("FTP" + ftp_source()[3:], "scheme"),
       ("ftp://mirror.example", "needs"),
       (ftp_source("fake-user"), "needs"),
       (ftp_source("fake-user:"), "needs"),
       (ftp_source(":fake-pass"), "needs"),
       (ftp_source("fake-user:fake:pass"), "needs"),
       (ftp_source("fake-user:fake+pass"), "needs"),
       (ftp_source("fake-user:%ff"), "needs"),
       (ftp_source("fake-user:%4"), "needs"),
       (ftp_source("fake-user:%G1"), "needs"),
       ("ftp://mirror.example/a@b", "needs"),
       (ftp_source("u:" + "p" * 127), "128 bytes"),
       (ftp_source("fake-user:%41"), "control or unreserved"),
       (ftp_source("fake-user:%7E"), "control or unreserved"),
       (ftp_source("fake-user:%2D"), "control or unreserved"),
       (ftp_source("fake-user:%00"), "control or unreserved"),
       (ftp_source("fake-user:%1F"), "control or unreserved"),
       (ftp_source("fake-user:%7F"), "control or unreserved"),
       (ftp_source(location="fake@mirror.example"), "https:// source grammar"),
       (ftp_source(location="mirror.example:021"), "https:// source grammar"),
       (ftp_source(location="mirror.example/./a"), "https:// source grammar"),
       (ftp_source(location="mirror.example/a?b"), "https:// source grammar"),
       (ftp_source(location=""), "https:// source grammar"),
       (f"http://{FTP_USERINFO}@10.0.2.2", "credential-free"),
       (f"https://{FTP_USERINFO}@mirror.example", "credential-free"),
   )
   ```

2. Rename `test_plain_http_source_rule_matches_launcher` to `test_source_rule_matches_launcher`
   and change its loop header and expectation to:

   ```python
   refused = tuple(source for source, _ in FTP_REFUSED)
   cases = PLAIN_HTTP_ACCEPTED + PLAIN_HTTP_REFUSED + SOURCE_BASE_PATH_REFUSED
   for source in cases + FTP_ACCEPTED + refused:
       expected = source in PLAIN_HTTP_ACCEPTED + FTP_ACCEPTED
   ```

   After `test_rejects_noncanonical_source_base_path_without_echoing_it` add:

   ```python
   def test_rejects_ftp_source_without_echoing_it(self):
       for source, rule in FTP_REFUSED:
           with (
               self.subTest(source=source),
               self.assertRaisesRegex(
                   iso_chain.ValidationError, f"^manifest source: .*{rule}"
               ) as caught,
           ):
               self.load(manifest_data(source=source))
           for fragment in ("fake", "ppppp", "mirror.example", "10.0.2.2"):
               self.assertNotIn(fragment, str(caught.exception))
   ```

   Run both focused commands; expect the red failures above.
3. In `scripts/iso_chain.py`, after `URI_PATH` add:

   ```python
   MAX_FTP_USERINFO_BYTES = 128
   # ADR 0027: RFC 3986 unreserved characters and upper-case percent escapes.
   FTP_USERINFO_PART = re.compile(r"(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+")
   ```

   Replace the first line of `_validate_source`'s body with:

   ```python
   source = _string(value, field)
   if source.startswith("ftp://"):
       userinfo, _, location = source.removeprefix("ftp://").partition("@")
       _validate_ftp_userinfo(userinfo, field)
       try:
           _validate_source("https://" + location, field)
       except ValidationError as error:
           message = "ftp:// host, port, and path must follow the https:// source grammar"
           raise ValidationError(f"manifest {field}: {message}") from error
       return source
   if not source.startswith(("http://", "https://")):
       _manifest_error(field, "must use the canonical lower-case http://, https://, or ftp:// scheme")
   _validate_origin(source, field)
   ```

   and add after `_validate_source`:

   ```python
   def _validate_ftp_userinfo(userinfo: str, field: str) -> None:
       user, colon, password = userinfo.partition(":")
       if not colon or not all(FTP_USERINFO_PART.fullmatch(part) for part in (user, password)):
           _manifest_error(
               field,
               "ftp:// needs <user>:<password>@ of unreserved characters and upper-case %XX escapes",
           )
       if len(userinfo) > MAX_FTP_USERINFO_BYTES:  # ASCII once the pattern matched
           _manifest_error(field, "ftp:// userinfo exceeds 128 bytes")
       for escape in re.findall(r"%([0-9A-F]{2})", userinfo):
           octet = int(escape, 16)
           if octet < 0x20 or octet == 0x7F or re.fullmatch(r"[A-Za-z0-9._~-]", chr(octet)):
               _manifest_error(
                   field, "ftp:// userinfo escapes must not encode a control or unreserved character"
               )
   ```

4. In `assets/dracut/iso-chain-launch.sh`, add before `valid_source`:

   ```sh
   # ADR 0027: unreserved characters and upper-case %XX escapes, refusing control octets and
   # escaped unreserved characters; scripts/iso_chain.py _validate_ftp_userinfo is the twin.
   valid_userinfo_part() {
       case "$1" in '' | *[!A-Za-z0-9._~%-]*) return 1 ;; esac
       userinfo_rest=$1
       while :; do
           case "$userinfo_rest" in *%*) userinfo_rest=${userinfo_rest#*%} ;; *) return 0 ;; esac
           case "$userinfo_rest" in
           [01][0-9A-F]* | 7F* | 2[DE]* | 3[0-9]* | 4[1-9A-F]* | 5[0-9AF]* | 6[1-9A-F]* | 7[0-9AE]*)
               return 1
               ;;
           [0-9A-F][0-9A-F]*) userinfo_rest=${userinfo_rest#??} ;;
           *) return 1 ;;
           esac
       done
   }

   valid_ftp_userinfo() {
       [ "${#1}" -le 128 ] || return 1
       case "$1" in *:*:*) return 1 ;; *:*) ;; *) return 1 ;; esac
       valid_userinfo_part "${1%%:*}" && valid_userinfo_part "${1#*:}"
   }
   ```

   In `valid_source`, add this arm before `*) return 1 ;;`:

   ```sh
   ftp://*@*)
       scheme=ftp
       authority=${source#ftp://}
       valid_ftp_userinfo "${authority%%@*}" || return 1
       authority=${authority#*@}
       ;;
   ```

   and replace its last line with `[ "$scheme" != http ] || plain_http_host "$host"`.
5. Run both focused commands; expect `OK`. Run `just fix`; expect exit 0. Commit
   `feat: accept ftp:// sources with userinfo in build and the launcher`.

## Task 2: Downstream contracts held

Interfaces: consumes `ftp_source`, `FTP_USERINFO` from Task 1 and existing `manifest_data`,
`base_manifest`, `target_request`, `BuildTests.args`, `iso_chain._kernel_arguments`,
`iso_chain._grub_config`, `iso_chain.load_manifest_bytes`, `iso_chain.build_iso`,
`iso_chain._validate_origin`. Provides no new interface.

Verification (each test passes once added, because Task 1 implemented the rule; red
observations use a temporary edit undone with `git restore <file>`):

- Mode: focused-test. Contract: spec Success 3.
  `BuildTests.test_longest_ftp_userinfo_fits_command_line_and_grub_quoting`; red when
  `scripts/iso_chain.py` is restored from `main`, as a `ValidationError` on the FTP source.
- Mode: focused-test. Contract: spec Success 4. `TargetRequestTests.test_composes_ftp_base_source`;
  red under the same restore.
- Mode: focused-test, regression guard. Contract: spec Success 2 (no command).
  `BuildTests.test_refuses_ftp_source_before_any_command`; it passes on `main` too, and catches
  manifest validation moved after the first `subprocess.run` call.
- Mode: focused-test, regression guard. Contract: spec Success 5.
  `BuildTests.test_publish_url_stays_credential_free`; it passes on `main` too, and catches
  `_validate_origin` admitting `ftp://` or userinfo.
- Mode: focused-test. Contract: spec Success 6. `bash tests/test_iso_chain_launch.sh` prints
  `launcher shell tests: passed`; red with Task 1 step 4 reverted as `FTP source was rejected`.

Steps:

1. Add to `BuildTests`:

   ```python
   def test_longest_ftp_userinfo_fits_command_line_and_grub_quoting(self):
       source = ftp_source("u:" + "p" * 126, "mirror.example/pub/fedora")
       manifest, _, digest = iso_chain.load_manifest_bytes(
           json.dumps(manifest_data(source=source)).encode()
       )
       arguments = iso_chain._kernel_arguments(manifest, digest, "fedora")
       self.assertIn(f"iso_chain.source={source}", arguments)
       config = iso_chain._grub_config(manifest, digest)
       self.assertIn(f"set iso_chain_args_0='{' '.join(arguments)}'\n", config)


   def test_refuses_ftp_source_before_any_command(self):
       data = json.loads(self.config.read_text())
       self.config.write_text(json.dumps({**data, "source": ftp_source("fake-user:%41")}))
       with (
           mock.patch("scripts.iso_chain.subprocess.run") as run,
           self.assertRaisesRegex(iso_chain.ValidationError, "^manifest source: ") as caught,
       ):
           iso_chain.build_iso(self.args())
       run.assert_not_called()
       self.assertNotIn("fake", str(caught.exception))


   def test_publish_url_stays_credential_free(self):
       ftp_url = ftp_source(location="media.example/iso")
       for url in (ftp_url, f"https://{FTP_USERINFO}@media.example"):
           with self.subTest(url=url), self.assertRaises(iso_chain.ValidationError):
               iso_chain._validate_origin(url, "publish_url")
   ```

2. Add to `TargetRequestTests`:

   ```python
   def test_composes_ftp_base_source(self):
       self.base.write_text(json.dumps(base_manifest(source=ftp_source(location="192.0.2.2"))))
       manifest, _, _ = self.compose(target_request())
       self.assertEqual(manifest.source, ftp_source(location="192.0.2.2"))
   ```

3. In `tests/test_iso_chain_launch.sh`, after the HTTPS base-path case add:

   ```bash
   ftp_userinfo=fake-user:fake%25pass
   ftp_cmdline=$(command_line)
   ftp_cmdline=${ftp_cmdline/iso_chain.source=http:\/\/10.0.2.2/iso_chain.source=ftp:\/\/${ftp_userinfo}@192.0.2.2\/pub}
   run_launcher "eth0" "" 206 "$ftp_cmdline"
   grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "FTP source was rejected"
   grep -qx 'artifacts: passed' "$RUN_OUTPUT" || fail "FTP artifacts were not downloaded"
   grep -Fq "ftp://${ftp_userinfo}@192.0.2.2/pub/repository/.treeinfo" "$RUN_CALLS" ||
       fail "FTP artifact request was not preserved"
   run_launcher "eth0" curl 206 "$ftp_cmdline"
   grep -qx 'kernel-http: failed' "$RUN_OUTPUT" || fail "FTP transfer failure missed fixed marker"
   if grep -q fake "$RUN_OUTPUT"; then fail "FTP transfer failure echoed the userinfo"; fi
   for refused_source in "ftps://${ftp_userinfo}@192.0.2.2" ftp://192.0.2.2 \
       "ftp://${ftp_userinfo%%:*}@192.0.2.2"; do
       invalid_cmdline=$(command_line)
       invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/10.0.2.2/iso_chain.source=$refused_source}
       assert_configuration_rejected "refused FTP source" "$invalid_cmdline"
       if grep -q fake "$RUN_OUTPUT"; then fail "refused FTP source echoed the userinfo"; fi
   done
   ```

4. Run `just fix`; expect exit 0. Commit `test: hold FTP sources' downstream contracts`.

## Task 3: Documentation

Verification:

- Mode: task-test-not-applicable. Surface: README, AGENTS.md, v4 spec prose. Reason: no
  executable consumer reads these sentences; `just check-markdown` checks only their format.

Steps:

1. README: replace "Authenticated FTP sources are not accepted yet (ADR 0016, issue #37)." with
   the grammar of spec Rule items 1–4 in two sentences, `ftps://` and HTTP(S) userinfo refused,
   the credential on the ISO and command lines (ADR 0016). In the `validate-external-source`
   paragraph, bound "credentials ... are rejected" and say it does not support `ftp://` until
   #69: on one it attempts the FTP login and transfer, then fails with a non-200 error.
2. AGENTS.md: replace "Authenticated FTP sources are not accepted yet:" with "`build` and the
   launcher accept authenticated FTP sources:" and end that sentence with #69, #70, and #37's
   remaining work instead of "issue #37 owns the implementation"; bound "no credential use"
   under No fallbacks to "beyond an `ftp://` source's userinfo (ADR 0027)"; in Security
   invariants drop "once #68 implements it".
3. v4 spec `source` bullet: add "or `ftp://` with userinfo on any host (ADR 0027)".
4. `just check`; expect exit 0. Commit `docs: describe accepted ftp:// sources`.
